# coding: utf-8

import asyncio
import atexit
import ctypes
import os
import subprocess
import time
from pathlib import Path

import globalVars
from logHandler import log

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _vcruntime_missing():
    """Return True if vcruntime140_1.dll cannot be loaded.

    sonata-grpc.exe is built with MSVC and needs the Visual C++ 2015-2022
    Redistributable (x64). On fresh Windows installs without it, Popen
    succeeds but the child process exits immediately with a missing-DLL
    dialog the user never sees from inside NVDA; the addon then logs the
    misleading 'Connection refused' from the failing gRPC channel.

    Use ctypes.WinDLL to ask Windows directly — it respects the standard
    DLL search path, so this is more reliable than checking a fixed
    System32 location.
    """
    try:
        ctypes.WinDLL("vcruntime140_1.dll")
        return False
    except (OSError, AttributeError):
        return True


def _show_vcruntime_warning():
    """Defer a user-facing wx messageBox about the missing VC++ redistributable.

    Imports of wx and gui are local so this module stays importable from
    contexts (tests, headless tooling) where the NVDA GUI isn't available.
    """
    try:
        import wx
        import gui
        wx.CallAfter(
            gui.messageBox,
            (
                "Sonata Neural Voices could not start because the "
                "Microsoft Visual C++ 2015-2022 Redistributable (x64) "
                f"is not installed.\n\nDownload and install it from:\n{VC_REDIST_URL}\n\n"
                "Then restart NVDA."
            ),
            "Sonata: missing dependency",
            style=wx.ICON_ERROR,
            parent=gui.mainFrame,
        )
    except Exception:
        log.exception("Failed to show VC++ redistributable warning dialog", exc_info=True)

from ..const import DENGJEN_VOICES_BASE_DIR
from ..helpers import BIN_DIRECTORY, find_free_port, import_bundled_library


with import_bundled_library():
    import grpc
    from .. import aio
    from .grpc_protos.sonata_grpc_pb2_grpc import sonata_grpcStub
    from .grpc_protos import sonata_grpc_pb2 as msgs


SONATA_GRPC_SERVER_PORT = None
GRPC_SERVER_PROCESS = None
CHANNEL = None
SONATA_GRPC_SERVICE = None
SERVER_CHECK_TIMEOUT = 15
# Outer bound on the startup futures; must exceed SERVER_CHECK_TIMEOUT so the
# coroutine's own error surfaces instead of a bare future timeout.
STARTUP_TIMEOUT = SERVER_CHECK_TIMEOUT + 5
CALL_TIMEOUT = 10
CHANNEL_CLOSE_TIMEOUT = 5


def start_grpc_server():
    global GRPC_SERVER_PROCESS, SONATA_GRPC_SERVER_PORT
    if hasattr(globalVars, "SONATA_GRPC_SERVER_PORT"):
        SONATA_GRPC_SERVER_PORT = globalVars.SONATA_GRPC_SERVER_PORT
        GRPC_SERVER_PROCESS = globalVars.GRPC_SERVER_PROCESS
        return True
    if _vcruntime_missing():
        log.error(
            "Sonata GRPC server cannot start: vcruntime140_1.dll not found. "
            "The Microsoft Visual C++ 2015-2022 Redistributable (x64) is required. "
            f"Download and install it from {VC_REDIST_URL} then restart NVDA."
        )
        _show_vcruntime_warning()
        return False
    SONATA_GRPC_SERVER_PORT = find_free_port()
    grpc_server_exe = os.path.join(BIN_DIRECTORY, "sonata-grpc.exe")
    nvda_espeak_dir = os.path.join(globalVars.appDir, "synthDrivers")
    env = os.environ.copy()
    env.update({
        "SONATA_GRPC_SERVER_PORT": str(SONATA_GRPC_SERVER_PORT),
        "SONATA_ESPEAKNG_DATA_DIRECTORY": os.fspath(nvda_espeak_dir),
        "SONATA_GRPC": "info",
    })
    creationflags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.REALTIME_PRIORITY_CLASS
    )
    try:
        server_log_file = os.path.join(DENGJEN_VOICES_BASE_DIR, "logs", "sonata-grpc.log")
        Path(server_log_file).parent.mkdir(parents=True, exist_ok=True)
        server_stdout = open(server_log_file, "wb")
    except OSError:
        log.exception("Failed to open server log file for writing", exc_info=True)
        server_stdout = subprocess.DEVNULL
    try:
        GRPC_SERVER_PROCESS = subprocess.Popen(
            args=grpc_server_exe,
            cwd=os.fspath(BIN_DIRECTORY),
            env=env,
            creationflags=creationflags,
            stdout=server_stdout,
            stderr=subprocess.STDOUT,
        )
    except Exception:
        log.exception(
            "Failed to start Sonata GRPC server. The synth will not be available.",
            exc_info=True
        )
        return False
    globalVars.SONATA_GRPC_SERVER_PORT = SONATA_GRPC_SERVER_PORT
    globalVars.GRPC_SERVER_PROCESS = GRPC_SERVER_PROCESS
    return True


