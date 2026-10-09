"""
Tests for the SynthDriver (addon/synthDrivers/dengjen_neural_voices/adapters/nvda/synth_driver.py):
construction, speech sequence handling, flush/cancel ordering, the settings
NVDA reads and writes through driver properties, and background voice loading
and switching.

Executes the real synth_driver.py under the stubs conftest.py installs, against
a fake on-disk voice and a fake backend. A voice that exists on disk but fails
to load (issue #69) must leave the previously active voice current and make
NVDA report a message instead of an error chime.
"""

import asyncio
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import config
import pytest
import ui
from dengjen_neural_voices._config import DengjenConfig
from dengjen_neural_voices.const import FALLBACK_SPEAKER_NAME
from dengjen_neural_voices.domain import tts_system
from dengjen_neural_voices.ports.tts_backend import (
    LoadedVoice,
    SynthOptions,
    VoiceLoadError,
)
from logHandler import log
from speech.commands import BreakCommand, IndexCommand, LangChangeCommand

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path
from tests.fake_tts_backend import FakeTTSBackend

driver_module = load_module_from_path(
    "dengjen_neural_voices.adapters.nvda.synth_driver",
    os.path.join(SYNTH_PKG_DIR, "adapters", "nvda", "synth_driver.py"),
    package="dengjen_neural_voices.adapters.nvda",
)

SynthDriver = driver_module.SynthDriver
SpeechTask = driver_module.SpeechTask
BreakTask = driver_module.BreakTask
IndexReachedTask = driver_module.IndexReachedTask
DoneSpeakingTask = driver_module.DoneSpeakingTask

VOICE_KEY = "en_US-test-medium"
SECTION = "dengjen_neural_voices"


def _index_command(index):
    cmd = IndexCommand()
    cmd.index = index
    return cmd


def _break_command(time_ms):
    cmd = BreakCommand()
    cmd.time = time_ms
    return cmd


def _lang_change_command(lang, is_default=False):
    cmd = LangChangeCommand()
    cmd.lang = lang
    cmd.isDefault = is_default
    return cmd


def _write_voice(voices_dir, key=VOICE_KEY):
    voice_dir = voices_dir / key
    voice_dir.mkdir(parents=True)
    (voice_dir / "config.json").write_text("{}", encoding="utf-8")
    return voice_dir


@pytest.fixture
def voices_dir(tmp_path, monkeypatch):
    """One fake voice on disk, wired in place of the real NVDA config dir."""
    monkeypatch.setattr(tts_system, "DENGJEN_VOICES_DIR", str(tmp_path))
    _write_voice(tmp_path)
    return tmp_path


@pytest.fixture
def configured_voice(voices_dir):
    """Point config at the on-disk voice, like a real NVDA profile would."""
    config.conf["speech"][SECTION].clear()
    config.conf["speech"][SECTION]["voice"] = VOICE_KEY
    return voices_dir


@pytest.fixture
def fake_backend(monkeypatch):
    backend = FakeTTSBackend()
    monkeypatch.setattr(driver_module, "_bootstrap_backend", lambda: backend)
    return backend


class GatedBackend(FakeTTSBackend):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def load_voice(self, config_path):
        assert self.release.wait(timeout=5), "load was never released"
        return super().load_voice(config_path)


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met in time")


def wait_ready(driver):
    voice = driver.tts.speech_options.voice
    wait_until(lambda: driver._scaled_voice is voice)


@pytest.fixture
def driver(configured_voice, fake_backend):
    d = SynthDriver()
    wait_ready(d)
    yield d
    d.terminate()


def _first_player(driver):
    """Players are created on first speech, so create the current voice's now."""
    driver._build_speech_tasks(["hi"])
    return driver._player


class TestConstruction:
    def test_loads_the_voice_on_disk(self, driver):
        assert [v.key for v in driver.voices] == [VOICE_KEY]

    def test_selects_the_configured_voice(self, driver):
        assert driver.tts.voice == VOICE_KEY

    def test_falls_back_to_first_voice_when_configured_voice_is_unknown(
        self, voices_dir, fake_backend
    ):
        config.conf["speech"][SECTION].clear()
        config.conf["speech"][SECTION]["voice"] = "does-not-exist"
        d = SynthDriver()
        try:
            assert d.tts.voice == VOICE_KEY
        finally:
            d.terminate()

    def test_available_voices_use_dash_separated_language_in_the_display_name(
        self, driver
    ):

        import languageHandler

        voice_id, display_name, lang = driver.availableVoices[VOICE_KEY]
        assert voice_id == VOICE_KEY
        expected_lang = languageHandler.normalizeLanguage(lang).replace("_", "-")
        assert f"({expected_lang})" in display_name

    def test_loads_voices_from_disk_only_once(
        self, configured_voice, fake_backend, monkeypatch
    ):
        """A previous version called load_all_voices_from_nvda_config_dir()
        twice back to back in __init__ for no reason."""
        real_load = driver_module.DengjenTextToSpeechSystem.load_all_voices_from_nvda_config_dir.__func__
        calls = []

        def counting_load(cls, backend):
            calls.append(1)
            return real_load(cls, backend)

        monkeypatch.setattr(
            driver_module.DengjenTextToSpeechSystem,
            "load_all_voices_from_nvda_config_dir",
            classmethod(counting_load),
        )
        d = SynthDriver()
        try:
            assert len(calls) == 1
        finally:
            d.terminate()

    def test_loads_without_an_audio_device(
        self, configured_voice, fake_backend, monkeypatch
    ):
        def no_device(_sample_rate):
            raise OSError("Couldn't open specified or default audio device")

        monkeypatch.setattr(driver_module, "create_wave_player", no_device)
        d = SynthDriver()
        try:
            assert d.tts is not None
            d.variant = d.variant
            d.spatial_audio = True
        finally:
            d.terminate()

    def test_backend_unavailable_leaves_the_driver_without_voices(
        self, configured_voice, monkeypatch
    ):
        """A BackendUnavailableError from bootstrap must not raise out of
        __init__ -- the driver stays constructed but non-functional, same as
        today's broad except-Exception behavior, so NVDA can still report the
        synth as failed rather than crash."""
        from dengjen_neural_voices.ports.tts_backend import BackendUnavailableError

        def _boom():
            raise BackendUnavailableError("no vcruntime")

        monkeypatch.setattr(driver_module, "_bootstrap_backend", _boom)
        d = SynthDriver()
        try:
            assert d.tts is None
        finally:
            d.terminate()

    def test_loads_saved_settings_without_crash(
        self, monkeypatch, configured_voice, fake_backend
    ):
        """Simulate NVDA loadSettings calling setters when loading saved settings."""
        import synthDriverHandler

        orig_init = synthDriverHandler.SynthDriver.__init__

        def _init_with_load_settings(synth_self):
            orig_init(synth_self)
            # In NVDA, AutoPropertyObject.__init__ calls loadSettings(), which sets
            # supported settings from config before Dengjen's own __init__ body runs.
            synth_self._set_spatial_audio(True)
            synth_self._set_night_mode(True)

        monkeypatch.setattr(
            synthDriverHandler.SynthDriver, "__init__", _init_with_load_settings
        )

        d = SynthDriver()
        try:
            assert d.spatial_audio is True
            assert d.night_mode is True
            assert d.tts is not None
        finally:
            d.terminate()

    def test_set_spatial_audio_before_init_does_not_raise(self):
        """Calling _set_spatial_audio on an uninitialized instance must not raise."""
        d = SynthDriver.__new__(SynthDriver)
        d._set_spatial_audio(True)
        assert d.spatial_audio is True


