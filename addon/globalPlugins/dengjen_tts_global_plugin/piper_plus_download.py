"""Piper-Plus download/install: neural voices from ayutaz/piper-plus on HuggingFace.

Supports all 6 Piper-Plus languages (ja_JP, en_US, zh_CN, es_ES, fr_FR, pt_BR)
and all 7 published Piper-Plus voice models (5 multilingual 6-language models,
1 Japanese OpenJTalk model, and 1 English espeak model).
"""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import addonHandler
from logHandler import log

addonHandler.initTranslation()

from dengjen_neural_voices.const import DENGJEN_PIPER_PLUS_VOICES_DIR
from dengjen_neural_voices.domain import voice_metadata

from .download_infra import (
    BaseVoiceDownloader,
    VoiceInstallError,
    follow_redirects,
    hosting_url,
    stream_to_file,
)
from .voice_download import PiperVoiceLanguage, PiperVoiceQualityLevel

DEFAULT_PIPER_PLUS_DOWNLOAD_PREFIX = "https://huggingface.co"
_CONFIG_JSON_FILENAME = "config.json"
_MODEL_ONNX_FILENAME = "model.onnx"
_PHONEME_TYPE_MULTILINGUAL = "multilingual"
_UTF8 = "utf-8"
_HASH_CHUNK_SIZE = 65536

PIPER_PLUS_LANGUAGE_ID_MAP: dict[str, int] = {
    "ja": 0,
    "en": 1,
    "zh": 2,
    "es": 3,
    "fr": 4,
    "pt": 5,
}

PIPER_PLUS_LANGUAGES: tuple[PiperVoiceLanguage, ...] = (
    PiperVoiceLanguage(
        code="ja_JP",
        family="ja",
        region="JP",
        name_native="日本語",
        name_english="Japanese",
        country_english="Japan",
    ),
    PiperVoiceLanguage(
        code="en_US",
        family="en",
        region="US",
        name_native="English",
        name_english="English",
        country_english="United States",
    ),
    PiperVoiceLanguage(
        code="zh_CN",
        family="zh",
        region="CN",
        name_native="简体中文",
        name_english="Chinese",
        country_english="China",
    ),
    PiperVoiceLanguage(
        code="es_ES",
        family="es",
        region="ES",
        name_native="Español",
        name_english="Spanish",
        country_english="Spain",
    ),
    PiperVoiceLanguage(
        code="fr_FR",
        family="fr",
        region="FR",
        name_native="Français",
        name_english="French",
        country_english="France",
    ),
    PiperVoiceLanguage(
        code="pt_BR",
        family="pt",
        region="BR",
        name_native="Português",
        name_english="Portuguese",
        country_english="Brazil",
    ),
)

_LANGUAGE_BY_CODE: dict[str, PiperVoiceLanguage] = {
    lang.code: lang for lang in PIPER_PLUS_LANGUAGES
}
_ALL_SIX_LANGUAGE_CODES: tuple[str, ...] = tuple(
    lang.code for lang in PIPER_PLUS_LANGUAGES
)


@dataclass(frozen=True)
class PiperPlusModelSpec:
    """Immutable specification and integrity pins for an upstream Piper-Plus model."""

    model_id: str
    repo_id: str
    commit: str
    onnx_path: str
    onnx_sha256: str
    config_path: str
    config_sha256: str
    phoneme_type: str
    languages: tuple[str, ...]
    description: str
    quality: PiperVoiceQualityLevel = PiperVoiceQualityLevel.Medium