@aio.asyncio_coroutine_to_concurrent_future
async def initialize():
    global CHANNEL, SONATA_GRPC_SERVICE, SONATA_GRPC_SERVER_PORT
    start_grpc_server()
    if CHANNEL is not None:
        try:
            # grpc.aio binds a channel to the loop that created it, so a channel
            # outliving its loop has to be replaced rather than reused.
            channel_loop = getattr(CHANNEL, "_loop", None)
            if channel_loop is aio.ASYNCIO_EVENT_LOOP and aio.ASYNCIO_EVENT_LOOP.is_running():
                return
        except Exception:
            log.debug("Failed to inspect the existing GRPC channel", exc_info=True)
        try:
            await CHANNEL.close()
        except Exception:
            log.debug("Failed to close the stale GRPC channel", exc_info=True)
        CHANNEL = None
    port = SONATA_GRPC_SERVER_PORT
    CHANNEL = grpc.aio.insecure_channel(f"localhost:{port}")
    SONATA_GRPC_SERVICE = sonata_grpcStub(CHANNEL)


def close_channel():
    """Close the aio channel on the loop that owns it.

    Channel.close() is a coroutine whose internals walk the running loop's
    task set, so it cannot be driven from another thread or a stopped loop.
    """
    global CHANNEL
    if CHANNEL is None:
        return
    channel, CHANNEL = CHANNEL, None
    loop = aio.ASYNCIO_EVENT_LOOP
    if loop is None or not loop.is_running():
        log.debug("Discarding the GRPC channel: its event loop is gone")
        channel.close().close()
        return
    try:
        asyncio.run_coroutine_threadsafe(channel.close(), loop).result(
            timeout=CHANNEL_CLOSE_TIMEOUT
        )
    except Exception:
        log.debug("Failed to close the GRPC channel cleanly", exc_info=True)


@atexit.register
def terminate():
    global GRPC_SERVER_PROCESS, SONATA_GRPC_SERVER_PORT
    SONATA_GRPC_SERVER_PORT = None
    close_channel()
    aio.terminate()
    if GRPC_SERVER_PROCESS is not None:
        GRPC_SERVER_PROCESS.terminate()
        GRPC_SERVER_PROCESS = None


@aio.asyncio_coroutine_to_concurrent_future
async def check_grpc_server() -> str:
    async with asyncio.timeout(SERVER_CHECK_TIMEOUT):
        return await get_sonata_version()


async def get_sonata_version():
    resp = await SONATA_GRPC_SERVICE.GetSonataVersion(msgs.Empty())
    return resp.version


@aio.asyncio_coroutine_to_concurrent_future
async def load_voice(config_path):
    req = msgs.VoicePath(config_path=config_path)
    return await SONATA_GRPC_SERVICE.LoadVoice(req)


@aio.asyncio_coroutine_to_concurrent_future
async def get_synth_options(voice_id):
    req = msgs.VoiceIdentifier(voice_id=voice_id)
    return await SONATA_GRPC_SERVICE.GetSynthesisOptions(req)


@aio.asyncio_coroutine_to_concurrent_future
async def set_synth_options(
    voice_id, speaker=None, length_scale=None, noise_scale=None, noise_w=None
):
    req = msgs.VoiceSynthesisOptions(
        voice_id=voice_id,
        synthesis_options=msgs.SynthesisOptions(
            speaker=speaker,
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w=noise_w,
        ),
    )
    return await SONATA_GRPC_SERVICE.SetSynthesisOptions(req)


async def speak(
    voice_id, text, rate=None, volume=None, pitch=None, appended_silence_ms=None, streaming=False
):
    speech_args = None
    if any([rate, volume, pitch, appended_silence_ms]):
        speech_args = msgs.SpeechArgs(
            rate=rate,
            volume=volume,
            pitch=pitch,
            appended_silence_ms=appended_silence_ms,
        )
    utterance = msgs.Utterance(
        voice_id=voice_id,
        text=text,
        speech_args=speech_args,
    )
    if streaming:
        stream = SONATA_GRPC_SERVICE.SynthesizeUtteranceRealtime
    else:
        stream = SONATA_GRPC_SERVICE.SynthesizeUtterance
    async for ret in stream(utterance):
        yield ret


async def bench(n=10000):
    initialize()
    t0 = time.perf_counter()
    for _ in range(n):
        await get_sonata_version()
    return time.perf_counter() - t0
