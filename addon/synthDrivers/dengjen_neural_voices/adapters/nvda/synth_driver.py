import asyncio as _std_asyncio
import math
import threading
import typing
from asyncio.exceptions import CancelledError as AsyncioCancelledError
from collections import OrderedDict
from contextlib import suppress
from functools import partial
from weakref import WeakKeyDictionary

import addonHandler
import config
import languageHandler
import ui
import wx
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
    findAndSetNextSynth,
    getSynth,
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
from ...domain.model_profiles import profile_for
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

_DEFAULT_SAY_ALL_SENTENCE_SILENCE_MS = 50
_MAX_SENTENCE_PAUSE_MS = 500
_RATE_LENGTH_SCALE_FLOOR = 0.75
_MAX_MODEL_RATE_SPEEDUP = 1.0 / _RATE_LENGTH_SCALE_FLOOR


class _VoiceScaleState:
    """Per-voice synchronization state shared by persistent pushes and task overrides."""

    __slots__ = (
        "active_override",
        "async_locks",
        "io_lock",
        "meta_lock",
        "persistent_length_scale",
        "version",
    )

    def __init__(self):
        self.io_lock = threading.Lock()
        self.meta_lock = threading.Lock()
        self.async_locks: WeakKeyDictionary = WeakKeyDictionary()
        self.active_override = False
        self.version = 0
        self.persistent_length_scale = None


_FALLBACK_SCALE_STATES: dict[int, _VoiceScaleState] = {}
_FALLBACK_SCALE_STATES_LOCK = threading.Lock()


def _rate_to_speed(engine_rate):
    """Convert an engine rate step (0-100) to its Sonic speed multiplier."""
    return 0.5 + 0.05 * engine_rate


def _speed_to_rate(speed):
    """Convert a Sonic speed multiplier back to an integer engine rate step."""
    return round((speed - 0.5) / 0.05)


def _get_voice_scale_state(voice) -> _VoiceScaleState:
    """Return the `_VoiceScaleState` attached to `voice`."""
    state = getattr(voice, "_nvda_scale_state", None)
    if isinstance(state, _VoiceScaleState):
        return state
    with _FALLBACK_SCALE_STATES_LOCK:
        state = getattr(voice, "_nvda_scale_state", None)
        if isinstance(state, _VoiceScaleState):
            return state
        state = _FALLBACK_SCALE_STATES.get(id(voice))
        if state is None:
            state = _VoiceScaleState()
            try:
                voice._nvda_scale_state = state
            except (AttributeError, TypeError):
                _FALLBACK_SCALE_STATES[id(voice)] = state
        return state


def _get_voice_lock(voice) -> _std_asyncio.Lock:
    """Return the per-loop `asyncio.Lock` serializing temporary overrides on `voice`."""
    state = _get_voice_scale_state(voice)
    loop = _std_asyncio.get_running_loop()
    with state.meta_lock:
        lock = state.async_locks.get(loop)
        if lock is None:
            lock = _std_asyncio.Lock()
            state.async_locks[loop] = lock
        return lock


