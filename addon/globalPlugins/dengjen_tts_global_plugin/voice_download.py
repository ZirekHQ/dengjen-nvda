import json
import math
import os
import re
import shutil
import ssl
import tarfile
import urllib.parse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from fnmatch import fnmatch
from functools import lru_cache, partial
from hashlib import md5
from http.client import HTTPException

import addonHandler
import core
import gui
import wx
from languageHandler import normalizeLanguage
from logHandler import log

addonHandler.initTranslation()

from dengjen_neural_voices.domain import voice_metadata

from . import DENGJEN_VOICES_DIR, DengjenGrpcBackend, DengjenTextToSpeechSystem, helpers

with helpers.import_bundled_library():
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import mureq as request


PIPER_VOICE_LIST_URL = (
    "https://huggingface.co/rhasspy/piper-voices/raw/v1.0.0/voices.json"
)
PIPER_VOICE_DOWNLOAD_URL_PREFIX = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
)
PIPER_SAMPLES_URL_PREFIX = "https://rhasspy.github.io/piper-samples/samples"
PIPER_VOICES_JSON_LOCAL_CACHE = os.path.join(DENGJEN_VOICES_DIR, "piper-voices.json")
RT_VOICE_LIST_URL = (
    "https://huggingface.co/datasets/mush42/piper-rt/raw/main/voices.json"
)
RT_VOICE_DOWNLOAD_URL_PREFIX = (
    "https://huggingface.co/datasets/mush42/piper-rt/resolve/main"
)

VOICE_INFO_REGEX = re.compile(
    r"(?P<language>[a-z]+(_|-)?([a-z]+)?)(-|_)"
    r"(?P<name>[a-z0-9_]+(\+RT)?)(-|_)"
    r"(?P<quality>(high|medium|low|x-low|x_low))",
    re.IGNORECASE,
)
THREAD_POOL_EXECUTOR = ThreadPoolExecutor()
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
REDIRECT_LIMIT = 5
DOWNLOAD_CHUNK_SIZE = 4096
CACERT_PATH = os.path.join(helpers.LIB_DIRECTORY, "cacert.pem")


class PiperVoiceQualityLevel(Enum):
    XLow = "x_low"
    Low = "low"
    Medium = "medium"
    High = "high"

    def __str__(self):
        return " ".join(v.title() for v in self.value.split("_"))


class PiperVoiceFileType(Enum):
    Onnx = auto()
    Config = auto()
    ModelCard = auto()


@dataclass
class PiperVoiceFile:
    file_path: str
    size_in_bytes: int
    md5hash: str

    def __post_init__(self):
        self.name = os.path.split(self.file_path)[-1]
        self.download_url = f"{PIPER_VOICE_DOWNLOAD_URL_PREFIX}/{self.file_path}"

    @property
    def type(self):
        suffix = Path(self.file_path).suffix.lstrip(".")
        if suffix == "onnx":
            return PiperVoiceFileType.Onnx
        elif suffix == "json":
            return PiperVoiceFileType.Config
        elif suffix == "":
            return PiperVoiceFileType.ModelCard
        raise ValueError(f"Unknown file type: {suffix}")


@dataclass(eq=False)
class PiperVoiceLanguage:
    code: str
    family: str
    region: str
    name_native: str
    name_english: str
    country_english: str

    def __str__(self):
        return self.code.replace("_", "-")

    def __eq__(self, other):
        if isinstance(other, PiperVoiceLanguage):
            return self.code == other.code
        return NotImplemented

    def __hash__(self):
        return hash(self.code)

    @property
    def description(self):
        code = self.code.replace("_", "-")
        if "English" not in self.name_native:
            return f"{self.name_english} ({self.country_english}) , {code}, {self.name_native}"
        return f"{self.name_english} ({self.country_english}), {code}"


