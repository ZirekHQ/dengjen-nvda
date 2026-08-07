# coding: utf-8
"""
Tests for the SynthDriver itself: construction, speech sequence handling,
flush/cancel ordering, the settings NVDA reads and writes through driver
properties, and _set_voice's failure handling
(addon/synthDrivers/dengjen_neural_voices/__init__.py).

conftest.py registers `dengjen_neural_voices` as a package without running
its __init__.py, so until now nothing imported or drove the SynthDriver
class (see issue #65 -- this is where user-reported regressions have
historically lived). This module executes the real __init__.py under the
same stubs used for the rest of the package, replacing the hollow package
stub, then constructs the driver against a fake on-disk voice.

The TestSetVoice* classes below additionally cover issue #69: a voice that
exists on disk but fails to load (e.g. a corrupted .onnx file) must not
leave the driver in a half-switched state -- the previously active voice
should remain current, and NVDA should report a message instead of letting
an unhandled exception surface as an error chime. They load a second,
separate instance of the same module under a private name so the fake TTS
stand-ins used here don't interfere with the on-disk fixtures above.
"""

import os

import config
import pytest
import ui
from unittest.mock import MagicMock

from logHandler import log

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

import dengjen_neural_voices.tts_system as tts_system
from dengjen_neural_voices.const import FALLBACK_SPEAKER_NAME
from speech.commands import BreakCommand, IndexCommand, LangChangeCommand