class TestSpeechTask:
    def test_feeds_every_chunk_then_waits_for_the_player_to_drain(self, monkeypatch):
        calls = []

        async def run_inline(fn, *args):
            return fn(*args)

        class _Player:
            def feed(self, chunk):
                calls.append(("feed", chunk))

            def sync(self):
                calls.append(("sync",))

        async def _audio():
            yield b"one"
            yield b"two"

        monkeypatch.setattr(driver_module, "run_in_executor", run_inline)
        options = SimpleNamespace(
            voice=SimpleNamespace(key="voice", speaker=None),
            rate=50,
            volume=100,
            pitch=50,
        )
        task = SimpleNamespace(text="hi", speech_options=options, generate_audio=_audio)
        driver_module.phrase_cache.clear()

        asyncio.run(SpeechTask(task, _Player())())

        assert calls == [("feed", b"one"), ("feed", b"two"), ("sync",)]


class TestBuildSpeechTasks:
    """`_build_speech_tasks` is where flush/cancel ordering bugs have
    historically shipped: pending text must be flushed into its own task
    before a command takes effect, and index callbacks must fire after
    every task that precedes them, never before."""

    def test_plain_text_becomes_a_single_speech_task_then_done(self, driver):
        tasks = driver._build_speech_tasks(["hello world"])
        assert [type(t) for t in tasks] == [SpeechTask, DoneSpeakingTask]

    def test_index_commands_alone_produce_no_speech_task(self, driver):
        tasks = driver._build_speech_tasks([_index_command(5)])
        assert [type(t) for t in tasks] == [IndexReachedTask, DoneSpeakingTask]
        assert tasks[0].index_list == [5]

    def test_flush_order_around_a_break_and_index_commands(self, driver):
        seq = [
            _index_command(1),
            "hello ",
            "world",
            _break_command(100),
            _index_command(2),
            "after break",
        ]
        tasks = driver._build_speech_tasks(seq)
        assert [type(t) for t in tasks] == [
            SpeechTask,
            BreakTask,
            SpeechTask,
            IndexReachedTask,
            DoneSpeakingTask,
        ]
        assert tasks[3].index_list == [1, 2]

    def test_command_flushes_pending_text_into_separate_tasks(self, driver):

        seq = [
            "hello ",
            "world",
            _lang_change_command("en_US", is_default=True),
            "more",
        ]
        tasks = driver._build_speech_tasks(seq)
        assert [type(t) for t in tasks] == [SpeechTask, SpeechTask, DoneSpeakingTask]

    def test_a_lone_empty_string_still_produces_a_speech_task(self, driver):
        """any(text_list) is False for [""] -- an empty string is a
        legitimate collected value, not "no text", and must still flush
        into a SpeechTask."""
        tasks = driver._build_speech_tasks([""])
        assert [type(t) for t in tasks] == [SpeechTask, DoneSpeakingTask]

    def test_a_lone_index_zero_still_produces_an_index_reached_task(self, driver):
        """any(index_command_list) is False for [0] -- index 0 is a
        legitimate index value, not "no index commands"."""
        tasks = driver._build_speech_tasks([_index_command(0)])
        assert [type(t) for t in tasks] == [IndexReachedTask, DoneSpeakingTask]
        assert tasks[0].index_list == [0]

    def test_a_mid_sequence_lang_change_switches_to_the_new_voices_player(
        self, configured_voice, fake_backend
    ):
        """A voice switched to mid-sequence (e.g. NVDA's language
        auto-detection) can have a different sample rate -- Kokoro's fixed
        24000Hz differs from Piper's common rates, so this regresses easily
        once both are installed. Each task must carry its own voice's
        player, and DoneSpeakingTask must wait on every player used."""
        second_voice_dir = _write_voice(configured_voice, key="fr_FR-test-medium")
        second_config_path = str(next(second_voice_dir.glob("*.json")))
        fake_backend.voices_by_config_path[second_config_path] = LoadedVoice(
            backend_voice_id="fake-remote-id-fr",
            supports_streaming_output=False,
            sample_rate=24000,
            speakers={},
            defaults=SynthOptions(
                speaker=None, length_scale=1.0, noise_scale=0.667, noise_w=0.8
            ),
        )
        driver = SynthDriver()
        try:
            first_player = _first_player(driver)
            seq = ["hello", _lang_change_command("fr_FR"), "bonjour"]

            tasks = driver._build_speech_tasks(seq)

            speech_tasks = [t for t in tasks if isinstance(t, SpeechTask)]
            assert len(speech_tasks) == 2
            assert speech_tasks[0].player is first_player
            second_player = driver._players[24000]
            assert speech_tasks[1].player is second_player
            assert second_player is not first_player
            done_task = tasks[-1]
            assert isinstance(done_task, DoneSpeakingTask)
            assert set(done_task.players) == {first_player, second_player}
        finally:
            driver.terminate()

    def test_a_later_call_resyncs_the_player_after_a_restored_synthesis_context(
        self, configured_voice, fake_backend
    ):
        """create_synthesis_context() restores tts.speech_options (and thus
        .voice) once a speak() call exits, but nothing previously resynced
        self._player to match -- a later speak() call with no
        LangChangeCommand of its own kept using whichever player a prior
        mid-sequence switch left behind: a sample-rate mismatch produces
        audible distortion, not an exception."""
        second_voice_dir = _write_voice(configured_voice, key="fr_FR-test-medium")
        second_config_path = str(next(second_voice_dir.glob("*.json")))
        fake_backend.voices_by_config_path[second_config_path] = LoadedVoice(
            backend_voice_id="fake-remote-id-fr",
            supports_streaming_output=False,
            sample_rate=24000,
            speakers={},
            defaults=SynthOptions(
                speaker=None, length_scale=1.0, noise_scale=0.667, noise_w=0.8
            ),
        )
        driver = SynthDriver()
        try:
            first_player = _first_player(driver)

            with driver.tts.create_synthesis_context():
                driver._build_speech_tasks(
                    ["hello", _lang_change_command("fr_FR"), "bonjour"]
                )
            assert driver.tts.speech_options.voice.key == VOICE_KEY

            tasks = driver._build_speech_tasks(["hi again"])

            speech_task = next(t for t in tasks if isinstance(t, SpeechTask))
            assert speech_task.player is first_player
        finally:
            driver.terminate()

    def test_a_voice_switch_drops_the_previous_voices_cached_speaker(
        self, configured_voice, fake_backend
    ):
        second_voice_dir = _write_voice(configured_voice, key="fr_FR-test-medium")
        second_config_path = str(next(second_voice_dir.glob("*.json")))
        fake_backend.voices_by_config_path[second_config_path] = LoadedVoice(
            backend_voice_id="fake-remote-id-fr",
            supports_streaming_output=False,
            sample_rate=24000,
            speakers={},
            defaults=SynthOptions(
                speaker=None, length_scale=1.0, noise_scale=0.667, noise_w=0.8
            ),
        )
        driver = SynthDriver()
        try:
            driver._current_speaker = "english-speaker"

            with driver.tts.create_synthesis_context():
                tasks = driver._build_speech_tasks(
                    ["hello", _lang_change_command("fr_FR"), "bonjour"]
                )

            speakers = [t.speaker for t in tasks if isinstance(t, SpeechTask)]
            assert speakers[0] == "english-speaker"
            assert speakers[1] != "english-speaker"
            assert driver._current_speaker is None
        finally:
            driver.terminate()

    def test_structural_reading_uses_cached_speaker(self, driver):
        driver.structural_reading = True
        voice = driver.tts.speech_options.voice
        voice.is_multi_speaker = True
        voice.speaker_names = ["spk1", "spk2"]
        driver.speaker = "spk1"

        # Even if remote voice.speaker would raise, task building uses cached speaker
        # Set voice as having the property on its type or instance
        voice.__class__ = type(
            "MultiSpeakerVoice",
            (voice.__class__,),
            {
                "speaker": property(
                    lambda self: (_ for _ in ()).throw(RuntimeError("timeout"))
                )
            },
        )

        tasks = driver._build_speech_tasks(["hello (aside) world"])
        speech_tasks = [t for t in tasks if isinstance(t, SpeechTask)]
        assert len(speech_tasks) == 3
        assert speech_tasks[1].speaker == "spk2"

    def test_non_structural_reading_uses_cached_speaker(self, driver):
        driver.structural_reading = False
        voice = driver.tts.speech_options.voice
        driver.speaker = "spk1"

        voice.__class__ = type(
            "ExplodingVoice",
            (voice.__class__,),
            {
                "speaker": property(
                    lambda self: (_ for _ in ()).throw(RuntimeError("timeout"))
                )
            },
        )

        tasks = driver._build_speech_tasks(["hello world"])
        speech_tasks = [t for t in tasks if isinstance(t, SpeechTask)]
        assert len(speech_tasks) == 1
        assert speech_tasks[0].speaker == "spk1"