@dataclass
class PiperVoice:
    key: str
    name: str
    quality: PiperVoiceQualityLevel
    num_speakers: int
    speaker_id_map: dict[str, int]
    language: PiperVoiceLanguage
    files: list[PiperVoiceFile]
    has_rt_variant: bool = False
    standard_variant_installed: bool = False
    fast_variant_installed: bool = False

    @classmethod
    def from_list_of_dicts(cls, voice_data):
        retval = []

        for data in voice_data:
            file_list = []
            for path, finfo in data["files"].items():
                file_list.append(
                    PiperVoiceFile(
                        file_path=path,
                        size_in_bytes=finfo["size_bytes"],
                        md5hash=finfo["md5_digest"],
                    )
                )
            lang_info = data["language"]
            language = PiperVoiceLanguage(
                code=lang_info["code"],
                family=lang_info["family"],
                region=lang_info["region"],
                name_native=lang_info["name_native"],
                name_english=lang_info["name_english"],
                country_english=lang_info["country_english"],
            )
            retval.append(
                cls(
                    key=data["key"],
                    name=data["name"],
                    quality=PiperVoiceQualityLevel(data["quality"]),
                    num_speakers=data["num_speakers"],
                    speaker_id_map=data["speaker_id_map"],
                    language=language,
                    files=file_list,
                    has_rt_variant=data["has_rt_variant"],
                    standard_variant_installed=data["standard_variant_installed"],
                    fast_variant_installed=data["fast_variant_installed"],
                )
            )

        retval.sort(key=lambda v: v.language.family)
        return retval

    def get_preview_url(self, speaker_idx=0):
        lang_path = f"{self.language.family.lower()}/{self.language.code}"
        quality = self.quality.value.lower()
        return f"{PIPER_SAMPLES_URL_PREFIX}/{lang_path}/{self.name}/{quality}/speaker_{speaker_idx}.mp3"

    def get_rt_variant_download_url(self):
        if not self.has_rt_variant:
            raise ValueError(f"Voice `{self.key}` has no RT variant")
        ___, rt_voice_key = DengjenTextToSpeechSystem.get_voice_variants(self.key)
        return f"{RT_VOICE_DOWNLOAD_URL_PREFIX}/{rt_voice_key}.tar.gz"


@lru_cache(maxsize=1)
def _fallback_ssl_context():
    return ssl.create_default_context(cafile=CACERT_PATH)


def _is_os_trust_store_gap(exc):

    return isinstance(exc.__cause__, ssl.SSLCertVerificationError)


def _get_with_cert_fallback(url, **kwargs):
    try:
        return request.get(url, **kwargs)
    except HTTPException as e:
        if not _is_os_trust_store_gap(e):
            raise
        log.debug(
            "OS trust store missing a root CA; retrying with the vendored CA bundle",
            exc_info=True,
        )
        return request.get(url, ssl_context=_fallback_ssl_context(), **kwargs)


@contextmanager
def _yield_response_with_cert_fallback(method, url, headers=None, **kwargs):
    with ExitStack() as stack:
        try:
            response = stack.enter_context(
                request.yield_response(method, url, headers=headers, **kwargs)
            )
        except HTTPException as e:
            if not _is_os_trust_store_gap(e):
                raise
            log.debug(
                "OS trust store missing a root CA; retrying with the vendored CA bundle",
                exc_info=True,
            )
            response = stack.enter_context(
                request.yield_response(
                    method,
                    url,
                    headers=headers,
                    ssl_context=_fallback_ssl_context(),
                    **kwargs,
                )
            )
        yield response


@contextmanager
def _follow_redirects(url, label, headers=None):

    for _redirect in range(REDIRECT_LIMIT):
        with _yield_response_with_cert_fallback(
            "GET", url, headers=headers
        ) as response:
            if response.status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Redirect without Location header.")
                url = urllib.parse.urljoin(url, location)
                continue

            if response.status not in (200, 206):
                raise RuntimeError(
                    f"Download failed for {label} (status {response.status})"
                )

            content_type = response.getheader("Content-Type", "").lower()
            if "text/html" in content_type or "xml" in content_type:
                raise RuntimeError(
                    f"Wrong content-type while downloading {label}: {content_type}"
                )

            yield response
            return

    raise RuntimeError(f"Too many redirects while downloading {label}")