PIPER_PLUS_MODELS: tuple[PiperPlusModelSpec, ...] = (
    PiperPlusModelSpec(
        model_id="tsukuyomi_chan",
        repo_id="ayousanz/piper-plus-tsukuyomi-chan",
        commit="619ad26fcbd5635b3d70a27eac919f4c2ce892b1",
        onnx_path="tsukuyomi-chan-6lang-fp16.onnx",
        onnx_sha256="5289e9b6eaf21080803b7fe1c4dc85b5491d4c216121207a41df18dd5f68e5d7",
        config_path=_CONFIG_JSON_FILENAME,
        config_sha256="516058f405ec914140f34832a9d8bb5d8272ba62af9bc7ffb29349715a539780",
        phoneme_type=_PHONEME_TYPE_MULTILINGUAL,
        languages=_ALL_SIX_LANGUAGE_CODES,
        description="Piper-Plus Tsukuyomi-chan 6-language neural voice (FP16)",
    ),
    PiperPlusModelSpec(
        model_id="tsukuyomi_zs",
        repo_id="ayousanz/piper-plus-tsukuyomi-chan",
        commit="619ad26fcbd5635b3d70a27eac919f4c2ce892b1",
        onnx_path="releases/zs-v1/tsukuyomi.onnx",
        onnx_sha256="5fcef335c2bd69a4d2b5512e46d971427a653bf252097e2fb73618e7a584f331",
        config_path="releases/zs-v1/tsukuyomi.onnx.json",
        config_sha256="055a837f6b77294789f8600ec0d0d6183b128e99023dca20f20f7f662b881b8b",
        phoneme_type=_PHONEME_TYPE_MULTILINGUAL,
        languages=_ALL_SIX_LANGUAGE_CODES,
        description="Piper-Plus Tsukuyomi-chan zero-shot v1 neural voice",
    ),
    PiperPlusModelSpec(
        model_id="css10_ja_6lang",
        repo_id="ayousanz/piper-plus-css10-ja-6lang",
        commit="bd0d812d4db9182ecdb907ef074becf9e230c17f",
        onnx_path="css10-ja-6lang-fp16.onnx",
        onnx_sha256="5ebc51dbf897238523f3df0d6e0f6c93033bc5cda3f8602a8379ebe2a4738c42",
        config_path=_CONFIG_JSON_FILENAME,
        config_sha256="3c613dacf139349c20159433559b2e94e6364e9a340d95245f3de6006f453fcc",
        phoneme_type=_PHONEME_TYPE_MULTILINGUAL,
        languages=_ALL_SIX_LANGUAGE_CODES,
        description="Piper-Plus CSS10 Japanese 6-language neural voice (FP16)",
    ),
    PiperPlusModelSpec(
        model_id="mera_multilingual",
        repo_id="kizuna-intelligence/piper-plus-mera-multilingual",
        commit="d5ed57f04a1fd1cada7940ecd79a51d523b83462",
        onnx_path="mera-multilingual.onnx",
        onnx_sha256="97952c17fd60d47c4db2a6bf3903184df2054b6fa97396c971102bc60a9f135f",
        config_path=_CONFIG_JSON_FILENAME,
        config_sha256="26dfa6f0e82ad64c3334b0e34d765cca29ddd20f23df22ac33748fff0ea3e17f",
        phoneme_type=_PHONEME_TYPE_MULTILINGUAL,
        languages=_ALL_SIX_LANGUAGE_CODES,
        description="Piper-Plus Mera 6-language neural voice",
    ),
    PiperPlusModelSpec(
        model_id="piper_plus_base",
        repo_id="ayousanz/piper-plus-base",
        commit="3620ed788667cb76f08bd6cf2db8152c1f4c8bd1",
        onnx_path="releases/zs-v1/base.onnx",
        onnx_sha256="e9860701a941db02149c7cfbe19cfb578c235c5e25020f1f592131d9b3b30f84",
        config_path="releases/zs-v1/base.onnx.json",
        config_sha256="d085681edaa5029c54ea8329f3f23ed347ba46ca15cd80e766de9a6a643dafc0",
        phoneme_type=_PHONEME_TYPE_MULTILINGUAL,
        languages=_ALL_SIX_LANGUAGE_CODES,
        description="Piper-Plus Base 6-language foundation neural voice",
    ),
    PiperPlusModelSpec(
        model_id="css10_ja",
        repo_id="ayousanz/piper-css10-ja",
        commit="2546b28de5147f3085c403b68ea3924f64aaf220",
        onnx_path="css10_ja_full_evaluation/css10_ja_epoch299.onnx",
        onnx_sha256="fbcd0186e04e9eb9014c32d61892b687a9d218e679fb22ecc7819a686cdc2bea",
        config_path="css10_ja_full_evaluation/css10_ja_epoch299.onnx.json",
        config_sha256="349d405d093a41e5c043a9ee90f309daae02b09d7d5db3d8814259e5e1af0077",
        phoneme_type="openjtalk",
        languages=("ja_JP",),
        description="Piper-Plus CSS10 Japanese OpenJTalk neural voice",
    ),
    PiperPlusModelSpec(
        model_id="piper_ljspeech",
        repo_id="piper-plus/piper-ljspeech",
        commit="2b5d34bea0f69c616f0f2a4cbe42e367e967949f",
        onnx_path="my_ljspeech_piper_voice.onnx",
        onnx_sha256="b51b96a756e6514ff725b4c4aebf244a37dc985047c341b0348108c10e904674",
        config_path="my_ljspeech_piper_voice.onnx.json",
        config_sha256="ae4dae9f66fb325b548522a5f4dce2dcb13d319200e50097ab3a629258e86413",
        phoneme_type="espeak",
        languages=("en_US",),
        description="Piper-Plus LJSpeech English neural voice",
    ),
)


