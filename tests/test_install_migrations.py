# coding: utf-8
"""Tests for the 4.0.0 upgrade path in installTasks.py.

The real upgrade runs inside NVDA on Windows. These exercise the decision
logic against a temporary directory and fake config objects; the NVDA-side
behaviour still needs an end-user check on the built artifact.
"""

import os
from unittest.mock import MagicMock

import pytest

from tests.conftest import REPO_ROOT, load_module_from_path

install_tasks = load_module_from_path(
    "_install_migrations_under_test",
    os.path.join(REPO_ROOT, "addon", "installTasks.py"),
)


@pytest.fixture
def fresh_log(monkeypatch):
    """A MagicMock scoped to a single test — logHandler.log is a session-wide
    stub shared with every other test module, so asserting on its call list
    without isolating it would pick up calls made elsewhere."""
    fake_log = MagicMock()
    monkeypatch.setattr(install_tasks, "log", fake_log)
    return fake_log


class TestMigrateVoicesDirectory:
    def test_moves_the_old_directory_when_the_new_one_is_absent(self, tmp_path):
        (tmp_path / "sonata" / "voices" / "piper").mkdir(parents=True)
        assert install_tasks.migrate_voices_directory(str(tmp_path)) is True
        assert (tmp_path / "dengjen" / "voices" / "piper").is_dir()
        assert not (tmp_path / "sonata").exists()

    def test_leaves_both_alone_when_the_new_directory_already_exists(self, tmp_path):
        (tmp_path / "sonata" / "voices").mkdir(parents=True)
        (tmp_path / "dengjen" / "voices").mkdir(parents=True)
        assert install_tasks.migrate_voices_directory(str(tmp_path)) is False
        assert (tmp_path / "sonata" / "voices").is_dir()

    def test_is_a_noop_when_there_is_nothing_to_migrate(self, tmp_path):
        assert install_tasks.migrate_voices_directory(str(tmp_path)) is False
        assert not (tmp_path / "dengjen").exists()

    def test_ignores_a_file_named_like_the_old_directory(self, tmp_path):
        (tmp_path / "sonata").write_text("not a directory")
        assert install_tasks.migrate_voices_directory(str(tmp_path)) is False
        assert not (tmp_path / "dengjen").exists()

    def test_logs_why_it_skipped_when_the_new_directory_already_exists(
        self, tmp_path, fresh_log
    ):
        (tmp_path / "sonata" / "voices").mkdir(parents=True)
        (tmp_path / "dengjen" / "voices").mkdir(parents=True)
        install_tasks.migrate_voices_directory(str(tmp_path))
        assert fresh_log.info.call_count == 1
        assert str(tmp_path / "dengjen") in fresh_log.info.call_args[0][0]

    def test_logs_why_it_skipped_when_there_is_nothing_to_migrate(
        self, tmp_path, fresh_log
    ):
        install_tasks.migrate_voices_directory(str(tmp_path))
        assert fresh_log.info.call_count == 1
        assert str(tmp_path / "sonata") in fresh_log.info.call_args[0][0]

    def test_warns_the_user_and_logs_when_the_move_raises(
        self, tmp_path, fresh_log, monkeypatch
    ):
        (tmp_path / "sonata" / "voices").mkdir(parents=True)

        def _boom(src, dst):
            raise PermissionError("file in use")

        monkeypatch.setattr(install_tasks.os, "rename", _boom)
        shown = []
        monkeypatch.setattr(
            install_tasks.gui, "messageBox", lambda *a, **kw: shown.append((a, kw))
        )
        assert install_tasks.migrate_voices_directory(str(tmp_path)) is False
        assert fresh_log.exception.call_count == 1
        assert len(shown) == 1
        message_text = shown[0][0][0]
        assert str(tmp_path / "sonata") in message_text

    def test_does_not_raise_when_the_move_fails(self, tmp_path, monkeypatch):
        (tmp_path / "sonata" / "voices").mkdir(parents=True)

        def _boom(src, dst):
            raise PermissionError("file in use")

        monkeypatch.setattr(install_tasks.os, "rename", _boom)
        monkeypatch.setattr(install_tasks.gui, "messageBox", lambda *a, **kw: None)
        install_tasks.migrate_voices_directory(str(tmp_path))


class _FakeSection(dict):
    """Stands in for NVDA's ConfigObj section, which has isSet()."""

    def __missing__(self, key):
        val = _FakeSection()
        self[key] = val
        return val

    def isSet(self, key):
        return key in self


def _speech_conf(**sections):
    speech = _FakeSection()
    speech.update(sections)
    return {"speech": speech}


