"""ModelCatalog: the seam a `dengjen-tts` model backend implements so the
voice manager can check install state without hardcoding Piper's shape.

Piper's own browsing/preview/download UI (OnlinePiperVoicesPanel) predates
this protocol and isn't rebuilt on top of it -- PiperCatalog exists to prove
the protocol against a second, structurally different backend (Kokoro, see
kokoro_download.py), not to replace working UI.
"""

from pathlib import Path
from typing import Protocol

from dengjen_neural_voices.const import DENGJEN_VOICES_DIR


class ModelCatalog(Protocol):
    model_type: str

    def is_installed(self) -> bool: ...

    def install(self, success_callback) -> None: ...


class PiperCatalog:
    model_type = "piper"

    def is_installed(self) -> bool:
        voices_dir = Path(DENGJEN_VOICES_DIR)
        return voices_dir.is_dir() and any(voices_dir.iterdir())

    def install(self, success_callback) -> None:
        raise NotImplementedError(
            "Piper voices are installed per-voice via OnlinePiperVoicesPanel, "
            "not through ModelCatalog.install()"
        )


from .kokoro_download import KokoroCatalog

AVAILABLE_CATALOGS: tuple[ModelCatalog, ...] = (PiperCatalog(), KokoroCatalog())
