"""The addon-owned voice.json sidecar.

Decouples NVDA-facing voice identity (name/language/model_type) from each
`dengjen-tts` model backend's own config format, and from Piper's
`lang-name-quality` directory-name convention -- both of which are owned by
the engine/catalog, not by us. Voices installed before this module existed
have no sidecar; read_or_migrate() falls back to the legacy directory-name
parse `DengjenVoice.from_path` used to do inline, and writes the sidecar so
later reads skip the fallback.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

VOICE_METADATA_FILENAME = "voice.json"


@dataclass(frozen=True)
class VoiceMetadata:
    model_type: str
    name: str
    language: str
    description: str = ""


def write(voice_dir: Path, metadata: VoiceMetadata) -> None:
    (voice_dir / VOICE_METADATA_FILENAME).write_text(
        json.dumps(asdict(metadata)), encoding="utf-8"
    )


def _migrate_legacy_piper_directory_name(voice_dir: Path) -> VoiceMetadata:
    try:
        lang, name, _quality = voice_dir.name.split("-")
    except ValueError:
        raise ValueError(f"Invalid voice path: {voice_dir}")
    return VoiceMetadata(
        model_type="piper", name=name.replace("+RT", ""), language=lang
    )


def read_or_migrate(voice_dir: Path) -> VoiceMetadata:
    sidecar_path = voice_dir / VOICE_METADATA_FILENAME
    if sidecar_path.exists():
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        try:
            return VoiceMetadata(**data)
        except TypeError:
            pass  # wrong-shaped sidecar: fall through to the legacy-name migration below

    metadata = _migrate_legacy_piper_directory_name(voice_dir)
    try:
        write(voice_dir, metadata)
    except OSError:
        pass
    return metadata
