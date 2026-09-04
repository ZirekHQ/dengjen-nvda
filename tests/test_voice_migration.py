"""Tests for the 4.0.0 voices-directory migration
(addon/synthDrivers/dengjen_neural_voices/voice_migration.py).

The migration used to run once, from installTasks.onInstall. Issue #83 showed
why that cannot work: at install time the old Sonata add-on still holds its
.onnx files open, so the move fails, and the synth driver then creates an
empty tree at the destination on its next load. An exists() guard reads that
empty tree as "already migrated", so the voices were stranded for good and
the reporter had to redownload them.

It now runs before every voice enumeration instead, and skips only when the
destination genuinely holds voices.
"""

import os
from unittest.mock import MagicMock

import pytest
from dengjen_neural_voices import voice_migration
from dengjen_neural_voices.domain import tts_system

from tests.fake_tts_backend import FakeTTSBackend

_backend = FakeTTSBackend()


@pytest.fixture
def fresh_log(monkeypatch):
    """A MagicMock scoped to a single test — logHandler.log is a session-wide
    stub shared with every other test module."""
    fake_log = MagicMock()
    monkeypatch.setattr(voice_migration, "log", fake_log)
    return fake_log


def _write_voice(base_dir, key="en_US-amy-medium", payload=b"model"):
    """Lay down a downloaded voice the way voice_download.py does."""
    voice_dir = base_dir / "voices" / "piper" / key
    voice_dir.mkdir(parents=True)
    (voice_dir / f"{key}.onnx").write_bytes(payload)
    (voice_dir / "config.json").write_text("{}", encoding="utf-8")
    return voice_dir