def _resumable_partial_size(target_file, expected_size):
    """Bytes of `target_file` already on disk that a Range request can resume from.

    Returns 0 (start fresh) when nothing exists yet, or when a known
    `expected_size` shows the leftover is stale/complete already.
    """
    if not os.path.exists(target_file):
        return 0
    existing_size = os.path.getsize(target_file)
    if expected_size and existing_size >= expected_size:
        return 0
    return existing_size


CONTENT_RANGE_TOTAL_REGEX = re.compile(r"bytes \d+-\d+/(\d+)")


def _archive_total_size(response, resume_offset):
    """The archive's full size, for a request that may itself be a resume.

    A 206 reports only the remaining bytes via Content-Length, so the total
    comes from Content-Range's `.../<total>` instead; a fresh 200 reports the
    full size directly.
    """
    if response.status == 206:
        match = CONTENT_RANGE_TOTAL_REGEX.match(response.getheader("Content-Range", ""))
        return int(match.group(1)) if match else resume_offset
    return int(response.getheader("Content-Length", 0))


def _stream_to_file(
    response, target_file, total_size, progress_callback, hasher=None, resume_offset=0
):
    """Streams `response` into `target_file`, resuming a prior partial download.

    A resume is only honored when the server actually answered with 206 —
    a 200 despite a Range request means it sent the full body from byte 0,
    so any partial bytes already on disk are discarded and hashed anew.
    """
    is_resuming = resume_offset > 0 and response.status == 206
    downloaded_til_now = resume_offset if is_resuming else 0
    if is_resuming and hasher is not None:
        with open(target_file, "rb") as existing:
            for chunk in iter(partial(existing.read, DOWNLOAD_CHUNK_SIZE), b""):
                hasher.update(chunk)
    with open(target_file, "ab" if is_resuming else "wb") as file_buffer:
        for chunk in iter(partial(response.read, DOWNLOAD_CHUNK_SIZE), b""):
            file_buffer.write(chunk)
            if hasher is not None:
                hasher.update(chunk)
            downloaded_til_now += len(chunk)
            if total_size > 0:
                progress_callback(math.floor((downloaded_til_now / total_size) * 100))


class _VoiceInstallError(Exception):
    """Raised by a downloader's `_install` hook to signal a failed install."""


class _BaseVoiceDownloader:
    def __init__(self, voice: PiperVoice, success_callback):
        self.voice = voice
        self.success_callback = success_callback
        # Stable across instances, so _resumable_partial_size can find a prior attempt's file here.
        self.download_dir = os.path.join(DENGJEN_VOICES_DIR, ".downloads", voice.key)
        os.makedirs(self.download_dir, exist_ok=True)
        self.progress_dialog = None

    def update_progress(self, progress):
        self._report_progress(
            progress,
            _("Downloaded: {progress}%").format(progress=progress),
        )

    def _report_progress(self, percent, message):
        # download_work runs on a worker thread (see download() below);
        # wx.ProgressDialog.Update() is not thread-safe, so every call must
        # be marshalled onto the GUI thread via wx.CallAfter.
        wx.CallAfter(self.progress_dialog.Update, percent, message)

    def download(self):
        self.progress_dialog = wx.ProgressDialog(
            title=self._progress_title(),
            message=_("Retrieving download information..."),
            parent=gui.mainFrame,
        )
        self.progress_dialog.CenterOnScreen()
        THREAD_POOL_EXECUTOR.submit(self._download_work).add_done_callback(
            partial(self._done_callback_wrapper, self.done_callback)
        )

    def done_callback(self, result):
        # Runs on the worker thread (a future's add_done_callback fires on
        # whichever thread completes it -- see download()). _install does
        # the actual disk I/O here rather than after the wx.CallAfter below,
        # so writing a large voice to disk doesn't block the wx event loop.
        has_error = isinstance(result, Exception)
        install_error = None
        if not has_error:
            self._report_progress(0, _("Installing voice"))
            try:
                self._install(result)
            except _VoiceInstallError as exc:
                has_error = True
                install_error = exc

        wx.CallAfter(self._on_download_complete, has_error, install_error, result)

    def _on_download_complete(self, has_error, install_error, result):
        self.progress_dialog.Hide()
        self.progress_dialog.Destroy()
        del self.progress_dialog

        if not has_error:
            shutil.rmtree(self.download_dir, ignore_errors=True)
            self.success_callback()
            retval = gui.messageBox(
                self._success_message(),
                _("Voice downloaded"),
                wx.YES_NO | wx.ICON_WARNING,
                parent=gui.mainFrame,
            )
            if retval == wx.YES:
                core.restart()
        else:
            gui.messageBox(
                self._failure_message(),
                _("Download failed"),
                style=wx.ICON_ERROR,
                parent=gui.mainFrame,
            )
            error = install_error if install_error is not None else result
            log.error(f"Failed to download voice.\nException: {error}", exc_info=error)

    @staticmethod
    def _done_callback_wrapper(done_callback, future):
        if done_callback is None:
            return
        try:
            result = future.result()
        except Exception as e:
            done_callback(e)
        else:
            done_callback(result)

    def _download_work(self):
        raise NotImplementedError

    def _install(self, result):
        raise NotImplementedError

    def _progress_title(self):
        raise NotImplementedError

    def _success_message(self):
        raise NotImplementedError

    def _failure_message(self):
        raise NotImplementedError


