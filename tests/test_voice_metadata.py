"""
Tests for domain/voice_metadata.py: the addon-owned voice.json sidecar that
decouples NVDA-facing voice identity from each engine backend's own config
format and from Piper's `lang-name-quality` directory-name convention.
"""

import json

import pytest
from dengjen_neural_voices.domain.voice_metadata import (
    VOICE_METADATA_FILENAME,
    VoiceMetadata,
    read_or_migrate,
    write,
)


class TestReadOrMigrate:
    def test_reads_existing_sidecar(self, tmp_path):
        voice_dir = tmp_path / "kokoro-multilingual"
        voice_dir.mkdir()
        (voice_dir / VOICE_METADATA_FILENAME).write_text(
            json.dumps(
                {
                    "model_type": "kokoro",
                    "name": "Kokoro Multilingual",
                    "language": "en",
                    "description": "54 presets across multiple languages",
                }
            ),
            encoding="utf-8",
        )

        metadata = read_or_migrate(voice_dir)

        assert metadata == VoiceMetadata(
            model_type="kokoro",
            name="Kokoro Multilingual",
            language="en",
            description="54 presets across multiple languages",
        )

    def test_migrates_legacy_piper_directory_name(self, tmp_path):
        voice_dir = tmp_path / "en_US-libritts-high"
        voice_dir.mkdir()

        metadata = read_or_migrate(voice_dir)

        assert metadata == VoiceMetadata(
            model_type="piper", name="libritts", language="en_US", description=""
        )

    def test_migration_self_heals_by_writing_the_sidecar(self, tmp_path):
        voice_dir = tmp_path / "en_US-libritts-high"
        voice_dir.mkdir()

        read_or_migrate(voice_dir)

        sidecar = json.loads((voice_dir / VOICE_METADATA_FILENAME).read_text())
        assert sidecar["model_type"] == "piper"
        assert sidecar["name"] == "libritts"

    def test_migration_self_heal_failure_does_not_raise(self, tmp_path, monkeypatch):
        voice_dir = tmp_path / "en_US-libritts-high"
        voice_dir.mkdir()

        def _raise(*_args, **_kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr("dengjen_neural_voices.domain.voice_metadata.write", _raise)

        metadata = read_or_migrate(voice_dir)

        assert metadata.name == "libritts"

    def test_falls_back_to_legacy_parse_on_wrong_shaped_sidecar(self, tmp_path):
        voice_dir = tmp_path / "en_US-libritts-high"
        voice_dir.mkdir()
        (voice_dir / VOICE_METADATA_FILENAME).write_text(
            json.dumps({"model_type": "piper", "unexpected_extra_key": "oops"}),
            encoding="utf-8",
        )

        metadata = read_or_migrate(voice_dir)

        assert metadata == VoiceMetadata(
            model_type="piper", name="libritts", language="en_US", description=""
        )

    def test_raises_on_directory_name_that_matches_neither_shape(self, tmp_path):
        voice_dir = tmp_path / "not-a-valid-voice-dir-name-at-all-here"
        voice_dir.mkdir()

        with pytest.raises(ValueError):
            read_or_migrate(voice_dir)


class TestWrite:
    def test_write_then_read_round_trips(self, tmp_path):
        voice_dir = tmp_path / "kokoro-multilingual"
        voice_dir.mkdir()
        metadata = VoiceMetadata(
            model_type="kokoro", name="Kokoro Multilingual", language="en"
        )

        write(voice_dir, metadata)

        assert read_or_migrate(voice_dir) == metadata