class TestMigrateVoicesDirectory:
    def test_moves_the_old_directory_when_the_new_one_is_absent(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is True
        migrated = tmp_path / "dengjen" / "voices" / "piper" / "en_US-amy-medium"
        assert (migrated / "en_US-amy-medium.onnx").read_bytes() == b"model"
        assert not (tmp_path / "sonata").exists()

    def test_is_a_noop_when_there_is_nothing_to_migrate(self, tmp_path):
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is False
        assert not (tmp_path / "dengjen").exists()

    def test_ignores_a_file_named_like_the_old_directory(self, tmp_path):
        (tmp_path / "sonata").write_text("not a directory")
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is False
        assert not (tmp_path / "dengjen").exists()

    def test_logs_and_does_not_raise_when_the_move_fails(
        self, tmp_path, fresh_log, monkeypatch
    ):
        _write_voice(tmp_path / "sonata")

        def _in_use(src, dst):
            raise PermissionError("file in use")

        monkeypatch.setattr(voice_migration.os, "rename", _in_use)
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is False
        assert fresh_log.exception.call_count == 1
        assert str(tmp_path / "sonata") in fresh_log.exception.call_args[0][0]

    def test_stays_quiet_when_there_is_nothing_to_do(self, tmp_path, fresh_log):
        voice_migration.migrate_voices_directory(str(tmp_path))
        assert fresh_log.info.call_count == 0


class TestMigrateVoicesDirectoryRetry:
    """Regression tests for issue #83."""

    def test_migrates_when_the_new_tree_exists_but_holds_no_voices(self, tmp_path):
        (tmp_path / "dengjen" / "voices" / "piper").mkdir(parents=True)
        _write_voice(tmp_path / "sonata")
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is True
        migrated = tmp_path / "dengjen" / "voices" / "piper" / "en_US-amy-medium"
        assert (migrated / "en_US-amy-medium.onnx").read_bytes() == b"model"
        assert not (tmp_path / "sonata").exists()

    def test_leaves_voices_already_present_in_the_new_tree_untouched(self, tmp_path):
        new_voice = _write_voice(tmp_path / "dengjen", payload=b"newer model")
        _write_voice(tmp_path / "sonata")
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is False
        assert (new_voice / "en_US-amy-medium.onnx").read_bytes() == b"newer model"
        assert (tmp_path / "sonata" / "voices" / "piper").is_dir()

    def test_a_move_blocked_by_open_files_can_succeed_on_a_later_attempt(
        self, tmp_path, monkeypatch
    ):
        _write_voice(tmp_path / "sonata")

        with monkeypatch.context() as locked:

            def _in_use(src, dst):
                raise PermissionError("file in use")

            locked.setattr(voice_migration.os, "rename", _in_use)
            assert voice_migration.migrate_voices_directory(str(tmp_path)) is False

        (tmp_path / "dengjen" / "voices" / "piper").mkdir(parents=True)

        assert voice_migration.migrate_voices_directory(str(tmp_path)) is True
        migrated = tmp_path / "dengjen" / "voices" / "piper" / "en_US-amy-medium"
        assert (migrated / "en_US-amy-medium.onnx").read_bytes() == b"model"

    def test_a_partly_migrated_tree_is_not_re_migrated_over(self, tmp_path):
        _write_voice(tmp_path / "dengjen", key="en_GB-alan-medium")
        _write_voice(tmp_path / "sonata", key="en_US-amy-medium")
        assert voice_migration.migrate_voices_directory(str(tmp_path)) is False
        assert not (
            tmp_path / "dengjen" / "voices" / "piper" / "en_US-amy-medium"
        ).exists()


class _FakeAddon:
    def __init__(self, name, pending_remove=False):
        self.name = name
        self.isPendingRemove = pending_remove


class TestCoexistenceWithTheOldAddon:
    """Moving the folder would break a Sonata install that still works, so
    while the old add-on is present the voices are left alone and the voice
    manager copies them on request instead."""

    def test_does_not_move_anything_while_the_old_addon_is_installed(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        assert (
            voice_migration.migrate_voices_directory(
                str(tmp_path), addons=[_FakeAddon("sonata_neural_voices")]
            )
            is False
        )
        assert (tmp_path / "sonata" / "voices" / "piper" / "en_US-amy-medium").is_dir()
        assert not (tmp_path / "dengjen").exists()

    def test_moves_once_the_old_addon_is_pending_removal(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        assert (
            voice_migration.migrate_voices_directory(
                str(tmp_path),
                addons=[_FakeAddon("sonata_neural_voices", pending_remove=True)],
            )
            is True
        )

    def test_an_unrelated_addon_does_not_block_the_move(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        assert (
            voice_migration.migrate_voices_directory(
                str(tmp_path), addons=[_FakeAddon("some_other_addon")]
            )
            is True
        )


class TestImportableVoiceKeys:
    def test_lists_voices_only_present_in_the_old_tree(self, tmp_path):
        _write_voice(tmp_path / "sonata", key="en_US-amy-medium")
        _write_voice(tmp_path / "sonata", key="en_GB-alan-medium")
        _write_voice(tmp_path / "dengjen", key="en_GB-alan-medium")
        assert voice_migration.importable_voice_keys(str(tmp_path)) == [
            "en_US-amy-medium"
        ]

    def test_is_empty_when_there_is_no_old_tree(self, tmp_path):
        assert voice_migration.importable_voice_keys(str(tmp_path)) == []

    def test_is_empty_when_everything_is_already_imported(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        _write_voice(tmp_path / "dengjen")
        assert voice_migration.importable_voice_keys(str(tmp_path)) == []


class TestCopyVoicesFromOldDir:
    def test_copies_and_leaves_the_originals_in_place(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        assert voice_migration.copy_voices_from_old_dir(str(tmp_path)) == [
            "en_US-amy-medium"
        ]
        original = tmp_path / "sonata" / "voices" / "piper" / "en_US-amy-medium"
        copy = tmp_path / "dengjen" / "voices" / "piper" / "en_US-amy-medium"
        assert (original / "en_US-amy-medium.onnx").read_bytes() == b"model"
        assert (copy / "en_US-amy-medium.onnx").read_bytes() == b"model"

    def test_does_not_overwrite_a_voice_already_imported(self, tmp_path):
        _write_voice(tmp_path / "sonata")
        _write_voice(tmp_path / "dengjen", payload=b"newer model")
        assert voice_migration.copy_voices_from_old_dir(str(tmp_path)) == []
        copy = tmp_path / "dengjen" / "voices" / "piper" / "en_US-amy-medium"
        assert (copy / "en_US-amy-medium.onnx").read_bytes() == b"newer model"

    def test_is_a_noop_when_there_is_no_old_tree(self, tmp_path):
        assert voice_migration.copy_voices_from_old_dir(str(tmp_path)) == []


class TestMigrationRunsOnVoiceEnumeration:
    """The trigger issue #83 was missing: onInstall was the only caller, so a
    move that failed once was never retried."""

    @pytest.fixture
    def config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            voice_migration.globalVars.appArgs, "configPath", str(tmp_path)
        )
        monkeypatch.setattr(
            tts_system,
            "DENGJEN_VOICES_DIR",
            str(tmp_path / "dengjen" / "voices" / "piper"),
        )
        return tmp_path

    def test_enumerating_voices_migrates_the_old_directory(self, config_dir):
        _write_voice(config_dir / "sonata")
        voices = (
            tts_system.DengjenTextToSpeechSystem.load_piper_voices_from_nvda_config_dir(
                _backend
            )
        )
        assert [v.key for v in voices] == ["en_US-amy-medium"]
        assert not (config_dir / "sonata").exists()

    def test_enumerating_voices_after_a_failed_move_retries_it(
        self, config_dir, monkeypatch
    ):
        _write_voice(config_dir / "sonata")

        with monkeypatch.context() as locked:

            def _in_use(src, dst):
                raise PermissionError("file in use")

            locked.setattr(voice_migration.os, "rename", _in_use)
            assert (
                tts_system.DengjenTextToSpeechSystem.load_piper_voices_from_nvda_config_dir(
                    _backend
                )
                == []
            )
            assert os.path.isdir(config_dir / "dengjen" / "voices" / "piper")

        voices = (
            tts_system.DengjenTextToSpeechSystem.load_piper_voices_from_nvda_config_dir(
                _backend
            )
        )
        assert [v.key for v in voices] == ["en_US-amy-medium"]