class PiperVoiceDownloader(_BaseVoiceDownloader):
    def _progress_title(self):

        return _("Downloading voice {voice}").format(voice=self.voice.key)

    def _success_message(self):

        return _(
            "Successfully downloaded voice  {voice}.\n"
            "To use this voice, you need to restart NVDA.\n"
            "Do you want to restart NVDA now?"
        ).format(voice=self.voice.key)

    def _failure_message(self):
        return _(
            "Cannot download voice {voice}.\nPlease check your connection and try again."
        ).format(voice=self.voice.key)

    def _download_work(self):
        return self.download_voice_files()

    def download_voice_files(self):
        retvals = []
        for file in self.voice.files:
            self._report_progress(
                0,
                _("Downloading file: {file}").format(file=file.name),
            )
            result = self._do_download_file(
                file, self.download_dir, self.update_progress
            )
            retvals.append(result)

        return retvals

    @classmethod
    def _do_download_file(cls, file, download_dir, progress_callback):
        target_file = os.path.join(download_dir, file.file_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(target_file), exist_ok=True)

        resume_offset = _resumable_partial_size(target_file, file.size_in_bytes)
        headers = {"Range": f"bytes={resume_offset}-"} if resume_offset else None

        hasher = md5(usedforsecurity=False)
        with _follow_redirects(
            file.download_url, file.file_path, headers=headers
        ) as response:
            _stream_to_file(
                response,
                target_file,
                file.size_in_bytes,
                progress_callback,
                hasher,
                resume_offset=resume_offset,
            )

        return (file, target_file, hasher.hexdigest())

    def _install(self, result):
        mismatched = [
            (file, target_file)
            for file, target_file, md5hash in result
            if file.md5hash != md5hash
        ]
        if mismatched:
            log.error(f"File hashes do not match: {[f.name for f, __ in mismatched]}")
            for __, target_file in mismatched:
                # Otherwise the next attempt would "resume" from corrupt bytes.
                Path(target_file).unlink(missing_ok=True)
            raise _VoiceInstallError

        voice_dir = Path(DENGJEN_VOICES_DIR).joinpath(self.voice.key)
        voice_dir.mkdir(parents=True, exist_ok=True)
        try:
            voice_metadata.write(
                voice_dir,
                voice_metadata.VoiceMetadata(
                    model_type="piper",
                    name=self.voice.name,
                    language=self.voice.language.code,
                ),
            )
        except OSError:
            log.exception("Failed to write voice.json sidecar", exc_info=True)
        copy_failed = False
        for file, src, __ in result:
            dst = os.path.join(voice_dir, file.name)
            try:
                shutil.copy(src, dst)
            except OSError:
                log.exception(f"Failed to copy file: {file}", exc_info=True)
                copy_failed = True
        if copy_failed:
            raise _VoiceInstallError


