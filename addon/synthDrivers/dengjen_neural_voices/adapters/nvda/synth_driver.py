import typing
from asyncio.exceptions import CancelledError as AsyncioCancelledError
from collections import OrderedDict
from contextlib import suppress

import addonHandler
import config
import languageHandler
import ui
from autoSettingsUtils.driverSetting import (
    BooleanDriverSetting,
    DriverSetting,
    NumericDriverSetting,
)
from logHandler import log
from nvwave import WavePlayer
from speech import sayAll
from speech.commands import (
    BreakCommand,
    IndexCommand,
    LangChangeCommand,
    PitchCommand,
    RateCommand,
    VolumeCommand,
)
from synthDriverHandler import (
    SynthDriver as NvdaSynthDriver,
)
from synthDriverHandler import (
    VoiceInfo,
    synthDoneSpeaking,
    synthIndexReached,
)

from ... import aio
from ..._config import DengjenConfig
from ...aio import (
    CancelledError,
    asyncio,
    asyncio_cancel_task,
    asyncio_coroutine_to_concurrent_future,
    run_in_executor,
)
from ...const import FALLBACK_SPEAKER_NAME
from ...domain.audio_processing import AudioStreamProcessor
from ...domain.phrase_cache import phrase_cache
from ...domain.structural_reading import split_into_segments
from ...domain.tts_system import (
    DengjenTextToSpeechSystem,
    SpeakerNotFoundError,
    SpeechOptions,
    VoiceNotFoundError,
)
from ...helpers import update_displaied_params_on_voice_change
from ...ports.tts_backend import BackendError, BackendUnavailableError

addonHandler.initTranslation()


def _bootstrap_backend():  # pragma: no cover
    """Construct and start the production TTS backend.

    A module-level function (not inline in SynthDriver.__init__) so tests can
    replace it wholesale via monkeypatch -- NVDA constructs SynthDriver()
    with zero arguments, so the backend cannot be a constructor parameter.

    Imports DengjenGrpcBackend lazily: this keeps the vendored, Windows-only
    grpc dependency out of every code path that doesn't actually need to talk
    to the engine (in particular, out of every test that monkeypatches this
    function before SynthDriver() is ever constructed).
    """
    from ..dengjen_grpc import DengjenGrpcBackend

    aio.ensure_running()
    backend = DengjenGrpcBackend()
    backend.initialize()
    version = backend.check_version()
    log.info(f"Dengjen GRPC server version: {version}")
    return backend


class DoneSpeakingTask:
    """Waits on every player used by the sequence, not just one -- a
    mid-sequence LangChangeCommand can switch to a voice with a different
    sample rate, and each rate gets its own WavePlayer (see
    _get_or_create_player)."""

    __slots__ = ["on_index_reached", "players"]

    def __init__(self, players, on_index_reached):
        self.players = players
        self.on_index_reached = on_index_reached

    async def __call__(self):
        for player in self.players:
            await run_in_executor(player.idle)
        await run_in_executor(self.on_index_reached, None)


class IndexReachedTask:
    __slots__ = ["callback", "index_list"]

    def __init__(self, callback, index_list):
        self.callback = callback
        self.index_list = index_list

    async def __call__(self):
        for index in self.index_list:
            await run_in_executor(self.callback, index)


def _get_focus_pan() -> float:
    try:
        import api
        import wx

        obj = api.getFocusObject()
        if obj is None or obj.location is None:
            return 0.0
        loc = obj.location
        screen_width = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_X)
        if screen_width <= 0:
            return 0.0
        centre_x = loc.left + loc.width / 2.0
        pan = (centre_x / screen_width) * 2.0 - 1.0
        return max(-1.0, min(1.0, pan))
    except Exception:
        return 0.0


