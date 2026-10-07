"""
Tests for japanese_dictionary.py: decides whether the engine gets
DENGJEN_JA_DICT_DIR at spawn.
"""

from dengjen_neural_voices import japanese_dictionary


def _install(path):
    path.mkdir(parents=True)
    (path / "metadata.json").write_text("{}", encoding="utf-8")


class TestIsInstalled:
    def test_a_directory_with_metadata_is_installed(self, tmp_path):
        _install(tmp_path / "naist-jdic")

        assert japanese_dictionary.is_installed(tmp_path / "naist-jdic")

    def test_a_missing_directory_is_not_installed(self, tmp_path):
        assert not japanese_dictionary.is_installed(tmp_path / "naist-jdic")

    def test_a_directory_without_metadata_is_not_installed(self, tmp_path):
        (tmp_path / "naist-jdic").mkdir()

        assert not japanese_dictionary.is_installed(tmp_path / "naist-jdic")


class TestEngineEnvironment:
    def test_points_the_engine_at_an_installed_dictionary(self, tmp_path):
        _install(tmp_path / "naist-jdic")

        env = japanese_dictionary.engine_environment(tmp_path / "naist-jdic", {})

        assert env == {"DENGJEN_JA_DICT_DIR": str(tmp_path / "naist-jdic")}

    def test_sets_nothing_without_an_installed_dictionary(self, tmp_path):
        assert japanese_dictionary.engine_environment(tmp_path / "naist-jdic", {}) == {}

    def test_keeps_a_value_the_user_already_set(self, tmp_path):
        _install(tmp_path / "naist-jdic")
        existing = {"DENGJEN_JA_DICT_DIR": "D:/my-dictionary"}

        assert (
            japanese_dictionary.engine_environment(tmp_path / "naist-jdic", existing)
            == {}
        )