@dataclass
class PiperPlusVoice:
    """Language-specific voice entry backed by a `PiperPlusModelSpec`."""

    key: str
    name: str
    quality: PiperVoiceQualityLevel
    language: PiperVoiceLanguage
    spec: PiperPlusModelSpec
    language_id: int | None
    standard_variant_installed: bool = False


def voice_key_for(spec: PiperPlusModelSpec, lang_code: str) -> str:
    """Build the canonical `<lang>-<model_id>-<quality>` directory key."""
    return f"{lang_code}-{spec.model_id}-{spec.quality.value}"


def build_piper_plus_config(raw_config: dict, voice: PiperPlusVoice) -> dict:
    """Stamp per-language and Piper-Plus metadata onto a parsed model config."""
    config = dict(raw_config)
    lang = voice.language
    config["dataset"] = voice.name
    config["language"] = {
        "code": lang.code,
        "family": lang.family,
        "region": lang.region,
        "name_native": lang.name_native,
        "name_english": lang.name_english,
        "country_english": lang.country_english,
    }
    piper_plus_meta: dict[str, str | int] = {
        "repo_id": voice.spec.repo_id,
        "commit": voice.spec.commit,
        "model_id": voice.spec.model_id,
        "phoneme_type": voice.spec.phoneme_type,
        "language_code": lang.code,
        "language_family": lang.family,
    }
    if voice.language_id is not None:
        piper_plus_meta["language_id"] = voice.language_id
    config["piper_plus"] = piper_plus_meta
    return config


def _is_voice_installed_dir(voice_dir: Path) -> bool:
    """Return True when `voice_dir` has both `.onnx` model and `.onnx.json` config."""
    return (
        voice_dir.is_dir()
        and (voice_dir / f"{voice_dir.name}.onnx").is_file()
        and (voice_dir / f"{voice_dir.name}.onnx.json").is_file()
    )


def _installed_piper_plus_keys(voices_dir: Path | None = None) -> set[str]:
    """Return keys of Piper-Plus voices that have both model `.onnx` and `.onnx.json`."""
    root = Path(DENGJEN_PIPER_PLUS_VOICES_DIR) if voices_dir is None else voices_dir
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if _is_voice_installed_dir(d)}


def get_all_piper_plus_voices(voices_dir: Path | None = None) -> list[PiperPlusVoice]:
    """Expand all 7 Piper-Plus models across their supported languages."""
    installed_keys = _installed_piper_plus_keys(voices_dir)
    voices: list[PiperPlusVoice] = []
    for spec in PIPER_PLUS_MODELS:
        is_multilingual = spec.phoneme_type == _PHONEME_TYPE_MULTILINGUAL
        for lang_code in spec.languages:
            lang = _LANGUAGE_BY_CODE[lang_code]
            key = voice_key_for(spec, lang_code)
            voices.append(
                PiperPlusVoice(
                    key=key,
                    name=spec.model_id,
                    quality=spec.quality,
                    language=lang,
                    spec=spec,
                    language_id=(
                        PIPER_PLUS_LANGUAGE_ID_MAP[lang.family]
                        if is_multilingual
                        else None
                    ),
                    standard_variant_installed=key in installed_keys,
                )
            )
    return voices


def get_available_piper_plus_voices(
    voices_dir: Path | None = None,
) -> list[PiperPlusVoice]:
    """Return Piper-Plus language entries that are not yet installed."""
    return [
        v
        for v in get_all_piper_plus_voices(voices_dir)
        if not v.standard_variant_installed
    ]


