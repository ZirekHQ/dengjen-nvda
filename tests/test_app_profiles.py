import os
from unittest.mock import MagicMock

import pytest

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

app_profiles = load_module_from_path(
    "dengjen_neural_voices.domain._app_profiles_under_test",
    os.path.join(SYNTH_PKG_DIR, "domain", "app_profiles.py"),
    package="dengjen_neural_voices.domain",
)
AppProfileManager = app_profiles.AppProfileManager


class FakeProfile(dict):
    def __init__(self, name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name


class FakeConfig:
    def __init__(self):
        self._dirtyProfiles = set()
        self.profiles = [FakeProfile(name="base")]
        self.conf_dict = {"speech": {"dengjen_neural_voices": {}}}

    def _markWriteProfileDirty(self):
        if len(self.profiles) > 1:
            self._dirtyProfiles.add(self.profiles[-1].name)

    def __getitem__(self, key):
        return self.conf_dict[key]

    def isSet(self, key):
        return key in self.conf_dict


@pytest.fixture
def mock_nvda_config(monkeypatch):
    import config

    fake = FakeConfig()
    monkeypatch.setattr(config, "conf", fake)
    return fake


class TestAppProfileManager:
    def test_list_profiles_excludes_many_wildcard(self, mock_nvda_config):
        mgr = AppProfileManager()
        section = mgr._profiles_section()
        section["__many__"] = {"voice": "default", "rate": 50}
        section["notepad.exe"] = {"voice": "piper:test", "rate": 60}

        profiles = mgr.list_profiles()
        names = [name for name, _ in profiles]
        assert "__many__" not in names
        assert "notepad.exe" in names

    def test_list_profiles_includes_empty_profile(self, mock_nvda_config):
        mgr = AppProfileManager()
        section = mgr._profiles_section()
        section["empty.exe"] = {"voice": None, "rate": None}

        profiles = mgr.list_profiles()
        assert ("empty.exe", {}) in profiles

    def test_get_profile_rejects_many_wildcard(self, mock_nvda_config):
        mgr = AppProfileManager()
        section = mgr._profiles_section()
        section["__many__"] = {"voice": "default"}
        assert mgr.get_profile("__many__") == {}
        assert mgr.get_profile("") == {}

    def test_ensure_section_spec_copies_from_many(self, mock_nvda_config):
        mgr = AppProfileManager()
        section = MagicMock()
        section._spec = {
            "__many__": {
                "rate": "integer(min=0, max=100)",
                "volume": "integer(min=0, max=100)",
            }
        }
        mgr._ensure_section_spec(section, "code.exe")
        assert "code.exe" in section._spec
        assert section._spec["code.exe"] == section._spec["__many__"]

    def test_set_profile_none_removes_key_and_marks_dirty(
        self, mock_nvda_config, monkeypatch
    ):
        mgr = AppProfileManager()
        dirty_called = False

        def fake_mark_dirty():
            nonlocal dirty_called
            dirty_called = True

        import config

        monkeypatch.setattr(config.conf, "_markWriteProfileDirty", fake_mark_dirty)

        mgr.set_profile("app.exe", voice="v1", rate=50)
        assert mgr.get_profile("app.exe")["voice"] == "v1"

        mgr.set_profile("app.exe", voice=None)
        assert "voice" not in mgr.get_profile("app.exe")
        assert dirty_called

    def test_delete_profile_removes_from_all_profiles_and_marks_dirty(
        self, mock_nvda_config
    ):
        import config

        p1 = FakeProfile(name="profile1")
        p1["speech"] = {
            "dengjen_neural_voices": {"app_profiles": {"app.exe": {"rate": 50}}}
        }
        p2 = FakeProfile(name="profile2")
        p2["speech"] = {
            "dengjen_neural_voices": {"app_profiles": {"app.exe": {"rate": 60}}}
        }
        config.conf.profiles = [p1, p2]

        mgr = AppProfileManager()
        mgr.set_profile("app.exe", rate=70)

        mgr.delete_profile("app.exe")
        assert mgr.get_profile("app.exe") == {}
        assert "app.exe" not in p1["speech"]["dengjen_neural_voices"]["app_profiles"]
        assert "app.exe" not in p2["speech"]["dengjen_neural_voices"]["app_profiles"]
        assert "profile1" in config.conf._dirtyProfiles
        assert "profile2" in config.conf._dirtyProfiles

    def test_apply_profile_dict_clamps_and_handles_bad_values(self, monkeypatch):
        mgr = AppProfileManager()
        synth = MagicMock()
        synth.voice = "old_voice"

        debug_mock = MagicMock()
        monkeypatch.setattr(app_profiles.log, "debug", debug_mock)

        profile = {
            "voice": "new_voice",
            "rate": "150",
            "volume": "-20",
            "pitch": "invalid_number",
        }
        res = mgr.apply_profile_dict(profile, synth)
        assert res is True
        assert synth.voice == "new_voice"
        assert synth.rate == 100
        assert synth.volume == 0
        debug_mock.assert_called_once()
        assert "invalid pitch" in debug_mock.call_args[0][0]

    def test_is_valid_exe(self):
        assert app_profiles._is_valid_exe("notepad.exe") is True
        assert app_profiles._is_valid_exe("") is False
        assert app_profiles._is_valid_exe(None) is False
        assert app_profiles._is_valid_exe("__many__") is False
        assert app_profiles._is_valid_exe("__spec__") is False

    def test_extract_profile_data(self):
        class ObjWithDict:
            def dict(self):
                return {"voice": "v1", "__desc__": "skip", "rate": None, "pitch": 50}

        assert app_profiles._extract_profile_data(ObjWithDict()) == {
            "voice": "v1",
            "pitch": 50,
        }

        assert app_profiles._extract_profile_data(
            {"rate": 40, "__spec__": "x", "other": None}
        ) == {"rate": 40}

        assert app_profiles._extract_profile_data("not_a_dict") == {}

    def test_delete_target_key_variants(self):
        # Target with _getUpdateSection
        mock_target = MagicMock()
        mock_underlying = {"key1": "val1"}
        mock_target._getUpdateSection.return_value = mock_underlying
        mock_target._cache = {"key1": "cached"}
        app_profiles._delete_target_key(mock_target, "key1")
        assert "key1" not in mock_underlying
        assert "key1" not in mock_target._cache

        # Target with pop
        d = {"k": 1}
        app_profiles._delete_target_key(d, "k")
        assert "k" not in d

        # Target with delitem only
        class DelOnly:
            def __init__(self):
                self.d = {"k": 1}

            def __delitem__(self, key):
                del self.d[key]

        obj = DelOnly()
        app_profiles._delete_target_key(obj, "k")
        assert "k" not in obj.d

    def test_delete_profile_with_update_section_and_cache(
        self, mock_nvda_config, monkeypatch
    ):
        mgr = AppProfileManager()

        class MockSection(dict):
            pass

        mock_section = MockSection()
        monkeypatch.setattr(mgr, "_profiles_section", lambda: mock_section)
        mock_update = {"test.exe": {"rate": 50}}
        mock_section._getUpdateSection = lambda: mock_update
        mock_section._cache = {"test.exe": "cached"}
        mock_section._spec = {"test.exe": "spec"}

        mock_section["test.exe"] = {"rate": 50}
        mgr.delete_profile("test.exe")

        assert "test.exe" not in mock_section
        assert "test.exe" not in mock_update
        assert "test.exe" not in mock_section._cache
        assert "test.exe" not in mock_section._spec

    def test_apply_profile_dict_all_options_and_failures(self, monkeypatch):
        mgr = AppProfileManager()
        synth = MagicMock()
        synth.voice = "old"

        # Empty dict returns False
        assert mgr.apply_profile_dict({}, synth) is False
        assert mgr.apply_profile_dict(None, synth) is False

        # All options
        profile = {
            "voice": "new_voice",
            "variant": "fast",
            "speaker": "spk_1",
            "rate": "60",
            "volume": "80",
            "pitch": "50",
        }
        assert mgr.apply_profile_dict(profile, synth) is True
        assert synth.voice == "new_voice"
        assert synth.variant == "fast"
        assert synth.speaker == "spk_1"
        assert synth.rate == 60
        assert synth.volume == 80
        assert synth.pitch == 50

        # Bad volume and rate types log debug
        debug_mock = MagicMock()
        monkeypatch.setattr(app_profiles.log, "debug", debug_mock)
        mgr.apply_profile_dict({"rate": "bad_rate", "volume": "bad_vol"}, synth)
        assert debug_mock.call_count == 2

        # Exception when setting attribute
        synth_err = MagicMock()
        type(synth_err).voice = property(
            fget=lambda self: "old",
            fset=MagicMock(side_effect=RuntimeError("fail")),
        )
        assert mgr.apply_profile_dict({"voice": "new"}, synth_err) is False

    def test_apply_for_exe(self, mock_nvda_config):
        mgr = AppProfileManager()
        synth = MagicMock()
        synth.voice = "default"

        # Not found
        assert mgr.apply_for_exe("nonexistent.exe", synth) is False

        # Found and applied
        mgr.set_profile("code.exe", voice="piper:code", rate=70)
        assert mgr.apply_for_exe("code.exe", synth) is True
        assert synth.voice == "piper:code"
        assert synth.rate == 70

    def test_init_creates_missing_section_and_handles_exception(
        self, mock_nvda_config, monkeypatch
    ):
        import config

        speech_mock = MagicMock()
        speech_mock.isSet.return_value = False
        config.conf.conf_dict["speech"] = speech_mock

        mgr = AppProfileManager()
        assert mgr is not None
        assert "dengjen_neural_voices" in speech_mock.__setitem__.call_args[0]

        # When ConfigObj raises exception
        exc_mock = MagicMock()
        monkeypatch.setattr(app_profiles.log, "exception", exc_mock)
        monkeypatch.setattr(
            app_profiles, "ConfigObj", MagicMock(side_effect=Exception("parse error"))
        )
        mgr2 = AppProfileManager()
        assert mgr2 is not None
        exc_mock.assert_called_once()