class TestPlayerCreation:
    @pytest.fixture
    def stereo_failing(self, monkeypatch):
        real = driver_module.create_wave_player

        def install(error):
            def create(sample_rate, channels=1):
                if channels != 1:
                    raise error
                return real(sample_rate)

            monkeypatch.setattr(driver_module, "create_wave_player", create)

        return install

    @pytest.mark.parametrize("error", [TypeError("no channels"), OSError("bad format")])
    def test_a_stereo_failure_falls_back_to_a_mono_player(
        self, driver, stereo_failing, error
    ):
        stereo_failing(error)
        driver.spatial_audio = True

        player = driver._get_or_create_player(22050)

        assert driver.spatial_audio is False
        assert driver._players[22050] is player

    def test_a_stereo_failure_reuses_the_existing_mono_player(
        self, driver, stereo_failing
    ):
        driver.spatial_audio = False
        mono = driver._get_or_create_player(22050)
        stereo_failing(OSError("bad format"))
        driver.spatial_audio = True

        assert driver._get_or_create_player(22050) is mono
        assert list(driver._players.values()) == [mono]

    def test_a_mono_failure_is_not_swallowed(self, driver, monkeypatch):
        def create(sample_rate, channels=1):
            raise OSError("no device")

        monkeypatch.setattr(driver_module, "create_wave_player", create)

        with pytest.raises(OSError):
            driver._get_or_create_player(22050)


