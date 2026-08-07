# coding: utf-8
"""Tests for the 4.0.0 upgrade path in installTasks.py.

The real upgrade runs inside NVDA on Windows. These exercise the decision
logic against a temporary directory and fake config objects; the NVDA-side
behaviour still needs an end-user check on the built artifact.
"""

import os

from tests.conftest import REPO_ROOT, load_module_from_path

install_tasks = load_module_from_path(
    "_install_migrations_under_test",
    os.path.join(REPO_ROOT, "addon", "installTasks.py"),
)


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


class _FakeSection(dict):
    """Stands in for NVDA's ConfigObj section, which has isSet()."""

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