driver_module = load_module_from_path(
    "dengjen_neural_voices",
    os.path.join(SYNTH_PKG_DIR, "__init__.py"),
    package="dengjen_neural_voices",
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
    monkeypatch.setattr(tts_system, "SONATA_VOICES_DIR", str(tmp_path))
    _write_voice(tmp_path)
    return tmp_path


@pytest.fixture
def configured_voice(voices_dir):
    """Point config at the on-disk voice, like a real NVDA profile would."""
    config.conf["speech"][SECTION].clear()
    config.conf["speech"][SECTION]["voice"] = VOICE_KEY
    return voices_dir


@pytest.fixture
def driver(configured_voice):
    d = SynthDriver()
    yield d
    d.terminate()


class TestConstruction:
    def test_loads_the_voice_on_disk(self, driver):
        assert [v.key for v in driver.voices] == [VOICE_KEY]

    def test_selects_the_configured_voice(self, driver):
        assert driver.tts.voice == VOICE_KEY

    def test_falls_back_to_first_voice_when_configured_voice_is_unknown(
        self, voices_dir
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
        # VoiceInfo is stubbed to return an (id, name, lang) tuple. Compare
        # against languageHandler.normalizeLanguage rather than a hardcoded
        # string so this doesn't assume any particular normalization casing.
        import languageHandler

        voice_id, display_name, lang = driver.availableVoices[VOICE_KEY]
        assert voice_id == VOICE_KEY
        expected_lang = languageHandler.normalizeLanguage(lang).replace("_", "-")
        assert f"({expected_lang})" in display_name


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
        # A LangChangeCommand to the voice's own (already-default) language
        # is a no-op for tts.language, but must still split the surrounding
        # text into two SpeechTasks rather than merging it into one.
        seq = ["hello ", "world", _lang_change_command("en_US", is_default=True), "more"]
        tasks = driver._build_speech_tasks(seq)
        assert [type(t) for t in tasks] == [SpeechTask, SpeechTask, DoneSpeakingTask]


class TestLifecycle:
    def test_cancel_stops_the_player(self, driver):
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
        driver._player.pause = MagicMock()
        driver.pause(True)
        driver._player.pause.assert_called_once_with(True)

    def test_terminate_closes_every_player_and_clears_them(self, driver):
        extra_player = MagicMock()
        driver._players["extra"] = extra_player
        real_player = driver._player
        real_player.close = MagicMock()
        driver.terminate()
        real_player.close.assert_called_once()
        extra_player.close.assert_called_once()
        assert driver._players == {}


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
        driver._player.setVolume = MagicMock()
        driver.volume = 42
        assert driver.volume == 42
        driver._player.setVolume.assert_called_once_with(all=0.42)

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


_failure_driver_module = load_module_from_path(
    "dengjen_neural_voices._init_under_test",
    os.path.join(SYNTH_PKG_DIR, "__init__.py"),
    package="dengjen_neural_voices",
)
_FailureSynthDriver = _failure_driver_module.SynthDriver


class _FakeVoiceEntry:
    """Stand-in for a _standard_voice_map value (a SonataVoice)."""

    def __init__(self, key, variant="unknown"):
        self.key = key
        self.variant = variant


class _FakeVoiceInfo:
    """Stand-in for synthDriverHandler.VoiceInfo -- only .displayName is used."""

    def __init__(self, display_name):
        self.displayName = display_name


class _FakeTTSRaising:
    """Stand-in for SonataTextToSpeechSystem whose voice setter always fails,
    as happens when the underlying .onnx model is corrupted/incomplete."""

    voice = None

    def __init__(self):
        # conftest's _AutoPropertyMeta wires noise_scale/length_scale/noise_w
        # into real properties that reach through tts.speech_options.voice;
        # a MagicMock happily fabricates that chain for values these tests
        # never assert on.
        self.speech_options = MagicMock()

    def __setattr__(self, name, value):
        if name == "voice":
            raise RuntimeError("Protobuf parsing failed")
        super().__setattr__(name, value)


class _FakeTTSAccepting:
    """Stand-in for SonataTextToSpeechSystem whose voice setter succeeds."""

    def __init__(self):
        self.voice = None
        self.speech_options = MagicMock()


def _make_driver(voice_map, available_voices, tts, initial_voice=None):
    driver = _FailureSynthDriver.__new__(_FailureSynthDriver)
    driver._standard_voice_map = voice_map
    driver.availableVoices = available_voices
    driver._voice_map = {}
    driver.tts = tts
    driver.noise_scale = 50
    driver.length_scale = 50
    driver.noise_w = 50
    driver._SynthDriver__voice = initial_voice
    return driver


@pytest.fixture(autouse=True)
def _reset_mocks():
    ui.message.reset_mock()
    log.exception.reset_mock()
    yield


class TestSetVoiceFailure:
    def test_failed_load_keeps_the_previous_voice(self):
        driver = _make_driver(
            voice_map={
                "alex": _FakeVoiceEntry("en_US-alex-medium"),
                "bryce": _FakeVoiceEntry("en_US-bryce-medium"),
            },
            available_voices={
                "alex": _FakeVoiceInfo("Alex (en-US)"),
                "bryce": _FakeVoiceInfo("Bryce (en-US)"),
            },
            tts=_FakeTTSRaising(),
            initial_voice="alex",
        )

        driver._set_voice("bryce")

        # No half-switched state: the driver still reports the last voice
        # that actually loaded, not the one that failed.
        assert driver._SynthDriver__voice == "alex"

    def test_failed_load_reports_a_message_naming_the_voice(self):
        driver = _make_driver(
            voice_map={"bryce": _FakeVoiceEntry("en_US-bryce-medium")},
            available_voices={"bryce": _FakeVoiceInfo("Bryce (en-US)")},
            tts=_FakeTTSRaising(),
            initial_voice=None,
        )

        driver._set_voice("bryce")

        ui.message.assert_called_once()
        (message,), _kwargs = ui.message.call_args
        assert "Bryce (en-US)" in message

    def test_failed_load_does_not_raise(self):
        driver = _make_driver(
            voice_map={"bryce": _FakeVoiceEntry("en_US-bryce-medium")},
            available_voices={"bryce": _FakeVoiceInfo("Bryce (en-US)")},
            tts=_FakeTTSRaising(),
            initial_voice=None,
        )

        driver._set_voice("bryce")  # must not raise

    def test_failed_load_logs_the_exception(self):
        driver = _make_driver(
            voice_map={"bryce": _FakeVoiceEntry("en_US-bryce-medium")},
            available_voices={"bryce": _FakeVoiceInfo("Bryce (en-US)")},
            tts=_FakeTTSRaising(),
            initial_voice=None,
        )

        driver._set_voice("bryce")

        log.exception.assert_called_once()


class TestSetVoiceSuccess:
    def test_successful_load_switches_the_current_voice(self):
        driver = _make_driver(
            voice_map={
                "alex": _FakeVoiceEntry("en_US-alex-medium"),
                "danny": _FakeVoiceEntry("en_US-danny-low"),
            },
            available_voices={
                "alex": _FakeVoiceInfo("Alex (en-US)"),
                "danny": _FakeVoiceInfo("Danny (en-US)"),
            },
            tts=_FakeTTSAccepting(),
            initial_voice="alex",
        )

        driver._set_voice("danny")

        assert driver._SynthDriver__voice == "danny"
        assert driver.tts.voice == "en_US-danny-low"
        ui.message.assert_not_called()

    def test_falls_back_to_the_first_available_voice_when_value_unknown(self):
        driver = _make_driver(
            voice_map={"alex": _FakeVoiceEntry("en_US-alex-medium")},
            available_voices={"alex": _FakeVoiceInfo("Alex (en-US)")},
            tts=_FakeTTSAccepting(),
            initial_voice=None,
        )

        driver._set_voice("does-not-exist")

        assert driver._SynthDriver__voice == "alex"
        assert driver.tts.voice == "en_US-alex-medium"