class TestLifecycle:
    def test_speak_with_no_backend_does_not_raise(self, configured_voice, monkeypatch):
        """__init__ leaves self.tts as None when the backend fails to start
        (test_backend_unavailable_leaves_the_driver_without_voices above),
        but check() always returns True, so NVDA can still select this
        driver and call speak() on it -- it must not crash with an
        AttributeError on self.tts.create_synthesis_context()."""
        from dengjen_neural_voices.ports.tts_backend import BackendUnavailableError

        def _boom():
            raise BackendUnavailableError("no vcruntime")

        monkeypatch.setattr(driver_module, "_bootstrap_backend", _boom)
        d = SynthDriver()
        assert d.tts is None
        try:
            d.speak(["hello"])
        finally:
            d.terminate()

    def test_cancel_stops_the_player(self, driver):
        _first_player(driver)
        driver._player.stop = MagicMock()
        driver.cancel()
        driver._player.stop.assert_called_once()

    def test_cancel_with_no_current_task_does_not_cancel_anything(
        self, driver, monkeypatch
    ):
        cancel_mock = MagicMock()
        monkeypatch.setattr(driver_module, "asyncio_cancel_task", cancel_mock)
        driver.cancel()
        cancel_mock.assert_not_called()

    def test_cancel_cancels_the_current_task(self, driver, monkeypatch):
        cancel_mock = MagicMock()
        monkeypatch.setattr(driver_module, "asyncio_cancel_task", cancel_mock)
        driver._current_task = object()
        driver.cancel()
        cancel_mock.assert_called_once_with(driver._current_task)

    def test_pause_delegates_to_the_player(self, driver):
        _first_player(driver)
        driver._player.pause = MagicMock()
        driver.pause(True)
        driver._player.pause.assert_called_once_with(True)

    def test_cancel_stops_every_player_from_a_mid_sequence_lang_change(
        self, configured_voice, fake_backend
    ):
        """cancel() must stop every player a just-built sequence might still
        be using, not just self._player -- _build_speech_tasks can leave
        self._player pointing at a later voice than whichever task is
        actually mid-playback when cancel() fires."""
        second_voice_dir = _write_voice(configured_voice, key="fr_FR-test-medium")
        second_config_path = str(next(second_voice_dir.glob("*.json")))
        fake_backend.voices_by_config_path[second_config_path] = LoadedVoice(
            backend_voice_id="fake-remote-id-fr",
            supports_streaming_output=False,
            sample_rate=24000,
            speakers={},
            defaults=SynthOptions(
                speaker=None, length_scale=1.0, noise_scale=0.667, noise_w=0.8
            ),
        )
        driver = SynthDriver()
        try:
            first_player = _first_player(driver)
            driver._build_speech_tasks(
                ["hello", _lang_change_command("fr_FR"), "bonjour"]
            )
            second_player = driver._players[24000]
            first_player.stop = MagicMock()
            second_player.stop = MagicMock()

            driver.cancel()

            first_player.stop.assert_called_once()
            second_player.stop.assert_called_once()
        finally:
            driver.terminate()

    def test_pause_pauses_every_player_from_a_mid_sequence_lang_change(
        self, configured_voice, fake_backend
    ):
        second_voice_dir = _write_voice(configured_voice, key="fr_FR-test-medium")
        second_config_path = str(next(second_voice_dir.glob("*.json")))
        fake_backend.voices_by_config_path[second_config_path] = LoadedVoice(
            backend_voice_id="fake-remote-id-fr",
            supports_streaming_output=False,
            sample_rate=24000,
            speakers={},
            defaults=SynthOptions(
                speaker=None, length_scale=1.0, noise_scale=0.667, noise_w=0.8
            ),
        )
        driver = SynthDriver()
        try:
            first_player = _first_player(driver)
            driver._build_speech_tasks(
                ["hello", _lang_change_command("fr_FR"), "bonjour"]
            )
            second_player = driver._players[24000]
            first_player.pause = MagicMock()
            second_player.pause = MagicMock()

            driver.pause(True)

            first_player.pause.assert_called_once_with(True)
            second_player.pause.assert_called_once_with(True)
        finally:
            driver.terminate()

    def test_terminate_closes_every_player_and_clears_them(self, driver):
        extra_player = MagicMock()
        driver._players["extra"] = extra_player
        real_player = _first_player(driver)
        real_player.close = MagicMock()
        driver.terminate()
        real_player.close.assert_called_once()
        extra_player.close.assert_called_once()
        assert driver._players == {}


class TestProcessSpeechSequence:
    """_process_speech_sequence's own per-task error/cancellation handling
    (addon/synthDrivers/dengjen_neural_voices/adapters/nvda/synth_driver.py)."""

    def test_runs_every_task_in_order_one_at_a_time(self):
        ran = []
        active = 0
        max_active = 0

        def make_task(n):
            async def task():
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0)
                ran.append(n)
                active -= 1

            return task

        asyncio.run(
            driver_module._process_speech_sequence([make_task(i) for i in range(3)])
        )
        assert ran == [0, 1, 2]

        assert max_active == 1

    def test_stops_and_debug_logs_on_cancellation(self, monkeypatch):
        ran = []

        async def cancels():
            raise asyncio.CancelledError()

        async def never_runs():
            ran.append("should not run")

        debug_mock = MagicMock()
        monkeypatch.setattr(driver_module.log, "debug", debug_mock)

        asyncio.run(driver_module._process_speech_sequence([cancels, never_runs]))

        assert ran == []
        debug_mock.assert_called_once()
        assert "Canceled" in debug_mock.call_args.args[0]

    def test_stops_and_exception_logs_on_a_task_error(self, monkeypatch):
        ran = []

        async def blows_up():
            raise ValueError("boom")

        async def never_runs():
            ran.append("should not run")

        exception_mock = MagicMock()
        monkeypatch.setattr(driver_module.log, "exception", exception_mock)
        # nvda_stubs aliases CancelledError to the builtin Exception (so a plain
        # raise can stand in for a real cancellation); narrow it back to the real
        # type here so a ValueError can reach the generic-exception branch under test.
        monkeypatch.setattr(driver_module, "CancelledError", asyncio.CancelledError)

        asyncio.run(driver_module._process_speech_sequence([blows_up, never_runs]))

        assert ran == []
        exception_mock.assert_called_once()

    def test_a_task_error_still_runs_the_index_and_done_notifications(
        self, monkeypatch
    ):
        ran = []

        async def blows_up():
            raise ValueError("boom")

        class _Index:
            async def __call__(self):
                ran.append("index")

        class _Done:
            async def __call__(self):
                ran.append("done")

        monkeypatch.setattr(driver_module, "IndexReachedTask", _Index)
        monkeypatch.setattr(driver_module, "DoneSpeakingTask", _Done)
        monkeypatch.setattr(driver_module.log, "exception", MagicMock())
        monkeypatch.setattr(driver_module, "CancelledError", asyncio.CancelledError)

        asyncio.run(
            driver_module._process_speech_sequence([blows_up, _Index(), _Done()])
        )

        assert ran == ["index", "done"]