class PiperRTVoiceDownloader(_BaseVoiceDownloader):
    def __init__(self, voice: PiperVoice, success_callback):
        self.rt_download_url = voice.get_rt_variant_download_url()
        super().__init__(voice, success_callback)

    def _progress_title(self):

        return _("Downloading fast variant of the voice {voice}").format(
            voice=self.voice.key
        )

    def _success_message(self):

        return _(
            "Successfully downloaded fast variant of the voice  {voice}.\n"
            "To use this voice, you need to restart NVDA.\n"
            "Do you want to restart NVDA now?"
        ).format(voice=self.voice.key)

    def _failure_message(self):
        return _(
            "Cannot download fast variant of the voice {voice}.\nPlease check your connection and try again."
        ).format(voice=self.voice.key)

    def _download_work(self):
        return self.download_voice_archive()

    def download_voice_archive(self):
        voice_name = self.rt_download_url.split("/")[-1].strip()
        self._report_progress(
            0,
            _("Downloading file: {file}").format(file=voice_name),
        )
        result = self._do_download_archive(
            self.rt_download_url,
            voice_name,
            self.download_dir,
            self.update_progress,
        )
        return result

    @classmethod
    def _do_download_archive(
        cls, download_url, voice_name, download_dir, progress_callback
    ):
        target_file = os.path.join(download_dir, voice_name)
        resume_offset = _resumable_partial_size(target_file, expected_size=0)
        headers = {"Range": f"bytes={resume_offset}-"} if resume_offset else None

        with _follow_redirects(download_url, voice_name, headers=headers) as response:
            expected_size = _archive_total_size(response, resume_offset)
            _stream_to_file(
                response,
                target_file,
                expected_size,
                progress_callback,
                resume_offset=resume_offset,
            )

        return target_file, expected_size

    def _install(self, result):
        target_file, expected_size = result
        if expected_size and os.path.getsize(target_file) != expected_size:
            log.error("Downloaded archive size does not match the expected size")
            Path(target_file).unlink(missing_ok=True)
            raise _VoiceInstallError
        try:
            install_voice_from_tar_archive(target_file, DENGJEN_VOICES_DIR)
        except Exception:
            log.exception("Failed to extract voice archive", exc_info=True)
            # Otherwise a Range request on the next attempt would land past
            # EOF and get a 416 forever, since this archive has no known
            # expected_size to catch it as stale beforehand.
            Path(target_file).unlink(missing_ok=True)
            raise _VoiceInstallError


def _voice_key_from_filename(stem):
    """Derive a voice_key from a filename stem like 'en_US-lessac-medium'.

    Returns the voice_key or None if the stem doesn't match the expected
    <language>-<name>-<quality> form.
    """
    m = VOICE_INFO_REGEX.match(stem)
    if m is None:
        return None
    info = m.groupdict()
    return "-".join(
        [
            normalizeLanguage(info["language"]),
            info["name"].replace("-", "_"),
            info["quality"].replace("-", "_"),
        ]
    )


def _voice_key_from_config(config):
    """Derive a voice_key from a Piper voice config dict.

    Used as a fallback when the filename doesn't follow the
    <language>-<name>-<quality> convention. Modern Piper configs carry
    `language.code`, `dataset`, and `audio.quality` — enough to construct
    a unique key without relying on the filename.

    Raises ValueError if the config is missing any required field.
    """
    try:
        language = config["language"]["code"]
        dataset = config["dataset"]
        quality = config["audio"]["quality"]
    except (KeyError, TypeError):
        raise ValueError(
            "Voice config is missing required fields (language.code, dataset, "
            "audio.quality). The archive filename also didn't follow the "
            "<language>-<name>-<quality> convention. Either rename the .onnx "
            "file to follow that convention, or ensure the bundled config "
            "JSON carries those fields."
        )
    return "-".join(
        [
            normalizeLanguage(language),
            str(dataset).replace("-", "_"),
            str(quality).replace("-", "_"),
        ]
    )