class SpeechTask:
    __slots__ = [
        "night_mode",
        "normalize",
        "pan",
        "player",
        "spatial_audio",
        "speaker",
        "task",
    ]

    def __init__(
        self,
        task,
        player,
        normalize=False,
        spatial_audio=False,
        night_mode=False,
        pan=0.0,
        speaker=None,
    ):
        self.task = task
        self.player = player
        self.normalize = normalize
        self.spatial_audio = spatial_audio
        self.night_mode = night_mode
        self.pan = pan
        self.speaker = speaker

    def _check_cache(self, voice_key, rate, volume, pitch, speaker):
        if self.spatial_audio:
            return None
        return phrase_cache.get(
            self.task.text,
            voice_key,
            rate,
            volume,
            pitch,
            normalize=self.normalize,
            night_mode=self.night_mode,
            speaker=speaker,
        )

    async def _play_chunks(self, chunks):
        feed_func = self.player.feed
        for chunk in chunks:
            await run_in_executor(feed_func, chunk)
        await run_in_executor(self.player.sync)

    def _create_processor(self):
        if not (self.night_mode or self.normalize or self.spatial_audio):
            return None
        pan = self.pan if self.spatial_audio else 0.0
        return AudioStreamProcessor(
            normalize=self.normalize,
            night_mode=self.night_mode,
            spatial_audio=self.spatial_audio,
            pan=pan,
        )

    async def _synthesize_and_stream(self, processor):
        collected = []
        feed_func = self.player.feed
        async for wave_samples in self.task.generate_audio():
            chunk = wave_samples
            if processor is not None:
                chunk = await run_in_executor(processor.process_chunk, chunk)
            if chunk:
                collected.append(chunk)
                await run_in_executor(feed_func, chunk)
        if processor is not None:
            final_chunk = await run_in_executor(processor.flush)
            if final_chunk:
                collected.append(final_chunk)
                await run_in_executor(feed_func, final_chunk)
        await run_in_executor(self.player.sync)
        return collected

    async def __call__(self):
        if sayAll.SayAllHandler.isRunning():
            self.task.text = self.task.text.replace("\n", " ")
            self.task.speech_options.sentence_silence_ms = 50

        voice = self.task.speech_options.voice
        voice_key = voice.key
        orig_speaker = await run_in_executor(getattr, voice, "speaker", None)
        speaker = self.speaker if self.speaker is not None else orig_speaker

        def _apply_speaker(spk):
            try:
                voice.speaker = spk
                return True
            except Exception:
                log.debug("Failed setting task speaker", exc_info=True)
                return False

        applied_custom_speaker = False
        speaker_applied = True
        if self.speaker is not None and self.speaker != orig_speaker:
            applied_custom_speaker = await run_in_executor(_apply_speaker, self.speaker)
            speaker_applied = applied_custom_speaker

        try:
            rate = self.task.speech_options.rate
            volume = self.task.speech_options.volume
            pitch = self.task.speech_options.pitch

            cached = self._check_cache(voice_key, rate, volume, pitch, speaker)
            if cached is not None:
                await self._play_chunks(cached)
                return

            processor = self._create_processor()
            collected_chunks = await self._synthesize_and_stream(processor)

            if not self.spatial_audio and collected_chunks and speaker_applied:
                phrase_cache.put(
                    self.task.text,
                    voice_key,
                    rate,
                    volume,
                    pitch,
                    self.normalize,
                    self.night_mode,
                    collected_chunks,
                    speaker=speaker,
                )
        finally:
            if applied_custom_speaker:
                await run_in_executor(_apply_speaker, orig_speaker)


class BreakTask:
    __slots__ = ["player", "task"]

    def __init__(self, task, player):
        self.task = task
        self.player = player

    async def __call__(self):
        await run_in_executor(self.player.feed, self.task.generate_audio())
        await run_in_executor(self.player.sync)


def speaker_setting():
    """Factory function for creating speaker setting."""
    return DriverSetting(
        "speaker",
        _("&Speaker"),
        availableInSettingsRing=True,
        displayName=_("Speaker"),
    )


def create_wave_player(sample_rate, channels=1):
    return WavePlayer(channels=channels, samplesPerSec=sample_rate, bitsPerSample=16)


async def _process_speech_sequence(speech_seq):
    failed = False
    for task in speech_seq:
        if failed and not isinstance(task, (IndexReachedTask, DoneSpeakingTask)):
            continue
        try:
            await task()
        except (AsyncioCancelledError, CancelledError):
            log.debug(f"Canceled speech task {task}", exc_info=True)
            break
        except Exception:
            log.exception(f"Failed to execute speech task {task}", exc_info=True)
            failed = True


@asyncio_coroutine_to_concurrent_future
async def process_speech(speech_seq):
    speech_task = _process_speech_sequence(speech_seq)
    return asyncio.get_running_loop().create_task(speech_task)