class TestMigrateSpeechConfig:
    def test_copies_the_old_section_when_the_new_one_is_absent(self):
        conf = _speech_conf(
            sonata_neural_voices={
                "rate": 55,
                "voices": {"en_US-amy-medium": {"speaker": "amy"}},
            }
        )
        assert install_tasks.migrate_speech_config(conf) is True
        assert conf["speech"]["dengjen_neural_voices"] == {
            "rate": 55,
            "voices": {"en_US-amy-medium": {"speaker": "amy"}},
        }

    def test_copies_rather_than_aliases_nested_sections(self):
        conf = _speech_conf(
            sonata_neural_voices={"voices": {"en_US-amy-medium": {"speaker": "amy"}}}
        )
        install_tasks.migrate_speech_config(conf)
        conf["speech"]["dengjen_neural_voices"]["voices"]["en_US-amy-medium"][
            "speaker"
        ] = "changed"
        assert (
            conf["speech"]["sonata_neural_voices"]["voices"]["en_US-amy-medium"][
                "speaker"
            ]
            == "amy"
        )

    def test_leaves_the_old_section_in_place(self):
        conf = _speech_conf(sonata_neural_voices={"rate": 55})
        install_tasks.migrate_speech_config(conf)
        assert conf["speech"]["sonata_neural_voices"] == {"rate": 55}

    def test_leaves_an_existing_new_section_alone(self):
        conf = _speech_conf(
            sonata_neural_voices={"rate": 55}, dengjen_neural_voices={"rate": 80}
        )
        assert install_tasks.migrate_speech_config(conf) is False
        assert conf["speech"]["dengjen_neural_voices"] == {"rate": 80}

    def test_is_a_noop_when_there_is_no_old_section(self):
        conf = _speech_conf()
        assert install_tasks.migrate_speech_config(conf) is False
        assert "dengjen_neural_voices" not in conf["speech"]


class _FakeAggregatedSection:
    """Stands in for NVDA's config.AggregatedSection.

    The real object provides items(), copy() and dict() but — unlike a plain
    dict or the dict-subclassing _FakeSection above — it has no keys(). Any
    migration code that guards its recursion with hasattr(value, "keys")
    silently treats a nested section as a leaf value here, exactly as it
    would against the real NVDA object.
    """

    def __init__(self, data=None):
        self._data = {}
        for key, value in (data or {}).items():
            self[key] = value

    def __setitem__(self, key, value):
        if isinstance(value, dict) and not isinstance(value, _FakeAggregatedSection):
            value = _FakeAggregatedSection(value)
        self._data[key] = value

    def __getitem__(self, key):
        if key not in self._data:
            self._data[key] = _FakeAggregatedSection()
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def items(self):
        return self._data.items()

    def isSet(self, key):
        return key in self._data

    def as_plain_dict(self):
        return {
            key: value.as_plain_dict() if isinstance(value, _FakeAggregatedSection) else value
            for key, value in self._data.items()
        }

    def __eq__(self, other):
        if isinstance(other, _FakeAggregatedSection):
            other = other.as_plain_dict()
        if not isinstance(other, dict):
            return NotImplemented
        return self.as_plain_dict() == other


def _aggregated_speech_conf(**sections):
    speech = _FakeAggregatedSection()
    for name, value in sections.items():
        speech[name] = value
    return {"speech": speech}


class TestMigrateSpeechConfigAgainstAggregatedSection:
    """Same behaviour as TestMigrateSpeechConfig, but against a double whose
    method surface matches the real config.AggregatedSection (no keys()),
    not the dict-subclassing _FakeSection the rest of this file uses."""

    def test_copies_the_old_section_when_the_new_one_is_absent(self):
        conf = _aggregated_speech_conf(
            sonata_neural_voices={
                "rate": 55,
                "voices": {"en_US-amy-medium": {"speaker": "amy"}},
            }
        )
        assert install_tasks.migrate_speech_config(conf) is True
        assert conf["speech"]["dengjen_neural_voices"] == {
            "rate": 55,
            "voices": {"en_US-amy-medium": {"speaker": "amy"}},
        }

    def test_copies_rather_than_aliases_nested_sections(self):
        conf = _aggregated_speech_conf(
            sonata_neural_voices={"voices": {"en_US-amy-medium": {"speaker": "amy"}}}
        )
        install_tasks.migrate_speech_config(conf)
        conf["speech"]["dengjen_neural_voices"]["voices"]["en_US-amy-medium"][
            "speaker"
        ] = "changed"
        assert (
            conf["speech"]["sonata_neural_voices"]["voices"]["en_US-amy-medium"][
                "speaker"
            ]
            == "amy"
        )

    def test_leaves_the_old_section_in_place(self):
        conf = _aggregated_speech_conf(sonata_neural_voices={"rate": 55})
        install_tasks.migrate_speech_config(conf)
        assert conf["speech"]["sonata_neural_voices"] == {"rate": 55}

    def test_leaves_an_existing_new_section_alone(self):
        conf = _aggregated_speech_conf(
            sonata_neural_voices={"rate": 55}, dengjen_neural_voices={"rate": 80}
        )
        assert install_tasks.migrate_speech_config(conf) is False
        assert conf["speech"]["dengjen_neural_voices"] == {"rate": 80}

    def test_is_a_noop_when_there_is_no_old_section(self):
        conf = _aggregated_speech_conf()
        assert install_tasks.migrate_speech_config(conf) is False
        assert "dengjen_neural_voices" not in conf["speech"]