async def _await_uncancellable(aw):
    """Await `aw` to completion before propagating any pending task cancellation."""
    fut = _std_asyncio.ensure_future(aw)
    cancelled = False
    while not fut.done():
        try:
            await _std_asyncio.shield(fut)
        except AsyncioCancelledError:
            if fut.done() and fut.cancelled():
                raise
            cancelled = True
    if cancelled:
        if not fut.cancelled():
            _ = fut.exception()
        raise AsyncioCancelledError
    return fut.result()


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
        "length_scale",
        "night_mode",
        "normalize",
        "on_scale_restore_error",
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
        length_scale=None,
        on_scale_restore_error=None,
    ):
        self.task = task
        self.player = player
        self.normalize = normalize
        self.spatial_audio = spatial_audio
        self.night_mode = night_mode
        self.pan = pan
        self.speaker = speaker
        self.length_scale = length_scale
        self.on_scale_restore_error = on_scale_restore_error

    def _check_cache(
        self, voice_key, rate, volume, pitch, speaker, sentence_silence_ms=None
    ):
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
            sentence_silence_ms=sentence_silence_ms,
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

    async def _apply_temporary_length_scale(self, voice, restore_box):
        """Temporarily override `voice.length_scale` when requested for this task.

        Populates `restore_box` with `[orig, start_version]` atomically under
        `state.io_lock` as soon as the override write succeeds so a concurrent
        cancellation cannot skip restoration.
        """
        if self.length_scale is None:
            return False

        def _apply_ls():
            state = _get_voice_scale_state(voice)
            with state.io_lock:
                start_version = state.version
                orig = voice.length_scale
                if orig is not None and math.isclose(
                    orig, self.length_scale, rel_tol=1e-4, abs_tol=1e-4
                ):
                    return False
                voice.length_scale = self.length_scale
                state.active_override = True
                restore_box[:] = [orig, start_version]
                return True

        return await _await_uncancellable(run_in_executor(_apply_ls))

    async def _restore_length_scale(self, voice, orig, start_version):
        """Restore `voice.length_scale` (or apply a newer persistent setting)."""

        def _set_ls():
            state = _get_voice_scale_state(voice)
            with state.io_lock:
                target = (
                    state.persistent_length_scale
                    if state.version != start_version
                    else orig
                )
                state.active_override = False
                try:
                    voice.length_scale = target
                    return True
                except Exception:
                    log.warning(
                        "Failed restoring voice length_scale after task override",
                        exc_info=True,
                    )
                    return False

        restored = await _await_uncancellable(run_in_executor(_set_ls))
        if not restored and self.on_scale_restore_error is not None:
            self.on_scale_restore_error()

    async def _apply_temporary_speaker(self, voice, restore_box):
        """Temporarily override `voice.speaker` when requested for this task."""

        def _apply_spk():
            orig = getattr(voice, "speaker", None)
            speaker = self.speaker if self.speaker is not None else orig
            if self.speaker is None or self.speaker == orig:
                return speaker, True
            try:
                voice.speaker = self.speaker
            except Exception:
                log.debug("Failed setting task speaker", exc_info=True)
                return speaker, False
            restore_box[:] = [orig]
            return speaker, True

        return await _await_uncancellable(run_in_executor(_apply_spk))

    @staticmethod
    async def _restore_speaker(voice, orig):
        """Restore `voice.speaker` after a per-task override."""

        def _set_spk():
            try:
                voice.speaker = orig
            except Exception:
                log.warning(
                    "Failed restoring voice speaker after task override",
                    exc_info=True,
                )

        await _await_uncancellable(run_in_executor(_set_spk))

    def _should_cache(self, collected_chunks, applied_custom_ls, speaker_applied):
        return (
            not self.spatial_audio
            and not applied_custom_ls
            and bool(collected_chunks)
            and speaker_applied
        )

    async def __call__(self):
        """Synthesize and feed the task's audio to the output player."""
        if sayAll.SayAllHandler.isRunning():
            self.task.text = self.task.text.replace("\n", " ")
            self.task.speech_options.sentence_silence_ms = max(
                self.task.speech_options.sentence_silence_ms or 0,
                _DEFAULT_SAY_ALL_SENTENCE_SILENCE_MS,
            )

        voice = self.task.speech_options.voice
        voice_key = voice.key
        async with _get_voice_lock(voice):
            speaker_restore_box = []
            ls_restore_box = []
            try:
                speaker, speaker_applied = await self._apply_temporary_speaker(
                    voice, speaker_restore_box
                )
                applied_custom_ls = await self._apply_temporary_length_scale(
                    voice, ls_restore_box
                )
                rate = self.task.speech_options.rate
                volume = self.task.speech_options.volume
                pitch = self.task.speech_options.pitch
                sentence_silence_ms = self.task.speech_options.sentence_silence_ms

                if not applied_custom_ls:
                    cached = self._check_cache(
                        voice_key, rate, volume, pitch, speaker, sentence_silence_ms
                    )
                    if cached is not None:
                        await self._play_chunks(cached)
                        return

                processor = self._create_processor()
                collected_chunks = await self._synthesize_and_stream(processor)

                if self._should_cache(
                    collected_chunks, applied_custom_ls, speaker_applied
                ):
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
                        sentence_silence_ms=sentence_silence_ms,
                    )
            finally:
                try:
                    if ls_restore_box:
                        await self._restore_length_scale(
                            voice, ls_restore_box[0], ls_restore_box[1]
                        )
                finally:
                    if speaker_restore_box:
                        await self._restore_speaker(voice, speaker_restore_box[0])


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
        NumericDriverSetting(
            "sentence_pause",
            _("Sentence &pause (5 ms per step at normal speed)"),
            False,
            defaultVal=0,
        ),
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
        """Initialize driver state, backend connection, and installed voices."""
        self._sentence_pause = 0
        self._rateBoost = False
        self._raw_engine_rate = None
        self._pushed_length_scale = None
        self.tts = None
        super().__init__()

        self._current_task = None
        self._player = None
        self._players = {}
        self._active_players = set()
        self._deferred_speech = None
        self._scaled_voice = None
        self._switch_origin = None
        self._terminated = False
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
        self._apply_sentence_pause()
        # WavePlayers are created on first speech: opening one fails on a machine
        # with no audio device, and the synth must still load there.
        self.availableLanguages = {v.language for v in self.voices}
        self._voice_map = {v.key: v for v in self.voices}
        self._standard_voice_map = {v.standard_variant_key: v for v in self.voices}
        self.availableVoices = self._get_valid_voices()
        self.__voice = None
        self._watch_load(
            configured_voice, self._on_startup_voice_ready, self._on_startup_load_failed
        )

    def terminate(self):
        self._terminated = True
        self.cancel()
        if self.tts is not None:
            self.tts.shutdown()
        for player in self._players.values():
            player.close()
        self._players.clear()
        self._player = None
        self._active_players = set()
        self._pushed_length_scale = None

    def speak(self, speechSequence):
        if self.tts is None:
            log.error("speak() called with no TTS backend available; dropping speech.")
            return
        needed = self._voices_needed(speechSequence)
        if self._ready_to_speak(needed):
            self._speak_now(speechSequence)
            return
        self._deferred_speech = speechSequence
        self._watch_load(needed[0], self._on_voice_ready, self._on_load_failed)
        for voice in needed[1:]:
            self._watch_load(
                voice,
                self._flush_deferred,
                partial(self._on_deferred_load_failed, speechSequence),
                current_only=False,
            )

    def _voices_needed(self, speech_sequence):
        current = self.tts.speech_options.voice
        voices = [current]
        default_lang = self.tts.language
        for item in speech_sequence:
            if type(item) is not LangChangeCommand:
                continue
            lang = default_lang if item.isDefault else item.lang
            with suppress(VoiceNotFoundError):
                current = self.tts.voice_for_language(lang, current=current)
                voices.append(current)
        return voices

    def _ready_to_speak(self, voices):
        return (
            self._switch_origin is None
            and self._scaled_voice is voices[0]
            and all(voice.is_loaded for voice in voices)
        )

    def _flush_deferred(self):
        pending = self._deferred_speech
        if pending is None or not self._ready_to_speak(self._voices_needed(pending)):
            return
        self._deferred_speech = None
        self._speak_now(pending)

    def _speak_now(self, speech_sequence):
        with self.tts.create_synthesis_context():
            self._fast_prepare_and_run_speech_task(speech_sequence)

    def _watch_load(self, voice, on_ready, on_failed, current_only=True):
        def hand_off(future):
            try:
                wx.CallAfter(
                    self._finish_load, voice, future, on_ready, on_failed, current_only
                )
            except Exception:
                log.debug("Dropped a voice-load callback; wx is gone", exc_info=True)

        voice.begin_load().add_done_callback(hand_off)

    def _finish_load(self, voice, future, on_ready, on_failed, current_only=True):
        if self._terminated:
            return
        if current_only and self.tts.speech_options.voice is not voice:
            return
        error = future.exception()
        if error is None:
            on_ready()
        else:
            on_failed(error)

    def _on_voice_ready(self):
        voice = self.tts.speech_options.voice
        if self._scaled_voice is not voice:
            self._reapply_scale_settings()
        if self._current_speaker is None:
            self._current_speaker = voice.default_speaker
        self._flush_deferred()

    def _on_startup_voice_ready(self):
        self._forget_cached_choices()
        self._refresh_speech_gui()
        self._on_voice_ready()

    def _refresh_speech_gui(self):
        try:
            update_displaied_params_on_voice_change(self)
        except Exception:
            log.exception("Failed to update Speech GUI", exc_info=True)

    def _on_load_failed(self, error):
        dropped, self._deferred_speech = self._deferred_speech, None
        log.exception("Failed to load the current voice", exc_info=error)
        if dropped is not None:
            self._on_index_reached(None)

    def _on_deferred_load_failed(self, sequence, error):
        if self._deferred_speech is sequence:
            self._on_load_failed(error)
        else:
            log.error("Failed to load a language voice", exc_info=error)

    def _on_startup_load_failed(self, error):
        self._on_load_failed(error)
        # The constructor succeeded, so NVDA only learns of the failure from us.
        if getSynth() is self:
            findAndSetNextSynth(self.name)

    def _fast_prepare_and_run_speech_task(self, speech_sequence):
        self.cancel()
        self._current_task = process_speech(
            self._build_speech_tasks(speech_sequence)
        ).result()

    def _invalidate_pushed_length_scale(self):
        """Mark the cached backend `length_scale` dirty so the next task resynchronizes."""
        self._pushed_length_scale = None
        phrase_cache.clear()

    def _build_speech_tasks(self, speech_sequence):
        """Convert an NVDA speech sequence into executable speech and break tasks."""
        self._sync_rate_length_scale()
        speech_seq = []
        text_list = []
        index_command_list = []
        default_lang = self.tts.language
        default_raw_rate = self._raw_engine_rate
        capture_length_scale = any(
            type(item) in (RateCommand, LangChangeCommand) for item in speech_sequence
        )
        self._player = self._get_or_create_player(
            self.tts.speech_options.voice.sample_rate
        )
        players_used = {self._player}
        try:
            for item in speech_sequence:
                item_type = type(item)
                if item_type is IndexCommand:
                    index_command_list.append(item.index)
                    continue
                if item_type is str:
                    text_list.append(item)
                    continue

                if text_list:
                    speech_seq.extend(
                        self._create_speech_tasks(
                            text_list, capture_length_scale=capture_length_scale
                        )
                    )
                    text_list.clear()
                break_task = self._apply_speech_command(
                    item, default_lang, default_raw_rate
                )
                if break_task is not None:
                    speech_seq.append(break_task)
                players_used.add(self._player)
            if text_list:
                speech_seq.extend(
                    self._create_speech_tasks(
                        text_list, capture_length_scale=capture_length_scale
                    )
                )
        finally:
            if self._raw_engine_rate != default_raw_rate:
                self._restore_raw_engine_rate(default_raw_rate, push_scale=False)
        if index_command_list:
            speech_seq.append(
                IndexReachedTask(self._on_index_reached, index_command_list)
            )
        speech_seq.append(DoneSpeakingTask(players_used, self._on_index_reached))
        self._active_players = players_used
        return speech_seq

    def _task_length_scale(self, voice):
        """Return the current effective `length_scale` for `voice`, or None."""
        if not voice.is_loaded or not self._voice_supports_length_scale(voice):
            return None
        return self._effective_scale(
            voice,
            "length_scale",
            self._get_scale_factor("length_scale"),
            self._SCALE_SETTINGS["length_scale"],
        )

    def _create_speech_tasks(self, text_list, *, capture_length_scale=False):
        joined_text = "\n".join(text_list)
        do_norm = self._get_normalize_audio()
        do_spatial = self._get_spatial_audio()
        do_night = self._get_night_mode()
        do_struct = self._get_structural_reading()
        pan = _get_focus_pan() if do_spatial else 0.0

        voice = self.tts.speech_options.voice
        task_ls = self._task_length_scale(voice) if capture_length_scale else None
        on_restore_err = (
            self._invalidate_pushed_length_scale if task_ls is not None else None
        )
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
                        length_scale=task_ls,
                        on_scale_restore_error=on_restore_err,
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
                length_scale=task_ls,
                on_scale_restore_error=on_restore_err,
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

    def _apply_speech_command(self, item, default_lang, default_raw_rate=None):
        """Apply an inline NVDA speech command to the active synthesis context."""
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
            self._apply_rate_split(push_scale=False)
        elif item_type is RateCommand:
            if getattr(item, "isDefault", False):
                self._restore_raw_engine_rate(default_raw_rate, push_scale=False)
            else:
                self._raw_engine_rate = self._slider_to_raw_rate(item.newValue)
                self._apply_rate_split(push_scale=False)
        elif item_type is VolumeCommand:
            self.tts.volume = item.newValue
        elif item_type is PitchCommand:
            self.tts.pitch = item.newValue
        return None

    def cancel(self):
        self._deferred_speech = None
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

    def _get_sentence_pause(self):
        """Return the current sentence pause slider value (0-100)."""
        return self._sentence_pause

    def _set_sentence_pause(self, value):
        """Clamp and apply the sentence pause slider value (0-100)."""
        self._sentence_pause = max(0, min(100, int(value)))
        self._apply_sentence_pause()
        phrase_cache.clear()

    def _apply_sentence_pause(self):
        """Map the 0-100 slider to milliseconds on speech_options."""
        if self.tts is None:
            return
        pause = self._sentence_pause
        self.tts.speech_options.sentence_silence_ms = (
            int(self._percentToParam(pause, 0, _MAX_SENTENCE_PAUSE_MS))
            if pause > 0
            else None
        )

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

    def _voice_supports_length_scale(self, voice=None):
        """Return True when `voice`'s model profile exposes `length_scale`."""
        if voice is None:
            voice = getattr(getattr(self.tts, "speech_options", None), "voice", None)
        if voice is None or voice.model_type is None:
            return False
        return "length_scale" in profile_for(voice.model_type).tunable

    def _model_rate_speedup(self, voice=None):
        """Return the ideal model-side speed multiplier (1.0..1/floor) for the active rate."""
        if self._raw_engine_rate is None or not self._voice_supports_length_scale(
            voice
        ):
            return 1.0
        target_speed = _rate_to_speed(self._raw_engine_rate)
        if target_speed <= 1.0:
            return 1.0
        return min(target_speed, _MAX_MODEL_RATE_SPEEDUP)

    def _applied_model_rate_speedup(self, voice=None):
        """Return the actual model speedup applied to `voice` after rounding and clamping."""
        if voice is None:
            voice = getattr(getattr(self.tts, "speech_options", None), "voice", None)
        ideal_speedup = self._model_rate_speedup(voice)
        if ideal_speedup <= 1.0:
            return 1.0
        if voice is None or not voice.is_loaded:
            return ideal_speedup
        value = self._get_scale_factor("length_scale")
        spec = self._SCALE_SETTINGS["length_scale"]
        base_scale = self._unsplit_scale(voice, "length_scale", value, spec)
        effective_scale = self._effective_scale(voice, "length_scale", value, spec)
        if effective_scale <= 0 or base_scale <= effective_scale:
            return 1.0
        return base_scale / effective_scale

    def _slider_to_raw_rate(self, value):
        """Convert an NVDA 0-100 rate value into a raw engine rate step."""
        return value if self._rateBoost else int(self._percentToParam(value, 0, 40))

    def _is_pushed_length_scale(self, voice, effective):
        pushed = self._pushed_length_scale
        return (
            pushed is not None
            and pushed[0] is voice
            and pushed[1] is voice.default_scales
            and pushed[2] == effective
        )

    def _sync_rate_length_scale(self):
        """Push effective `length_scale` only when it differs from the last pushed value."""
        voice = self.tts.speech_options.voice
        if not voice.is_loaded or not self._voice_supports_length_scale(voice):
            return
        value = self._get_scale_factor("length_scale")
        effective = self._effective_scale(
            voice, "length_scale", value, self._SCALE_SETTINGS["length_scale"]
        )
        if self._is_pushed_length_scale(voice, effective):
            return
        self._set_scale_factor("length_scale", value, force=True)

    def _restore_raw_engine_rate(self, raw_rate, push_scale=True):
        """Restore `_raw_engine_rate` and resync Sonic rate and `length_scale`."""
        self._raw_engine_rate = raw_rate
        if self.tts is None:
            return
        if raw_rate is None:
            self.tts.speech_options.rate = None
            if push_scale:
                self._sync_rate_length_scale()
            return
        self._apply_rate_split(push_scale=push_scale)

    def _apply_rate_split(self, push_scale=True):
        """Split `_raw_engine_rate` between `voice.length_scale` and Sonic `tts.rate`."""
        if self._raw_engine_rate is None or self.tts is None:
            return
        speedup = self._applied_model_rate_speedup()
        if speedup <= 1.0:
            self.tts.rate = self._raw_engine_rate
        else:
            target_speed = _rate_to_speed(self._raw_engine_rate)
            self.tts.rate = _speed_to_rate(target_speed / speedup)
        if push_scale:
            self._sync_rate_length_scale()

    def _get_rate(self):
        """Return the user-facing NVDA rate percentage (0-100)."""
        raw = (
            self._raw_engine_rate
            if self._raw_engine_rate is not None
            else self.tts.rate
        )
        if self._rateBoost:
            return raw
        raw = min(40, raw)
        return int(raw * 2.5)

    def _set_rate(self, value):
        """Store the raw engine rate for `value` and apply the model/Sonic split."""
        self._raw_engine_rate = self._slider_to_raw_rate(value)
        self._apply_rate_split()

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
        setattr(self, factor_attr, value)
        if name == "length_scale":
            self._apply_rate_split(push_scale=False)
        voice = self.tts.speech_options.voice
        if voice.is_loaded:
            try:
                self._push_scale(voice, name, value, spec)
            except BackendError:
                if name == "length_scale":
                    self._pushed_length_scale = None
                log.exception(
                    f"Could not apply {name}: the speech engine is unreachable"
                )
        phrase_cache.clear()

    def _unsplit_scale(self, voice, name, value, spec):
        """Compute the scale value for slider `value` without rate speedup."""
        default = getattr(voice.default_scales, name)
        if value == 50:
            return default
        base = self._percentToParam(value, 0.0, default * spec["multiplier"])
        return max(0.1, round(base, 2))

    def _effective_scale(self, voice, name, value, spec):
        """Compute the scale value to push to `voice` for slider `value`."""
        default = getattr(voice.default_scales, name)
        speedup = self._model_rate_speedup(voice) if name == "length_scale" else 1.0
        if value == 50 and speedup <= 1.0:
            return default
        base = (
            default
            if value == 50
            else self._percentToParam(value, 0.0, default * spec["multiplier"])
        )
        if speedup > 1.0:
            base /= speedup
        return max(0.1, round(base, 2))

    def _push_scale(self, voice, name, value, spec):
        """Push the effective scale setting to `voice`."""
        effective = self._effective_scale(voice, name, value, spec)
        if name != "length_scale":
            setattr(voice, name, effective)
            return
        state = _get_voice_scale_state(voice)
        with state.io_lock:
            state.version += 1
            state.persistent_length_scale = effective
            if not state.active_override:
                setattr(voice, name, effective)
            self._pushed_length_scale = (
                voice,
                voice.default_scales,
                effective,
            )

    def _reapply_scale_settings(self):
        """Reapply rate split and model scale sliders after a voice finishes loading."""
        self._apply_rate_split(push_scale=False)
        for name in self._SCALE_SETTINGS:
            self._set_scale_factor(name, self._get_scale_factor(name), force=True)
        voice = self.tts.speech_options.voice
        if voice.is_loaded:
            self._scaled_voice = voice

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
            self._begin_switch(value, self._target_voice_key(value))
        except VoiceNotFoundError:
            log.exception(f"Failed to load voice `{value}`")
            self._announce_switch_failure(value)

    def _begin_switch(self, value, voice_key):
        origin = self._switch_origin or (self.tts.voice, self.__voice)
        self.tts.voice = voice_key
        self._switch_origin = origin
        self.__voice = value
        self._forget_cached_choices()
        self._watch_load(
            self.tts.speech_options.voice,
            partial(self._finish_switch, value),
            partial(self._revert_switch, value, origin),
        )

    def _target_voice_key(self, value):
        standard = self._standard_voice_map[value]
        variant = (
            DengjenConfig[value].get("variant", "standard")
            if value in DengjenConfig
            else "standard"
        )
        if variant.lower() == "fast" and standard.fast_variant_key in self._voice_map:
            return standard.fast_variant_key
        return standard.key

    def _forget_cached_choices(self):
        for attr in ("_availableVariants", "_availableSpeakers"):
            with suppress(AttributeError):
                delattr(self, attr)

    def _announce_switch_failure(self, value):
        ui.message(
            _("Failed to load voice {voice}. Keeping the previous voice.").format(
                voice=self.availableVoices[value].displayName
            )
        )

    def _finish_switch(self, value):
        self._switch_origin = None
        self._forget_cached_choices()
        phrase_cache.clear()
        if value in DengjenConfig:
            variant = DengjenConfig[value].get("variant", self.variant)
        else:
            variant = self._standard_voice_map[value].variant
        self._set_variant(variant)
        self._apply_voice_speaker(value)
        self._refresh_speech_gui()
        self._on_voice_ready()

    def _apply_voice_speaker(self, value):
        speaker = (
            DengjenConfig[value].get("speaker") if value in DengjenConfig else None
        )
        if speaker is not None:
            self._set_speaker(speaker)
        else:
            self._current_speaker = self.tts.speech_options.voice.default_speaker

    def _revert_switch(self, value, previous, error):
        previous_key, previous_value = previous
        self._switch_origin = None
        log.exception(f"Failed to load voice `{value}`", exc_info=error)
        with suppress(VoiceNotFoundError):
            self.tts.voice = previous_key
        self.__voice = previous_value or self._get_voice()
        self._forget_cached_choices()
        if previous_value is not None:
            self._announce_switch_failure(value)
        self._watch_load(
            self.tts.speech_options.voice, self._on_voice_ready, self._on_load_failed
        )

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
        DengjenConfig.setdefault(self.voice, {})["variant"] = value
        if voice_key == self.tts.voice:
            self._reapply_scale_settings()
            return
        self._begin_switch(self._get_voice(), voice_key)

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
        if not self.tts.speech_options.voice.is_loaded:
            return None
        spk = self.tts.speaker
        self._current_speaker = spk
        return spk

    def _set_speaker(self, value):
        if not self.tts.speech_options.voice.is_loaded:
            self._current_speaker = value
            DengjenConfig.setdefault(self.voice, {})["speaker"] = value
            return
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
        if not self.tts.speech_options.voice.is_loaded:
            return {}
        return {spk: VoiceInfo(spk, spk, None) for spk in self.tts.get_speakers()}
