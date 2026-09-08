"""Kokoro-82M download/install: the second ModelCatalog implementation.

Unlike Piper (many independent per-voice files, browsed and downloaded one
at a time), Kokoro is one shared onnx model + one shared vocab + 54 small
per-preset voice-embedding files, installed as a single unit. Presets are
selected afterwards via NVDA's existing multi-speaker "Speaker" setting --
see domain/tts_system.py's DengjenVoice.speaker.

Source: onnx-community/Kokoro-82M-v1.0-ONNX on HuggingFace (Apache-2.0,
mirroring hexgrad/Kokoro-82M). File paths and the voice-embedding byte
layout (510 tokens x 256 dims x 4 bytes = 522240 bytes/file) are verified
against zirekhq/dengjen-tts's crates/dengjen/models/kokoro/src/{config,
voice_style}.rs, which is what actually loads this config.json.
"""

import json
import shutil
from pathlib import Path

import addonHandler
from logHandler import log

addonHandler.initTranslation()

from dengjen_neural_voices.const import DENGJEN_KOKORO_VOICES_DIR
from dengjen_neural_voices.domain import voice_metadata

from .voice_download import (
    _BaseVoiceDownloader,
    _follow_redirects,
    _stream_to_file,
    _VoiceInstallError,
)

KOKORO_REPO_RESOLVE_URL = (
    "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
)
KOKORO_MODEL_FILE = (
    "onnx/model.onnx"  # full precision -- quantized variants crash dengjen-tts-grpc.exe
)
KOKORO_LOCAL_MODEL_FILENAME = "model.onnx"  # KOKORO_MODEL_FILE's name once downloaded
KOKORO_VOCAB_FILE = "tokenizer.json"
KOKORO_VOICE_KEY = "kokoro-multilingual"
KOKORO_SAMPLE_RATE = 24000

# Verified via the HuggingFace API's model-info siblings listing (54 files
# under voices/, one per preset). First letter = language (a=American
# English, b=British English, e=Spanish, f=French, h=Hindi, i=Italian,
# j=Japanese, p=Brazilian Portuguese, z=Mandarin); second = f/m for gender.
KOKORO_PRESET_NAMES = [
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "jf_alpha",
    "jf_gongitsune",
    "jf_nezumi",
    "jf_tebukuro",
    "jm_kumo",
    "pf_dora",
    "pm_alex",
    "pm_santa",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
]


def build_kokoro_config(preset_names):
    return {
        "model_type": "kokoro",
        "model_path": KOKORO_LOCAL_MODEL_FILENAME,
        "voices_dir": "voices",
        "vocab_path": KOKORO_VOCAB_FILE,
        "sample_rate": KOKORO_SAMPLE_RATE,
        "voices": list(preset_names),
    }


def _download_to_file(relative_path, target_path):
    """Streams straight to disk (never holds a whole asset in memory) -- the
    full-precision model alone is ~326MB, and 56 files held as bytes
    simultaneously would be material memory pressure inside NVDA."""
    url = f"{KOKORO_REPO_RESOLVE_URL}/{relative_path}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with _follow_redirects(url, relative_path) as response:
        total_size = int(response.getheader("Content-Length", 0))
        _stream_to_file(response, target_path, total_size, lambda _percent: None)


class KokoroVoiceDownloader(_BaseVoiceDownloader):
    """Downloads the shared model + vocab + every preset embedding in one
    install. `voice` is unused by the base class beyond `.key` (used in
    progress/success/failure message formatting)."""

    class _Descriptor:
        key = KOKORO_VOICE_KEY

    def __init__(self, success_callback):
        super().__init__(self._Descriptor(), success_callback)

    def _progress_title(self):
        return _("Downloading Kokoro multilingual voice")

    def _success_message(self):
        return _(
            "Successfully downloaded the Kokoro multilingual voice.\n"
            "To use this voice, you need to restart NVDA.\n"
            "Do you want to restart NVDA now?"
        )

    def _failure_message(self):
        return _(
            "Cannot download the Kokoro voice.\n"
            "Please check your connection and try again."
        )

    def _download_work(self):
        files_to_download = [
            (KOKORO_LOCAL_MODEL_FILENAME, KOKORO_MODEL_FILE),
            (KOKORO_VOCAB_FILE, KOKORO_VOCAB_FILE),
            *(
                (f"voices/{name}.bin", f"voices/{name}.bin")
                for name in KOKORO_PRESET_NAMES
            ),
        ]
        total_files = len(files_to_download)
        download_dir = Path(self.download_dir)
        result = {}
        for files_done, (result_key, relative_path) in enumerate(
            files_to_download, start=1
        ):
            self._report_progress(
                int((files_done - 1) / total_files * 100),
                _("Downloading file: {file}").format(file=relative_path),
            )
            target_path = download_dir / result_key
            _download_to_file(relative_path, target_path)
            result[result_key] = target_path
            self.update_progress(int(files_done / total_files * 100))
        return result

    def _install(self, result):
        install_dir = Path(DENGJEN_KOKORO_VOICES_DIR) / KOKORO_VOICE_KEY
        try:
            (install_dir / "voices").mkdir(parents=True, exist_ok=True)

            shutil.copy(
                result[KOKORO_LOCAL_MODEL_FILENAME],
                install_dir / KOKORO_LOCAL_MODEL_FILENAME,
            )
            shutil.copy(result[KOKORO_VOCAB_FILE], install_dir / KOKORO_VOCAB_FILE)
            for name in KOKORO_PRESET_NAMES:
                shutil.copy(
                    result[f"voices/{name}.bin"], install_dir / "voices" / f"{name}.bin"
                )

            # voice_metadata written before config.json: KokoroCatalog.is_installed()
            # checks only for config.json, so it must be the last thing that lands --
            # otherwise a metadata-write failure would leave a directory that looks
            # installed but that voice discovery can never load.
            voice_metadata.write(
                install_dir,
                voice_metadata.VoiceMetadata(
                    model_type="kokoro",
                    name="Kokoro Multilingual",
                    language="en",
                    description=(
                        "Kokoro-82M neural voice, 54 presets across multiple "
                        "languages -- pick one via the Speaker setting."
                    ),
                ),
            )
            (install_dir / "config.json").write_text(
                json.dumps(build_kokoro_config(KOKORO_PRESET_NAMES)), encoding="utf-8"
            )
        except OSError as exc:
            log.exception("Failed to install the Kokoro voice", exc_info=True)
            raise _VoiceInstallError from exc


class KokoroCatalog:
    model_type = "kokoro"

    def is_installed(self) -> bool:
        config_path = Path(DENGJEN_KOKORO_VOICES_DIR) / KOKORO_VOICE_KEY / "config.json"
        return config_path.exists()

    def install(self, success_callback) -> None:
        KokoroVoiceDownloader(success_callback).download()