class TestSettings:
    """These only work because conftest's _AutoPropertyMeta wires _get_x/
    _set_x pairs into a real `x` property, matching what NVDA's
    AutoPropertyObject does for the driver at runtime."""

    def test_rate_round_trips_through_percent_param(self, driver):
        driver.rate = 0
        assert driver.rate == 0
        driver.rate = 100
        assert driver.rate == 100

    def test_volume_updates_the_player_gain(self, driver):
        _first_player(driver)
        driver._player.setVolume = MagicMock()
        driver.volume = 42
        assert driver.volume == 42
        driver._player.setVolume.assert_called_once_with(all=0.42)

    def test_a_player_created_after_a_volume_change_gets_that_volume(
        self, driver, monkeypatch
    ):
        driver.volume = 42
        created = MagicMock()
        monkeypatch.setattr(driver_module, "create_wave_player", lambda _rate: created)
        driver._get_or_create_player(12345)
        created.setVolume.assert_called_once_with(all=0.42)

    def test_pitch_round_trips(self, driver):
        driver.pitch = 60
        assert driver.pitch == 60

    def test_speaker_defaults_to_fallback_for_a_single_speaker_voice(self, driver):
        assert driver.speaker == FALLBACK_SPEAKER_NAME

    def test_noise_scale_defaults_to_fifty(self, driver):
        assert driver.noise_scale == 50

    def test_noise_scale_round_trips_through_the_engine(self, driver):
        driver.noise_scale = 75
        assert driver.noise_scale == 75

    def test_noise_scale_reapplies_an_unchanged_value(self, driver, fake_backend):
        driver.noise_scale = 75
        fake_backend.set_synth_options_calls.clear()
        driver.noise_scale = 75
        assert len(fake_backend.set_synth_options_calls) == 1

    def test_length_scale_defaults_to_fifty(self, driver):
        assert driver.length_scale == 50

    def test_length_scale_round_trips_through_the_engine(self, driver):
        driver.length_scale = 75
        assert driver.length_scale == 75

    def test_length_scale_reapplies_an_unchanged_value(self, driver, fake_backend):
        driver.length_scale = 75
        fake_backend.set_synth_options_calls.clear()
        driver.length_scale = 75
        assert len(fake_backend.set_synth_options_calls) == 1

    def test_noise_w_defaults_to_fifty(self, driver):
        assert driver.noise_w == 50

    def test_noise_w_round_trips_through_the_engine(self, driver):
        driver.noise_w = 75
        assert driver.noise_w == 75

    def test_noise_w_skips_reapplying_an_unchanged_value(self, driver, fake_backend):

        driver.noise_w = 75
        fake_backend.set_synth_options_calls.clear()
        driver.noise_w = 75
        assert fake_backend.set_synth_options_calls == []

    def test_switching_variant_reapplies_scale_settings(self, driver, fake_backend):

        driver.noise_scale = 75
        fake_backend.set_synth_options_calls.clear()
        driver.variant = driver.variant
        calls = [kwargs for _, kwargs in fake_backend.set_synth_options_calls]
        assert any("noise_scale" in kwargs for kwargs in calls)

    def test_switching_variant_reapplies_noise_w_even_when_the_cached_value_is_unchanged(
        self, driver, fake_backend
    ):

        driver.noise_w = 75
        fake_backend.set_synth_options_calls.clear()
        driver.variant = driver.variant
        calls = [kwargs for _, kwargs in fake_backend.set_synth_options_calls]
        assert any("noise_w" in kwargs for kwargs in calls)


class _FakeVoiceInfo:
    """Stand-in for synthDriverHandler.VoiceInfo -- only .displayName is used."""

    def __init__(self, display_name):
        self.displayName = display_name


@pytest.fixture(autouse=True)
def _reset_mocks():
    ui.message.reset_mock()
    log.exception.reset_mock()
    yield


class TestEngineLostMidSession:
    """Setters swallow BackendError and log it instead of raising, so NVDA's
    loadSettings() cannot fail when the engine is gone."""

    @pytest.fixture
    def dead_engine(self, driver, fake_backend):
        fake_backend.raise_on_set_synth_options(VoiceLoadError("engine gone"))
        return driver

    def test_reapplying_the_voice_does_not_raise(self, dead_engine):
        dead_engine.voice = dead_engine.voice

    def test_switching_variant_does_not_raise(self, dead_engine):
        dead_engine.variant = dead_engine.variant

    @pytest.mark.parametrize("name", ["noise_scale", "length_scale", "noise_w"])
    def test_moving_a_scale_slider_does_not_raise(self, dead_engine, name):
        setattr(dead_engine, name, 60)

    def test_setting_the_speaker_does_not_raise(self, driver, monkeypatch):
        def fail(_self, _value):
            raise VoiceLoadError("engine gone")

        monkeypatch.setattr(
            type(driver.tts), "speaker", property(lambda _self: "x", fail)
        )
        driver.speaker = "anyone"
        assert DengjenConfig[driver.voice]["speaker"] == "anyone"

    def test_the_slider_value_is_kept_for_when_the_engine_returns(self, dead_engine):
        dead_engine.noise_scale = 60
        assert dead_engine.noise_scale == 60

    def test_the_failure_is_logged(self, dead_engine):
        log.exception.reset_mock()
        dead_engine.noise_scale = 60
        log.exception.assert_called_once()


@pytest.fixture
def kokoro_voice_dir(tmp_path, monkeypatch):
    """A second, Kokoro-shaped voice directory alongside the Piper one."""
    kokoro_dir = tmp_path / "kokoro"
    monkeypatch.setattr(tts_system, "DENGJEN_KOKORO_VOICES_DIR", str(kokoro_dir))
    voice_dir = kokoro_dir / "kokoro-multilingual"
    voice_dir.mkdir(parents=True)
    (voice_dir / "config.json").write_text("{}", encoding="utf-8")
    (voice_dir / "voice.json").write_text(
        '{"model_type": "kokoro", "name": "Kokoro", "language": "en"}',
        encoding="utf-8",
    )
    return kokoro_dir


class TestConstructionWithAKokoroVoicePresent:
    def test_does_not_crash_building_the_voice_list(
        self, configured_voice, kokoro_voice_dir, fake_backend
    ):
        d = SynthDriver()
        try:
            assert sorted(d.availableVoices) == sorted(
                [VOICE_KEY, "kokoro-multilingual"]
            )
        finally:
            d.terminate()