class SynthDriver(NvdaSynthDriver):
    supportedSettings = (
        NvdaSynthDriver.VoiceSetting(),
        NvdaSynthDriver.VariantSetting(),
        speaker_setting(),
        NvdaSynthDriver.RateSetting(),
        NvdaSynthDriver.RateBoostSetting(),
        NvdaSynthDriver.VolumeSetting(),
        NvdaSynthDriver.PitchSetting(),
        NumericDriverSetting("noise_scale", _("&Noise scale"), False),
        NumericDriverSetting("length_scale", _("&Length scale"), True),
        NumericDriverSetting("noise_w", _("Noise &w"), False),
        BooleanDriverSetting("night_mode", _("&Night mode"), defaultVal=False),
        BooleanDriverSetting(
            "normalize_audio", _("&Normalize audio volume"), defaultVal=False
        ),
        BooleanDriverSetting(
            "spatial_audio", _("&Spatial audio (stereo panning)"), defaultVal=False
        ),
        BooleanDriverSetting(
            "structural_reading",
            _("Alternate &speaker for brackets and quotes"),
            defaultVal=False,
        ),
    )
    supportedCommands: typing.ClassVar = {
        IndexCommand,
        LangChangeCommand,
        BreakCommand,
        RateCommand,
        VolumeCommand,
        PitchCommand,
    }
    supportedNotifications: typing.ClassVar = {synthIndexReached, synthDoneSpeaking}

    description = "Dengjen Neural Voices"
    name = "dengjen_neural_voices"
    cachePropertiesByDefault = False

    @classmethod
    def check(cls):
        return True

    def __init__(self):
        super().__init__()

        self._current_task = None
        self._rateBoost = False
        self.tts = None
        self._player = None
        self._players = {}
        self._active_players = set()
        self._current_speaker = None
        self._noise_scale_factor = None
        self._length_scale_factor = None
        self._noise_w_factor = None
        try:
            backend = _bootstrap_backend()
        except BackendUnavailableError:
            log.exception(
                "Failed to initialize Dengjen services. Synthesizer will not be available.",
                exc_info=True,
            )
            return
        except Exception:
            log.exception(
                "Unexpected error initializing Dengjen services. Synthesizer will not be available.",
                exc_info=True,
            )
            return
        voices = DengjenTextToSpeechSystem.load_all_voices_from_nvda_config_dir(backend)
        if not any(voices):
            log.error(
                "No installed voices were found for Dengjen. Synthesizer will not be available."
            )
            return
        self.voices = voices
        try:
            voice_key = config.conf["speech"]["dengjen_neural_voices"]["voice"]
            configured_voice = next(
                filter(lambda v: v.key.startswith(voice_key), self.voices)
            )
        except (KeyError, StopIteration):
            configured_voice = self.voices[0]
        init_speech_options = SpeechOptions(voice=configured_voice)
        self.tts = DengjenTextToSpeechSystem(
            self.voices, speech_options=init_speech_options
        )
        # WavePlayers are created on first speech: opening one fails on a machine
        # with no audio device, and the synth must still load there.
        self.availableLanguages = {v.language for v in self.voices}
        self._voice_map = {v.key: v for v in self.voices}
        self._standard_voice_map = {v.standard_variant_key: v for v in self.voices}
        self.availableVoices = self._get_valid_voices()
        self.__voice = None

    def terminate(self):
        self.cancel()
        if self.tts is not None:
            self.tts.shutdown()
        for player in self._players.values():
            player.close()
        self._players.clear()
        self._player = None
        self._active_players = set()

    def speak(self, speechSequence):
        if self.tts is None:
            log.error("speak() called with no TTS backend available; dropping speech.")
            return
        with self.tts.create_synthesis_context():
            self._fast_prepare_and_run_speech_task(speechSequence)

    def _fast_prepare_and_run_speech_task(self, speech_sequence):
        self.cancel()
        self._current_task = process_speech(
            self._build_speech_tasks(speech_sequence)
        ).result()

    def _build_speech_tasks(self, speech_sequence):
        speech_seq = []
        text_list = []
        index_command_list = []
        default_lang = self.tts.language
        self._player = self._get_or_create_player(
            self.tts.speech_options.voice.sample_rate
        )
        players_used = {self._player}
        for item in speech_sequence:
            item_type = type(item)
            if item_type is IndexCommand:
                index_command_list.append(item.index)
                continue
            if item_type is str:
                text_list.append(item)
                continue

            if text_list:
                speech_seq.extend(self._create_speech_tasks(text_list))
                text_list.clear()
            break_task = self._apply_speech_command(item, default_lang)
            if break_task is not None:
                speech_seq.append(break_task)
            players_used.add(self._player)
        if text_list:
            speech_seq.extend(self._create_speech_tasks(text_list))
        if index_command_list:
            speech_seq.append(
                IndexReachedTask(self._on_index_reached, index_command_list)
            )
        speech_seq.append(DoneSpeakingTask(players_used, self._on_index_reached))
        self._active_players = players_used
        return speech_seq

    def _create_speech_tasks(self, text_list):
        joined_text = "\n".join(text_list)
        do_norm = self._get_normalize_audio()
        do_spatial = self._get_spatial_audio()
        do_night = self._get_night_mode()
        do_struct = self._get_structural_reading()
        pan = _get_focus_pan() if do_spatial else 0.0

        voice = self.tts.speech_options.voice
        if (
            do_struct
            and getattr(voice, "is_multi_speaker", False)
            and len(getattr(voice, "speaker_names", [])) >= 2
        ):
            default_spk = self._active_speaker(voice)
            spk_names = voice.speaker_names
            alt_spk = spk_names[1] if spk_names[0] == default_spk else spk_names[0]
            segments = split_into_segments(
                joined_text, default_speaker=default_spk, alt_speaker=alt_spk
            )
            tasks = []
            for seg in segments:
                tasks.append(
                    SpeechTask(
                        self.tts.create_speech_provider(seg.text),
                        self._player,
                        normalize=do_norm,
                        spatial_audio=do_spatial,
                        night_mode=do_night,
                        pan=pan,
                        speaker=seg.speaker_name,
                    )
                )
            return tasks

        return [
            SpeechTask(
                self.tts.create_speech_provider(joined_text),
                self._player,
                normalize=do_norm,
                spatial_audio=do_spatial,
                night_mode=do_night,
                pan=pan,
                speaker=self._active_speaker(voice),
            )
        ]

    def _current_voice_key(self):
        options = getattr(self.tts, "speech_options", None)
        return getattr(getattr(options, "voice", None), "key", None)

    @property
    def _current_speaker(self):
        key, speaker = getattr(self, "_speaker_cache", (None, None))
        return speaker if key == self._current_voice_key() else None

    @_current_speaker.setter
    def _current_speaker(self, speaker):
        self._speaker_cache = (self._current_voice_key(), speaker)

    def _active_speaker(self, voice):
        spk = getattr(self, "_current_speaker", None)
        if spk is None:
            spk = getattr(voice, "default_speaker", None)
        if spk is None:
            with suppress(Exception):
                spk = voice.speaker
        if spk is None:
            spk = FALLBACK_SPEAKER_NAME
        self._current_speaker = spk
        return spk

    def _apply_speech_command(self, item, default_lang):
        item_type = type(item)
        if item_type is BreakCommand:
            return BreakTask(
                self.tts.create_break_provider(item.time),
                self._player,
            )
        if item_type is LangChangeCommand:
            with suppress(VoiceNotFoundError):
                self.tts.language = default_lang if item.isDefault else item.lang
            voice = self.tts.speech_options.voice
            self._player = self._get_or_create_player(voice.sample_rate)
        elif item_type is RateCommand:
            self.tts.rate = item.newValue
        elif item_type is VolumeCommand:
            self.tts.volume = item.newValue
        elif item_type is PitchCommand:
            self.tts.pitch = item.newValue
        return None

    def cancel(self):
        if self._current_task is not None:
            asyncio_cancel_task(self._current_task)
        for player in self._active_players:
            player.stop()

    def pause(self, switch):
        for player in self._active_players:
            player.pause(switch)

    def _on_index_reached(self, index):
        if index is not None:
            synthIndexReached.notify(synth=self, index=index)
        else:
            synthDoneSpeaking.notify(synth=self)

    def _get_night_mode(self):
        return getattr(self, "_night_mode_enabled", False)

    def _set_night_mode(self, value):
        self._night_mode_enabled = bool(value)
        phrase_cache.clear()

    def _get_normalize_audio(self):
        return getattr(self, "_normalize_audio_enabled", False)

    def _set_normalize_audio(self, value):
        self._normalize_audio_enabled = bool(value)
        phrase_cache.clear()

    def _get_spatial_audio(self):
        return getattr(self, "_spatial_audio_enabled", False)

    def _set_spatial_audio(self, value):
        self._spatial_audio_enabled = bool(value)
        phrase_cache.clear()
        self._player = None

    def _get_structural_reading(self):
        return getattr(self, "_structural_reading_enabled", False)

    def _set_structural_reading(self, value):
        self._structural_reading_enabled = bool(value)

    def _get_or_create_player(self, sample_rate):
        channels = 2 if self._get_spatial_audio() else 1
        key = sample_rate if channels == 1 else (sample_rate, channels)
        if key not in self._players:
            player, key = self._open_player(sample_rate, channels)
            player.setVolume(all=self.tts.volume / 100)
            self._players[key] = player
        return self._players[key]

    def _open_player(self, sample_rate, channels):
        if channels == 1:
            return create_wave_player(sample_rate), sample_rate
        try:
            player = create_wave_player(sample_rate, channels=channels)
            return player, (sample_rate, channels)
        except (TypeError, OSError):
            log.warning(
                "Stereo playback is unavailable; turning spatial audio off",
                exc_info=True,
            )
            self._spatial_audio_enabled = False
            existing = self._players.get(sample_rate)
            return existing or create_wave_player(sample_rate), sample_rate

    def _get_rateBoost(self):
        return self._rateBoost

    def _set_rateBoost(self, enable):
        if enable != self._rateBoost:
            rate = self.rate
            self._rateBoost = enable
            self.rate = rate

    def _get_rate(self):
        if self._rateBoost:
            return self.tts.rate
        else:
            self.tts.rate = min(40, self.tts.rate)
            return int(self.tts.rate * 2.5)

    def _set_rate(self, value):
        if self._rateBoost:
            self.tts.rate = value
        else:
            self.tts.rate = int(self._percentToParam(value, 0, 40))

    def _get_volume(self):
        return self.tts.volume

    def _set_volume(self, value):
        self.tts.volume = value
        for player in self._players.values():
            player.setVolume(all=value / 100)

    def _get_pitch(self):
        return self.tts.pitch

    def _set_pitch(self, value):
        self.tts.pitch = value

    def _get_voice(self):
        return self._get_variant_independent_voice_id(self.tts.voice)

    _SCALE_SETTINGS: typing.ClassVar = {
        "noise_scale": {
            "factor_attr": "_noise_scale_factor",
            "multiplier": 3,
            "skip_if_unchanged": False,
        },
        "length_scale": {
            "factor_attr": "_length_scale_factor",
            "multiplier": 2,
            "skip_if_unchanged": False,
        },
        "noise_w": {
            "factor_attr": "_noise_w_factor",
            "multiplier": 3,
            "skip_if_unchanged": True,
        },
    }

    def _get_scale_factor(self, name):
        factor_attr = self._SCALE_SETTINGS[name]["factor_attr"]
        factor = getattr(self, factor_attr, None)
        if factor is not None:
            return factor
        if self.voice in DengjenConfig:
            factor = DengjenConfig[self.voice].get(name, 50)
            setattr(self, factor_attr, factor)
            return factor
        return 50

    def _set_scale_factor(self, name, value, force=False):
        spec = self._SCALE_SETTINGS[name]
        factor_attr = spec["factor_attr"]
        if (
            not force
            and spec["skip_if_unchanged"]
            and getattr(self, factor_attr, None) == value
        ):
            return
        try:
            self._push_scale(self.tts.speech_options.voice, name, value, spec)
        except BackendError:
            log.exception(f"Could not apply {name}: the speech engine is unreachable")
        setattr(self, factor_attr, value)
        phrase_cache.clear()

    def _push_scale(self, voice, name, value, spec):
        default = getattr(voice.default_scales, name)
        if value == 50:
            setattr(voice, name, default)
        else:
            setattr(
                voice,
                name,
                max(
                    0.1,
                    round(
                        self._percentToParam(value, 0.0, default * spec["multiplier"]),
                        2,
                    ),
                ),
            )

    def _reapply_scale_settings(self):

        for name in self._SCALE_SETTINGS:
            self._set_scale_factor(name, self._get_scale_factor(name), force=True)

    def _get_noise_scale(self):
        return self._get_scale_factor("noise_scale")

    def _set_noise_scale(self, value):
        self._set_scale_factor("noise_scale", value)

    def _get_length_scale(self):
        return self._get_scale_factor("length_scale")

    def _set_length_scale(self, value):
        self._set_scale_factor("length_scale", value)

    def _get_noise_w(self):
        return self._get_scale_factor("noise_w")

    def _set_noise_w(self, value):
        self._set_scale_factor("noise_w", value)

    def _set_voice(self, value):
        if value not in self.availableVoices:
            value = next(iter(self.availableVoices))
        try:
            self.tts.voice = self._standard_voice_map[value].key
        except Exception:
            log.exception(f"Failed to load voice `{value}`")
            ui.message(
                _("Failed to load voice {voice}. Keeping the previous voice.").format(
                    voice=self.availableVoices[value].displayName
                )
            )
            return
        self.__voice = value
        phrase_cache.clear()
        with suppress(AttributeError):
            del self._availableVariants
        with suppress(AttributeError):
            del self._availableSpeakers
        if value in DengjenConfig:
            variant = DengjenConfig[value].get("variant", self.variant)
            speaker = DengjenConfig[value].get("speaker")
        else:
            variant = self._standard_voice_map[value].variant
            speaker = None
        self._set_variant(variant)

        if speaker is not None:
            self._set_speaker(speaker)
        else:
            voice_obj = getattr(
                getattr(self.tts, "speech_options", None), "voice", None
            )
            self._current_speaker = getattr(voice_obj, "default_speaker", None)
        try:
            update_displaied_params_on_voice_change(self)
        except Exception:
            log.exception("Failed to update Speech GUI", exc_info=True)

    def _get_language(self):
        return self.tts.language

    def _set_language(self, value):
        self.tts.language = value

    def _get_variant(self):
        return self.tts.speech_options.voice.variant

    def _set_variant(self, value):
        variant = value.lower()
        if variant == "standard":
            voice_key = self.tts.speech_options.voice.standard_variant_key
        elif variant == "fast":
            voice_key = self.tts.speech_options.voice.fast_variant_key
        else:
            log.info(f"Unknown voice variant: {variant}")
            return
        if voice_key not in self._voice_map:
            return
        prev_speaker = getattr(self, "_current_speaker", None)
        if prev_speaker is None:
            with suppress(Exception):
                prev_speaker = self.tts.speech_options.voice.speaker
        self.tts.voice = voice_key
        if prev_speaker is not None:
            with suppress(Exception):
                self.tts.speech_options.voice.speaker = prev_speaker
        self._current_speaker = prev_speaker
        DengjenConfig.setdefault(self.voice, {})["variant"] = value

        self._reapply_scale_settings()

    def _getAvailableVariants(self):
        std_key, rt_key = DengjenTextToSpeechSystem.get_voice_variants(self.__voice)
        rv = OrderedDict()
        if std_key in self._voice_map:
            rv["standard"] = VoiceInfo("standard", "Standard", self.language)
        if rt_key != std_key and rt_key in self._voice_map:
            rv["fast"] = VoiceInfo("fast", "Fast", self.language)
        return rv

    def _get_variant_independent_voice_id(self, voice_key):
        return DengjenTextToSpeechSystem.get_voice_variants(voice_key)[0]

    def _get_valid_voices(self):
        all_voices = OrderedDict()
        for voice in self.voices:
            voice_id = self._get_variant_independent_voice_id(voice.key)
            quality = voice.properties.get("quality")
            lang = languageHandler.normalizeLanguage(voice.language).replace("_", "-")
            display_name = (
                f"{voice.name} ({lang}) - {quality}"
                if quality
                else f"{voice.name} ({lang})"
            )
            all_voices[voice_id] = VoiceInfo(voice_id, display_name, voice.language)
        return all_voices

    def _get_speaker(self):
        if self._current_speaker is not None:
            return self._current_speaker
        spk = self.tts.speaker
        self._current_speaker = spk
        return spk

    def _set_speaker(self, value):
        try:
            self.tts.speaker = value
            self._current_speaker = value
            DengjenConfig.setdefault(self.voice, {})["speaker"] = value
        except SpeakerNotFoundError:
            self._current_speaker = self.tts.speaker
            DengjenConfig.setdefault(self.voice, {})["speaker"] = self._current_speaker
        except BackendError:
            log.exception(
                "Could not apply the speaker: the speech engine is unreachable"
            )
            self._current_speaker = value
            DengjenConfig.setdefault(self.voice, {})["speaker"] = value
        phrase_cache.clear()

    def _get_availableSpeakers(self):
        return {spk: VoiceInfo(spk, spk, None) for spk in self.tts.get_speakers()}