class _FakeAddon:
    def __init__(self, name, pending_remove=False):
        self.name = name
        self.isPendingRemove = pending_remove


class TestIsOldAddonInstalled:
    def test_detects_the_old_addon(self):
        assert install_tasks.is_old_addon_installed(
            [_FakeAddon("sonata_neural_voices")]
        ) is True

    def test_ignores_the_new_addon(self):
        assert install_tasks.is_old_addon_installed(
            [_FakeAddon("dengjen_neural_voices")]
        ) is False

    def test_ignores_an_addon_already_pending_removal(self):
        assert install_tasks.is_old_addon_installed(
            [_FakeAddon("sonata_neural_voices", pending_remove=True)]
        ) is False

    def test_handles_an_empty_addon_list(self):
        assert install_tasks.is_old_addon_installed([]) is False


class TestWarnIfOldAddonInstalled:
    def test_warns_when_the_old_addon_is_present(self, monkeypatch):
        shown = []
        monkeypatch.setattr(
            install_tasks.gui, "messageBox", lambda *a, **kw: shown.append((a, kw))
        )
        install_tasks.warn_if_old_addon_installed([_FakeAddon("sonata_neural_voices")])
        assert len(shown) == 1
        assert "Sonata" in shown[0][0][0]

    def test_shows_the_warning_via_wx_CallAfter_not_directly(self, monkeypatch):
        # gui.messageBox must be deferred through wx.CallAfter rather than
        # called directly, or it would stack a modal dialog on top of NVDA's
        # add-on installation dialog.
        call_after_calls = []
        monkeypatch.setattr(
            install_tasks.wx,
            "CallAfter",
            lambda func, *a, **kw: call_after_calls.append((func, a, kw)),
        )
        message_box_calls = []
        monkeypatch.setattr(
            install_tasks.gui,
            "messageBox",
            lambda *a, **kw: message_box_calls.append((a, kw)),
        )
        install_tasks.warn_if_old_addon_installed([_FakeAddon("sonata_neural_voices")])
        assert len(call_after_calls) == 1
        assert call_after_calls[0][0] is install_tasks.gui.messageBox
        assert message_box_calls == []

    def test_stays_quiet_when_it_is_absent(self, monkeypatch):
        shown = []
        monkeypatch.setattr(
            install_tasks.gui, "messageBox", lambda *a, **kw: shown.append((a, kw))
        )
        install_tasks.warn_if_old_addon_installed([])
        assert shown == []


class TestOnInstall:
    def test_runs_every_step_in_order(self, monkeypatch):
        ran = []
        monkeypatch.setattr(
            install_tasks, "warn_if_old_addon_installed", lambda: ran.append("warn")
        )
        monkeypatch.setattr(
            install_tasks, "migrate_voices_directory", lambda: ran.append("voices")
        )
        monkeypatch.setattr(
            install_tasks, "migrate_speech_config", lambda: ran.append("config")
        )
        install_tasks.onInstall()
        assert ran == ["warn", "voices", "config"]

    def test_a_failing_step_does_not_abort_the_install(self, monkeypatch):
        ran = []

        def _boom():
            raise OSError("permission denied")

        monkeypatch.setattr(install_tasks, "warn_if_old_addon_installed", _boom)
        monkeypatch.setattr(
            install_tasks, "migrate_voices_directory", lambda: ran.append("voices")
        )
        monkeypatch.setattr(
            install_tasks, "migrate_speech_config", lambda: ran.append("config")
        )
        install_tasks.onInstall()
        assert ran == ["voices", "config"]