class TestSpeechTaskExecution:
    @pytest.fixture(autouse=True)
    def clean_cache(self, monkeypatch):
        phrase_cache = driver_module.phrase_cache
        phrase_cache.clear()

        async def _fake_run_in_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(driver_module, "run_in_executor", _fake_run_in_executor)

        yield
        phrase_cache.clear()

    def _make_mock_task(self, text="hello world", chunks=None):
        if chunks is None:
            # 2 chunks of 16-bit PCM (e.g. 4 samples each, 8 bytes each)
            chunks = [
                b"\x00\x10\x00\x20\x00\x10\x00\x20",
                b"\x00\x05\x00\x15\x00\x05\x00\x15",
            ]

        async def _gen():
            for c in chunks:
                yield c

        mock_task = MagicMock()
        mock_task.text = text
        mock_task.generate_audio = _gen

        options = MagicMock()
        options.rate = 50
        options.volume = 100
        options.pitch = 50
        options.sentence_silence_ms = 0

        voice = MagicMock()
        voice.key = "en_US-test-voice"
        voice.speaker = "default_spk"
        options.voice = voice

        mock_task.speech_options = options
        return mock_task

    def test_plain_stream_plays_chunks_and_caches(self):
        phrase_cache = driver_module.phrase_cache
        mock_task = self._make_mock_task()
        mock_player = MagicMock()

        task = SpeechTask(mock_task, mock_player)
        asyncio.run(task())

        assert mock_player.feed.call_count == 2
        assert mock_player.sync.call_count == 1

        cached = phrase_cache.get(
            "hello world", "en_US-test-voice", 50, 100, 50, speaker="default_spk"
        )
        assert cached is not None
        assert len(cached) == 2

    def test_cache_hit_plays_cached_chunks_directly(self):
        phrase_cache = driver_module.phrase_cache
        mock_task = self._make_mock_task()
        mock_player = MagicMock()

        phrase_cache.put(
            "hello world",
            "en_US-test-voice",
            50,
            100,
            50,
            False,
            False,
            [b"cached_chunk_1", b"cached_chunk_2"],
            speaker="default_spk",
        )

        task = SpeechTask(mock_task, mock_player)
        asyncio.run(task())

        mock_player.feed.assert_any_call(b"cached_chunk_1")
        mock_player.feed.assert_any_call(b"cached_chunk_2")
        assert mock_player.sync.call_count == 1

    def test_audio_processing_options_applied(self):
        phrase_cache = driver_module.phrase_cache
        mock_task = self._make_mock_task()
        mock_player = MagicMock()

        task = SpeechTask(
            mock_task,
            mock_player,
            normalize=True,
            night_mode=True,
            spatial_audio=True,
            pan=0.5,
        )
        asyncio.run(task())

        assert mock_player.feed.called
        assert mock_player.sync.called

        # Spatial audio is not cached
        cached = phrase_cache.get("hello world", "en_US-test-voice", 50, 100, 50)
        assert cached is None

    def test_say_all_normalizes_newlines_and_sentence_silence(self, monkeypatch):
        from speech import sayAll

        monkeypatch.setattr(sayAll.SayAllHandler, "isRunning", lambda: True)

        mock_task = self._make_mock_task(text="line 1\nline 2\nline 3")
        mock_player = MagicMock()

        task = SpeechTask(mock_task, mock_player)
        asyncio.run(task())

        assert mock_task.text == "line 1 line 2 line 3"
        assert mock_task.speech_options.sentence_silence_ms == 50

    def test_speaker_switching_and_restoration(self):
        mock_task = self._make_mock_task()
        voice = mock_task.speech_options.voice
        voice.speaker = "speaker_a"
        mock_player = MagicMock()

        speakers_during_stream = []

        async def _gen():
            speakers_during_stream.append(voice.speaker)
            yield b"\x00\x10\x00\x20"

        mock_task.generate_audio = _gen

        task = SpeechTask(mock_task, mock_player, speaker="speaker_b")
        asyncio.run(task())

        assert speakers_during_stream == ["speaker_b"]
        assert voice.speaker == "speaker_a"

    def test_speaker_switching_handles_exception(self, monkeypatch):
        mock_task = self._make_mock_task()

        class BadVoice:
            key = "en_US-test-voice"

            @property
            def speaker(self):
                return "orig"

            @speaker.setter
            def speaker(self, val):
                raise ValueError("cannot change speaker")

        mock_task.speech_options.voice = BadVoice()
        mock_player = MagicMock()

        debug_mock = MagicMock()
        monkeypatch.setattr(driver_module.log, "debug", debug_mock)

        task = SpeechTask(mock_task, mock_player, speaker="new_speaker")
        asyncio.run(task())

        assert debug_mock.called
        assert mock_player.feed.called
        phrase_cache = driver_module.phrase_cache
        assert (
            phrase_cache.get(
                "hello world", "en_US-test-voice", 50, 100, 50, speaker="new_speaker"
            )
            is None
        )


class TestStartupPreload:
    @pytest.fixture
    def fake_backend(self, monkeypatch):
        backend = GatedBackend()
        monkeypatch.setattr(driver_module, "_bootstrap_backend", lambda: backend)
        return backend

    @pytest.fixture
    def pending_driver(self, configured_voice, fake_backend):
        d = SynthDriver()
        yield d
        fake_backend.release.set()
        d.terminate()

    def test_construction_does_not_wait_for_the_model(self, pending_driver):
        assert pending_driver.tts is not None
        assert not pending_driver.tts.speech_options.voice.is_loaded

    def test_speech_waits_for_the_load_then_plays(self, pending_driver, fake_backend):
        spoken = []
        pending_driver._speak_now = spoken.append

        pending_driver.speak(["hi"])

        assert spoken == []
        fake_backend.release.set()
        wait_until(lambda: spoken == [["hi"]])

    def test_the_latest_deferred_utterance_wins(self, pending_driver, fake_backend):
        spoken = []
        pending_driver._speak_now = spoken.append

        pending_driver.speak(["a"])
        pending_driver.speak(["b"])
        fake_backend.release.set()
        wait_ready(pending_driver)

        assert spoken == [["b"]]

    def test_cancel_drops_a_deferred_utterance(self, pending_driver, fake_backend):
        spoken = []
        pending_driver._speak_now = spoken.append

        pending_driver.speak(["stale"])
        pending_driver.cancel()
        fake_backend.release.set()
        wait_ready(pending_driver)

        assert spoken == []

    def test_sliders_set_before_the_load_are_applied_after_it(
        self, pending_driver, fake_backend
    ):
        pending_driver.noise_scale = 30

        assert fake_backend.set_synth_options_calls == []
        fake_backend.release.set()
        wait_ready(pending_driver)
        assert fake_backend.set_synth_options_calls != []
        assert pending_driver.noise_scale == 30

    def test_speaker_set_before_the_load_is_kept_without_a_backend_call(
        self, pending_driver, fake_backend
    ):
        pending_driver.speaker = "alice"

        assert fake_backend.get_synth_options_calls == []
        assert pending_driver._current_speaker == "alice"

    def test_available_speakers_is_empty_until_loaded(self, pending_driver):
        assert pending_driver.availableSpeakers == {}

    def test_terminate_during_a_load_leaves_the_late_callback_inert(
        self, pending_driver, fake_backend
    ):
        spoken = []
        pending_driver._speak_now = spoken.append
        pending_driver.speak(["x"])
        voice = pending_driver.tts.speech_options.voice

        pending_driver.terminate()
        fake_backend.release.set()
        done = threading.Event()
        voice.begin_load().add_done_callback(lambda _f: done.set())
        assert done.wait(timeout=5)

        assert spoken == []