def _parse_content_length(raw_header) -> int:
    """Parse an HTTP Content-Length header safely, returning 0 when absent/invalid."""
    try:
        size = int(raw_header)
    except (TypeError, ValueError):
        return 0
    return max(0, size)


def _sha256_file(path: Path) -> str:
    """Compute the lowercase hex SHA-256 digest of `path` in fixed-size chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_downloaded_file(
    target_path: Path, label: str, total_size: int, expected_sha256: str
) -> None:
    """Verify size (when given) and pinned SHA-256 digest, deleting bad downloads."""
    if total_size and target_path.stat().st_size != total_size:
        log.error(f"Downloaded size for {label} does not match the expected size")
        target_path.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded size for {label} does not match")
    actual_sha256 = _sha256_file(target_path)
    if actual_sha256 != expected_sha256:
        log.error(
            f"SHA-256 mismatch for {label}: expected {expected_sha256}, got {actual_sha256}"
        )
        target_path.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {label}")


def _download_to_file(
    spec: PiperPlusModelSpec,
    relative_path: str,
    expected_sha256: str,
    target_path: Path,
    progress_callback=None,
) -> None:
    """Stream a pinned model asset to `target_path` and verify its SHA-256 digest."""
    prefix = hosting_url(
        "piper_plus_download_prefix", DEFAULT_PIPER_PLUS_DOWNLOAD_PREFIX
    )
    url = f"{prefix}/{spec.repo_id}/resolve/{spec.commit}/{relative_path}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    label = f"{spec.repo_id}@{spec.commit}/{relative_path}"
    on_progress = (
        (lambda _percent: None) if progress_callback is None else progress_callback
    )
    with follow_redirects(url, label) as response:
        total_size = _parse_content_length(response.getheader("Content-Length", 0))
        stream_to_file(response, target_path, total_size, on_progress)
    _verify_downloaded_file(target_path, label, total_size, expected_sha256)


def _find_cached_sibling_onnx(
    spec: PiperPlusModelSpec, voices_dir: Path
) -> Path | None:
    """Locate a sibling language `.onnx` matching `spec.onnx_sha256`, if any."""
    if not voices_dir.is_dir():
        return None
    for lang_code in spec.languages:
        key = voice_key_for(spec, lang_code)
        onnx_file = voices_dir / key / f"{key}.onnx"
        if not onnx_file.is_file():
            continue
        try:
            if _sha256_file(onnx_file) == spec.onnx_sha256:
                return onnx_file
        except OSError:
            continue
    return None


def _link_or_copy_file(src: Path, dst: Path) -> None:
    """Atomically hard-link or copy `src` to `dst` via a same-directory temp file."""
    if src.exists() and dst.exists() and os.path.samefile(src, dst):
        return
    tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    try:
        try:
            os.link(src, tmp)
        except OSError:
            shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _write_text_atomic(dst: Path, content: str) -> None:
    """Atomically write UTF-8 `content` to `dst` via a same-directory temp file."""
    tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    try:
        tmp.write_text(content, encoding=_UTF8)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _cleanup_rollback_dirs(rollback_dirs: list[Path]) -> None:
    """Remove partially created voice directories, logging any cleanup failures."""
    for directory in rollback_dirs:
        if not directory.exists():
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            log.warning(
                f"Failed to remove partial Piper-Plus voice directory {directory}",
                exc_info=True,
            )


class PiperPlusVoiceDownloader(BaseVoiceDownloader):
    """Downloads a Piper-Plus model and installs either the selected language
    or all supported languages for that model."""

    def __init__(
        self,
        voice: PiperPlusVoice,
        success_callback,
        *,
        install_all_languages: bool = False,
    ):
        super().__init__(voice, success_callback)
        self.install_all_languages = install_all_languages

    def _target_voices(self, voices_dir: Path | None = None) -> list[PiperPlusVoice]:
        """Return either the single selected voice or all languages for its model."""
        if not self.install_all_languages:
            return [self.voice]
        return [
            v
            for v in get_all_piper_plus_voices(voices_dir)
            if v.spec.model_id == self.voice.spec.model_id
        ]

    def _progress_title(self):
        return _("Downloading Piper-Plus voice {voice}").format(voice=self.voice.key)

    def _success_message(self):
        return _(
            "Successfully downloaded Piper-Plus voice {voice}.\n"
            "To use this voice, you need to restart NVDA.\n"
            "Do you want to restart NVDA now?"
        ).format(voice=self.voice.key)

    def _failure_message(self):
        return _(
            "Cannot download Piper-Plus voice {voice}.\n"
            "Please check your connection and try again."
        ).format(voice=self.voice.key)

    def _file_progress_callback(self, file_index: int, total_files: int):
        """Map per-file percentage (0-100) onto the overall download progress bar."""

        def _on_chunk(percent: int) -> None:
            clamped = max(0, min(100, int(percent)))
            overall = int(((file_index - 1) * 100 + clamped) / total_files)
            self.update_progress(overall)

        return _on_chunk

    def _download_work(self):
        """Fetch and verify `.onnx` and config assets, reusing a verified sibling `.onnx`."""
        spec = self.voice.spec
        voices_dir = Path(DENGJEN_PIPER_PLUS_VOICES_DIR)
        cached_onnx = _find_cached_sibling_onnx(spec, voices_dir)
        files_to_download = []
        result = {}
        if cached_onnx is not None:
            result[_MODEL_ONNX_FILENAME] = cached_onnx
        else:
            files_to_download.append(
                (_MODEL_ONNX_FILENAME, spec.onnx_path, spec.onnx_sha256)
            )
        files_to_download.append(
            (_CONFIG_JSON_FILENAME, spec.config_path, spec.config_sha256)
        )
        total_files = len(files_to_download)
        download_dir = Path(self.download_dir)
        for files_done, (result_key, relative_path, expected_sha256) in enumerate(
            files_to_download, start=1
        ):
            self._report_progress(
                int((files_done - 1) / total_files * 100),
                _("Downloading file: {file}").format(file=relative_path),
            )
            target_path = download_dir / result_key
            _download_to_file(
                spec,
                relative_path,
                expected_sha256,
                target_path,
                progress_callback=self._file_progress_callback(files_done, total_files),
            )
            result[result_key] = target_path
            self.update_progress(int(files_done / total_files * 100))
        return result

    def _install(self, result):
        """Install target language directories atomically, rolling back on failure."""
        voices_root = Path(DENGJEN_PIPER_PLUS_VOICES_DIR)
        rollback_dirs: list[Path] = []
        try:
            onnx_source = Path(result[_MODEL_ONNX_FILENAME])
            raw_config = json.loads(
                Path(result[_CONFIG_JSON_FILENAME]).read_text(_UTF8)
            )
            if not isinstance(raw_config, dict):
                raise TypeError("Piper-Plus voice config must be a JSON object")

            shared_onnx = onnx_source
            for target_voice in self._target_voices(voices_root):
                install_dir = voices_root / target_voice.key
                if _is_voice_installed_dir(install_dir):
                    continue
                rollback_dirs.append(install_dir)
                installed_onnx = self._install_single_voice(
                    voices_root, target_voice, shared_onnx, raw_config
                )
                shared_onnx = installed_onnx
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _cleanup_rollback_dirs(rollback_dirs)
            log.exception("Failed to install the Piper-Plus voice", exc_info=True)
            raise VoiceInstallError from exc

    @staticmethod
    def _install_single_voice(
        voices_root: Path,
        target_voice: PiperPlusVoice,
        onnx_source: Path,
        raw_config: dict,
    ) -> Path:
        """Write `.onnx`, sidecar metadata, and `.onnx.json` for a single language."""
        install_dir = voices_root / target_voice.key
        install_dir.mkdir(parents=True, exist_ok=True)
        dst_onnx = install_dir / f"{target_voice.key}.onnx"
        _link_or_copy_file(onnx_source, dst_onnx)
        voice_metadata.write(
            install_dir,
            voice_metadata.VoiceMetadata(
                model_type="piper-plus",
                name=target_voice.name,
                language=target_voice.language.code,
                description=target_voice.spec.description,
            ),
        )
        config_data = build_piper_plus_config(raw_config, target_voice)
        _write_text_atomic(
            install_dir / f"{target_voice.key}.onnx.json",
            json.dumps(config_data, ensure_ascii=False, indent=2),
        )
        return dst_onnx