def install_voice_from_tar_archive(tar_path, voices_dir):
    with tarfile.open(tar_path) as tar:
        filenames = {f.name: f for f in tar.getmembers()}
        onnx_files = list(filter(lambda pth: fnmatch(pth, "*.onnx"), filenames))
        config_files = list(filter(lambda pth: fnmatch(pth, "*.json"), filenames))
        if not (onnx_files and config_files):
            raise FileNotFoundError("Required files not found in archive")
        if len(onnx_files) == 1:
            voice_key = _voice_key_from_filename(Path(onnx_files[0]).stem)
        else:
            voice_key = _voice_key_from_filename(Path(tar_path).stem[:-4])
        if voice_key is None:
            config = json.loads(
                tar.extractfile(filenames[config_files[0]]).read().decode("utf-8")
            )
            voice_key = _voice_key_from_config(config)
        voice_folder_name = Path(voices_dir).joinpath(voice_key)

        resolved_voices_dir = Path(voices_dir).resolve()
        resolved_voice_folder = voice_folder_name.resolve()
        if (
            resolved_voice_folder != resolved_voices_dir
            and resolved_voices_dir not in resolved_voice_folder.parents
        ):
            raise ValueError(
                f"Voice key resolves outside the voices directory: {voice_key!r}"
            )
        voice_folder_name.mkdir(parents=True, exist_ok=True)
        voice_folder_name = os.fspath(voice_folder_name)
        files_to_extract = [*onnx_files, *config_files]
        if "MODEL_CARD" in filenames:
            files_to_extract.append("MODEL_CARD")
        for file in files_to_extract:
            tar.extract(
                filenames[file],
                path=voice_folder_name,
                set_attrs=False,
                filter="data",
            )
        # Written after extraction: config_files matches any *.json in the
        # archive, so a root-level voice.json in the archive would otherwise
        # overwrite this canonical sidecar instead of the other way around.
        lang, name, _quality = voice_key.split("-")
        try:
            voice_metadata.write(
                Path(voice_folder_name),
                voice_metadata.VoiceMetadata(
                    model_type="piper", name=name.replace("+RT", ""), language=lang
                ),
            )
        except OSError:
            log.exception("Failed to write voice.json sidecar", exc_info=True)
        return voice_key


def _select_not_installed_voices(voices):
    installed_voices = DengjenTextToSpeechSystem.load_piper_voices_from_nvda_config_dir(
        DengjenGrpcBackend()
    )
    installed_voice_keys = {voice.key for voice in installed_voices}
    not_installed = []
    for key, value in voices.items():
        std_key, rt_key = DengjenTextToSpeechSystem.get_voice_variants(key)
        value["standard_variant_installed"] = std_key in installed_voice_keys
        value["fast_variant_installed"] = rt_key in installed_voice_keys
        if value["standard_variant_installed"] and value["fast_variant_installed"]:
            continue
        if value["standard_variant_installed"] and not value["has_rt_variant"]:
            continue
        not_installed.append(value)
    return not_installed


def _get_voices_from_cache():
    """Return the not-installed voices from the on-disk cache, or None if unreadable."""
    try:
        with open(PIPER_VOICES_JSON_LOCAL_CACHE, "rb") as file:
            voices = json.load(file)
    except Exception:
        log.exception("Failed to get voices from local file", exc_info=True)
        return None
    return PiperVoice.from_list_of_dicts(_select_not_installed_voices(voices))


def _refresh_voices_cache():
    std_resp = _get_with_cert_fallback(PIPER_VOICE_LIST_URL)
    std_resp.raise_for_status()
    std_voices = std_resp.json()
    rt_resp = _get_with_cert_fallback(RT_VOICE_LIST_URL)
    rt_resp.raise_for_status()
    rt_voice_names = {vdata["base"] for vdata in rt_resp.json().values()}
    voice_list = {}
    for vname, vdata in std_voices.items():
        vdata["has_rt_variant"] = vname in rt_voice_names
        voice_list[vname] = vdata
    with open(PIPER_VOICES_JSON_LOCAL_CACHE, "w", encoding="utf-8") as file:
        json.dump(voice_list, file, ensure_ascii=False, indent=2)


def get_available_voices(force_online=False):
    if not force_online and os.path.exists(PIPER_VOICES_JSON_LOCAL_CACHE):
        cached_voices = _get_voices_from_cache()
        if cached_voices is not None:
            return cached_voices
    _refresh_voices_cache()
    voices = _get_voices_from_cache()
    if voices is None:
        raise RuntimeError("Failed to read the voice list cache that was just written")
    return voices