class TestFailedStartupLoad:
    def test_the_next_utterance_retries_the_load(self, configured_voice, fake_backend):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        d = SynthDriver()
        wait_until(lambda: log.exception.called)
        fake_backend.raise_on_load_voice(None)
        spoken = []
        d._speak_now = spoken.append

        d.speak(["again"])

        wait_until(lambda: spoken == [["again"]])
        ui.message.assert_not_called()
        d.terminate()

    def test_a_dropped_utterance_still_tells_nvda_speech_is_done(
        self, configured_voice, fake_backend
    ):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        d = SynthDriver()
        wait_until(lambda: log.exception.called)
        driver_module.synthDoneSpeaking.notify.reset_mock()

        d.speak(["lost"])

        wait_until(lambda: driver_module.synthDoneSpeaking.notify.called)
        d.terminate()


class TestStartupLoadFallsBackToAnotherSynth:
    @pytest.fixture
    def fallback(self, monkeypatch):
        fallback = MagicMock(return_value=True)
        monkeypatch.setattr(driver_module, "findAndSetNextSynth", fallback)
        return fallback

    @pytest.fixture
    def gated_backend(self, monkeypatch):
        backend = GatedBackend()
        monkeypatch.setattr(driver_module, "_bootstrap_backend", lambda: backend)
        return backend

    def test_a_failed_startup_load_hands_nvda_the_next_synth(
        self, configured_voice, gated_backend, fallback, monkeypatch
    ):
        gated_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        d = SynthDriver()
        monkeypatch.setattr(driver_module, "getSynth", lambda: d)
        gated_backend.release.set()

        wait_until(lambda: fallback.called)

        fallback.assert_called_once_with("dengjen_neural_voices")
        d.terminate()

    def test_a_driver_nvda_already_replaced_does_not_switch_again(
        self, configured_voice, fake_backend, fallback
    ):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        d = SynthDriver()

        wait_until(lambda: log.exception.called)

        fallback.assert_not_called()
        d.terminate()

    def test_a_successful_startup_load_keeps_the_synth(
        self, configured_voice, fake_backend, fallback, monkeypatch
    ):
        d = SynthDriver()
        monkeypatch.setattr(driver_module, "getSynth", lambda: d)
        wait_ready(d)

        fallback.assert_not_called()
        d.terminate()

    def test_a_failed_retry_on_speech_keeps_the_synth(
        self, configured_voice, fake_backend, fallback
    ):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        d = SynthDriver()
        wait_until(lambda: log.exception.called)
        log.exception.reset_mock()

        d.speak(["again"])

        wait_until(lambda: log.exception.called)
        fallback.assert_not_called()
        d.terminate()


class TestStartupLoadRefreshesTheSpeechSettings:
    def test_the_gui_is_refreshed_and_stale_choices_dropped_when_the_voice_loads(
        self, configured_voice, monkeypatch
    ):
        backend = GatedBackend()
        monkeypatch.setattr(driver_module, "_bootstrap_backend", lambda: backend)
        refreshed = []
        monkeypatch.setattr(
            driver_module,
            "update_displaied_params_on_voice_change",
            lambda synth: refreshed.append(synth),
        )
        d = SynthDriver()
        d._availableSpeakers = {}
        backend.release.set()

        wait_until(lambda: refreshed)

        assert refreshed == [d]
        assert not hasattr(d, "_availableSpeakers")
        d.terminate()

    def test_a_gui_refresh_failure_does_not_stop_the_voice_becoming_ready(
        self, configured_voice, fake_backend, monkeypatch
    ):
        def explode(synth):
            raise RuntimeError("no dialog")

        monkeypatch.setattr(
            driver_module, "update_displaied_params_on_voice_change", explode
        )
        d = SynthDriver()

        wait_ready(d)

        d.terminate()


OTHER_KEY = "en_US-other-medium"


FRENCH_KEY = "fr_FR-durand-medium"
THIRD_KEY = "en_US-third-medium"
FAST_KEY = "en_US-test+RT-medium"


@pytest.fixture
def second_voice(voices_dir):
    _write_voice(voices_dir, OTHER_KEY)
    _write_voice(voices_dir, THIRD_KEY)
    _write_voice(voices_dir, FRENCH_KEY)
    _write_voice(voices_dir, FAST_KEY)


class TestVoiceSwitch:
    @pytest.fixture
    def fake_backend(self, monkeypatch):
        backend = GatedBackend()
        backend.release.set()
        monkeypatch.setattr(driver_module, "_bootstrap_backend", lambda: backend)
        return backend

    @pytest.fixture
    def switch_driver(self, second_voice, configured_voice, fake_backend):
        d = SynthDriver()
        wait_ready(d)
        d.availableVoices = {
            key: _FakeVoiceInfo(f"{key} (en-US)") for key in d.availableVoices
        }
        d._SynthDriver__voice = VOICE_KEY
        yield d
        fake_backend.release.set()
        d.terminate()

    def test_switch_returns_before_the_new_voice_loads(
        self, switch_driver, fake_backend
    ):
        fake_backend.release.clear()

        switch_driver._set_voice(OTHER_KEY)

        assert switch_driver._SynthDriver__voice == OTHER_KEY
        assert switch_driver.tts.voice == OTHER_KEY
        assert not switch_driver.tts.speech_options.voice.is_loaded

    def test_switch_completes_once_loaded(self, switch_driver, fake_backend):
        fake_backend.release.clear()
        switch_driver._set_voice(OTHER_KEY)

        fake_backend.release.set()
        wait_ready(switch_driver)

        assert switch_driver.tts.voice == OTHER_KEY
        ui.message.assert_not_called()

    def test_speech_during_a_switch_waits_for_the_new_voice(
        self, switch_driver, fake_backend
    ):
        spoken = []
        switch_driver._speak_now = spoken.append
        fake_backend.release.clear()
        switch_driver._set_voice(OTHER_KEY)

        switch_driver.speak(["hello"])

        assert spoken == []
        fake_backend.release.set()
        wait_until(lambda: spoken == [["hello"]])
        assert switch_driver.tts.voice == OTHER_KEY

    def test_failed_load_restores_the_previous_voice_and_reports(
        self, switch_driver, fake_backend
    ):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))

        switch_driver._set_voice(OTHER_KEY)

        wait_until(lambda: ui.message.called)
        assert switch_driver._SynthDriver__voice == VOICE_KEY
        assert switch_driver.tts.voice == VOICE_KEY
        (message,), _ = ui.message.call_args
        assert switch_driver.availableVoices[OTHER_KEY].displayName in message
        log.exception.assert_called()

    def test_unknown_voice_falls_back_to_the_first_available(self, switch_driver):
        switch_driver._set_voice("does-not-exist")

        first = next(iter(switch_driver.availableVoices))
        assert switch_driver._SynthDriver__voice == first

    def test_a_superseded_switch_applies_and_reverts_nothing(
        self, switch_driver, fake_backend
    ):
        switch_driver._finish_switch = MagicMock()
        switch_driver._revert_switch = MagicMock()
        fake_backend.release.clear()
        switch_driver._set_voice(OTHER_KEY)
        slow = switch_driver.tts.speech_options.voice

        switch_driver._set_voice(VOICE_KEY)
        fake_backend.release.set()
        done = threading.Event()
        slow.begin_load().add_done_callback(lambda _f: done.set())
        assert done.wait(timeout=5)

        assert switch_driver._finish_switch.call_args_list == [call(VOICE_KEY)]
        switch_driver._revert_switch.assert_not_called()
        assert switch_driver.tts.voice == VOICE_KEY

    def test_variant_before_the_load_does_not_block(self, switch_driver, fake_backend):
        fake_backend.release.clear()
        switch_driver._set_voice(OTHER_KEY)

        started = time.monotonic()
        switch_driver.variant = "standard"

        assert time.monotonic() - started < 1
        assert switch_driver.tts.voice == OTHER_KEY

    def test_fast_variant_switch_returns_before_its_voice_loads(
        self, switch_driver, fake_backend
    ):
        fake_backend.release.clear()

        switch_driver.variant = "fast"

        assert switch_driver.tts.voice == FAST_KEY
        assert not switch_driver.tts.speech_options.voice.is_loaded
        fake_backend.release.set()
        wait_ready(switch_driver)
        ui.message.assert_not_called()

    def test_failed_variant_load_restores_the_previous_voice_and_reports(
        self, switch_driver, fake_backend
    ):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))

        switch_driver.variant = "fast"

        wait_until(lambda: ui.message.called)
        assert switch_driver.tts.voice == VOICE_KEY
        log.exception.assert_called()

    def test_a_failed_second_switch_reverts_to_the_last_loaded_voice(
        self, switch_driver, fake_backend
    ):
        fake_backend.release.clear()
        switch_driver._set_voice(OTHER_KEY)
        switch_driver._set_voice(THIRD_KEY)

        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        fake_backend.release.set()

        wait_until(lambda: ui.message.called)
        assert switch_driver.tts.voice == VOICE_KEY
        assert switch_driver._SynthDriver__voice == VOICE_KEY

    def test_speech_waits_for_a_switch_back_to_a_loaded_voice(
        self, switch_driver, fake_backend, monkeypatch
    ):
        switch_driver._set_voice(OTHER_KEY)
        wait_ready(switch_driver)
        queued = []
        monkeypatch.setattr(
            driver_module.wx,
            "CallAfter",
            lambda func, *a, **kw: queued.append(lambda: func(*a, **kw)),
        )
        spoken = []
        switch_driver._speak_now = spoken.append
        switch_driver._set_voice(VOICE_KEY)

        switch_driver.speak(["x"])

        assert spoken == []
        while queued:
            queued.pop(0)()
        assert spoken == [["x"]]

    def test_a_mid_utterance_language_change_does_not_block(
        self, switch_driver, fake_backend
    ):
        spoken = []
        switch_driver._speak_now = spoken.append
        fake_backend.release.clear()
        sequence = ["a", _lang_change_command("fr_FR"), "b"]

        started = time.monotonic()
        switch_driver.speak(sequence)

        assert time.monotonic() - started < 1
        assert spoken == []
        fake_backend.release.set()
        wait_until(lambda: spoken == [sequence])

    def test_a_language_voice_failure_keeps_a_newer_deferred_utterance(
        self, switch_driver
    ):
        older, newer = ["a"], ["b"]
        switch_driver._deferred_speech = newer
        driver_module.synthDoneSpeaking.notify.reset_mock()

        switch_driver._on_deferred_load_failed(older, VoiceLoadError("corrupt"))

        assert switch_driver._deferred_speech is newer
        driver_module.synthDoneSpeaking.notify.assert_not_called()

    def test_a_language_voice_failure_drops_the_utterance_that_needed_it(
        self, switch_driver
    ):
        sequence = ["a"]
        switch_driver._deferred_speech = sequence
        driver_module.synthDoneSpeaking.notify.reset_mock()

        switch_driver._on_deferred_load_failed(sequence, VoiceLoadError("corrupt"))

        assert switch_driver._deferred_speech is None
        driver_module.synthDoneSpeaking.notify.assert_called()

    def test_a_late_load_after_the_app_is_gone_logs_nothing_at_error(
        self, switch_driver, monkeypatch, caplog
    ):
        def app_gone(*_a, **_kw):
            raise RuntimeError("wx app destroyed")

        monkeypatch.setattr(driver_module.wx, "CallAfter", app_gone)
        voice = switch_driver.tts.speech_options.voice

        switch_driver._watch_load(voice, MagicMock(), MagicMock())

        assert not [r for r in caplog.records if r.levelname == "ERROR"]


class TestFailedStartupSwitch:
    def test_the_startup_voice_setting_fails_quietly_and_keeps_a_voice_name(
        self, configured_voice, fake_backend
    ):
        fake_backend.raise_on_load_voice(VoiceLoadError("corrupt"))
        d = SynthDriver()
        wait_until(lambda: log.exception.called)
        log.exception.reset_mock()

        d._set_voice(VOICE_KEY)

        wait_until(lambda: log.exception.called)
        ui.message.assert_not_called()
        assert d._SynthDriver__voice == VOICE_KEY
        d.terminate()
