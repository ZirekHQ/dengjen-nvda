"""Driver hot-path benchmark.

Usage: python -m benchmarks.driver_bench <repo_root> --out result.json [--repeats N]

Run from the head checkout after `python vendor_libs.py fetch`; <repo_root> picks
which tree's addon code is measured. The output maps each case id to
{"median_ms": float, "audio_ms": float?} or {"unavailable": str}.
"""

import argparse
import asyncio
import contextlib
import importlib
import itertools
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
import types
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPEATS = 15
CHUNK_MS = 100
SAMPLE_RATES = (16000, 22050, 24000)
CACHE_ENTRY_BYTES = 4096
PACKAGE = "dengjen_neural_voices"


@dataclass(frozen=True)
class Case:
    case_id: str
    make: Callable
    audio_ms: float | None = None


def median_ms(fn, repeats):
    """Median over `repeats` calls after one discarded warm-up call.

    `fn` returns its own elapsed milliseconds, or None to be timed by wall clock.
    """
    fn()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        reported = fn()
        wall_ms = (time.perf_counter() - start) * 1000
        samples.append(wall_ms if reported is None else reported)
    return statistics.median(samples)


def _close_case_fn(fn):
    close = getattr(fn, "close", None)
    if not callable(close):
        return None
    try:
        close()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def run_case(case, target, repeats):
    """Execute `case` for `repeats` timed iterations and ensure teardown runs."""
    fn = None
    entry = None
    run_err = None
    try:
        fn = case.make(target)
        entry = {"median_ms": median_ms(fn, repeats)}
    except Exception as exc:
        run_err = f"{type(exc).__name__}: {exc}"
    finally:
        close_err = _close_case_fn(fn)
    if run_err and close_err:
        return {"unavailable": f"{run_err}; cleanup failed ({close_err})"}
    if run_err or close_err:
        return {"unavailable": run_err or close_err}
    return {**entry, "audio_ms": case.audio_ms} if case.audio_ms else entry


def run_cases(cases, target, repeats):
    return {case.case_id: run_case(case, target, repeats) for case in cases}


class Target:
    def __init__(self, pkg_dir, load_from_path):
        self._pkg_dir = pkg_dir
        self._load_from_path = load_from_path
        self._driver = None

    def module(self, name):
        return importlib.import_module(f"{PACKAGE}.{name}")

    def driver(self):
        if self._driver is None:
            self._driver = self._load_from_path(
                f"{PACKAGE}.adapters.nvda.synth_driver",
                os.path.join(self._pkg_dir, "adapters", "nvda", "synth_driver.py"),
                f"{PACKAGE}.adapters.nvda",
            )
        return self._driver


def _repoint_package(pkg_dir):
    for name in [n for n in sys.modules if n.startswith(f"{PACKAGE}.")]:
        del sys.modules[name]
    package = sys.modules[PACKAGE]
    package.__path__ = [pkg_dir]
    # Stale attributes would shadow the submodules imported from the new tree.
    for stale in ("domain", "DengjenTextToSpeechSystem", "DENGJEN_VOICES_DIR"):
        package.__dict__.pop(stale, None)
    return package


def load_target(root):
    import vendor_libs
    from tests.nvda_stubs import install, load_module_from_path

    vendor_libs.require_fetched()
    install(stub_wx=True)
    pkg_dir = os.path.join(os.path.abspath(root), "addon", "synthDrivers", PACKAGE)
    package = _repoint_package(pkg_dir)
    package.aio = load_module_from_path(
        f"{PACKAGE}.aio", os.path.join(pkg_dir, "aio.py"), PACKAGE
    )
    return Target(pkg_dir, load_module_from_path)


def pcm_chunk(rate, ms=CHUNK_MS):
    count = rate * ms // 1000
    return array("h", (int(8000 * math.sin(i / 7)) for i in range(count))).tobytes()


def _processor_make(rate, spatial, normalize, night):
    chunk = pcm_chunk(rate)

    def make(target):
        cls = target.module("domain.audio_processing").AudioStreamProcessor

        def run():
            cls(
                normalize=normalize, night_mode=night, spatial_audio=spatial
            ).process_chunk(chunk)

        return run

    return make


def processor_cases():
    matrix = itertools.product(
        SAMPLE_RATES, (False, True), (False, True), (False, True)
    )
    return [
        Case(
            f"process_chunk/{rate}/{'spatial' if spatial else 'mono'}"
            f"/norm={int(norm)}/night={int(night)}",
            _processor_make(rate, spatial, norm, night),
            CHUNK_MS,
        )
        for rate, spatial, norm, night in matrix
    ]


def _timed_by_harness(fn, *args):
    def run():
        fn(*args)

    return run


def _cache_make(op):
    args = ("hello", "voice", None, None, None)
    chunks = [b"\x01" * CACHE_ENTRY_BYTES]

    def make(target):
        cache = target.module("domain.phrase_cache").PhraseCache()
        if op == "get_hit":
            cache.put(*args, False, False, chunks)
        if op == "put":
            return _timed_by_harness(cache.put, *args, False, False, chunks)
        return _timed_by_harness(cache.get, *args)

    return make


def cache_cases():
    return [
        Case(f"phrase_cache/{op}", _cache_make(op))
        for op in ("get_miss", "get_hit", "put")
    ]


class _TimedPlayer:
    def __init__(self):
        self.first_feed = None

    def feed(self, data):
        if self.first_feed is None:
            self.first_feed = time.perf_counter()

    def sync(self):
        pass


def _fake_synthesis_task(chunk):
    async def generate_audio():
        for _ in range(3):
            await asyncio.sleep(0)
            yield chunk

    voice = types.SimpleNamespace(key="bench", speaker=None)
    options = types.SimpleNamespace(
        voice=voice, rate=None, volume=None, pitch=None, sentence_silence_ms=None
    )
    return types.SimpleNamespace(
        text="hello", speech_options=options, generate_audio=generate_audio
    )


def _make_speak(target, task, spatial):
    driver, aio = target.driver(), target.module("aio")

    @aio.asyncio_coroutine_to_concurrent_future
    async def speak():
        driver.phrase_cache.clear()
        player = _TimedPlayer()
        speech = driver.SpeechTask(
            task, player, normalize=True, night_mode=True, spatial_audio=spatial
        )
        start = time.perf_counter()
        await speech()
        return (player.first_feed - start) * 1000

    return lambda: speak().result(timeout=10)


def _first_audio_make(rate, spatial):
    task = _fake_synthesis_task(pcm_chunk(rate))
    return lambda target: _make_speak(target, task, spatial)


def first_audio_cases():
    return [
        Case(
            f"first_audio/{rate}/{'spatial' if spatial else 'mono'}",
            _first_audio_make(rate, spatial),
        )
        for rate, spatial in itertools.product(SAMPLE_RATES, (False, True))
    ]


_MISSING = object()
_GRPC_GLOBAL_ATTRS = ("appDir", "DENGJEN_GRPC_SERVER_PORT", "GRPC_SERVER_PROCESS")
_GRPC_PATCHED_ATTRS = (
    "_vcruntime_missing",
    "_reap_stale_grpc_servers",
    "DENGJEN_VOICES_BASE_DIR",
    "subprocess",
    "grpc",
    "DengjenGrpcStub",
)


def _restore_attrs(obj, saved):
    for name, value in saved.items():
        if value is _MISSING:
            vars(obj).pop(name, None)
        else:
            setattr(obj, name, value)


class _FakeGrpcChannel:
    """No-op async gRPC channel for add-on overhead benchmarks."""

    async def close(self):
        pass


class _FakeGrpcService:
    """In-process stub gRPC service yielding synthetic PCM chunks."""

    chunks_per_utterance = 3

    def __init__(self, chunk):
        self._chunk = chunk
        self.version_checks = 0
        self.utterances = 0
        self.chunks_yielded = 0

    async def GetDengjenVersion(self, _request):
        self.version_checks += 1
        return types.SimpleNamespace(version="bench")

    async def SynthesizeUtterance(self, _request):
        self.utterances += 1
        for _ in range(self.chunks_per_utterance):
            await asyncio.sleep(0)
            self.chunks_yielded += 1
            yield types.SimpleNamespace(audio_bytes=self._chunk)


def _fake_grpc_popen(**kwargs):
    """Write the port-handshake banner immediately and return a stub process."""
    stdout = kwargs.get("stdout")
    if hasattr(stdout, "write"):
        stdout.write(b"DENGJEN_GRPC_LISTENING port=50051\n")
        stdout.flush()
    return types.SimpleNamespace(
        poll=lambda: None,
        kill=lambda: None,
        terminate=lambda: None,
        wait=lambda timeout=None: 0,
    )


def _reset_grpc_state(grpc_mod):
    """Close any open server log handle and clear module-level gRPC state."""
    handle = grpc_mod.SERVER_LOG_HANDLE
    grpc_mod.SERVER_LOG_HANDLE = None
    try:
        if handle is not None:
            handle.close()
    finally:
        grpc_mod._clear_saved_server_state()
        grpc_mod.GRPC_SERVER_PROCESS = None
        grpc_mod.DENGJEN_GRPC_SERVER_PORT = None
        grpc_mod.CHANNEL = None
        grpc_mod.CHANNEL_PORT = None
        grpc_mod.DENGJEN_GRPC_SERVICE = None


@contextlib.contextmanager
def _patched_grpc(target):
    """Patch `adapters.dengjen_grpc` with in-process fakes and restore on exit.

    Measures add-on Python/asyncio glue only (no OS process spawn or wire I/O)
    and keeps fake channel wiring off the shared `sys.modules["grpc"]` module.
    """
    grpc_mod = target.module("adapters.dengjen_grpc")
    saved_attrs = {name: getattr(grpc_mod, name) for name in _GRPC_PATCHED_ATTRS}
    global_vars = grpc_mod.globalVars
    saved_globals = {
        name: getattr(global_vars, name, _MISSING) for name in _GRPC_GLOBAL_ATTRS
    }
    service = _FakeGrpcService(pcm_chunk(22050))
    with tempfile.TemporaryDirectory(prefix="dengjen-bench-") as voices_dir:
        try:
            global_vars.appDir = ""
            grpc_mod._vcruntime_missing = lambda: False
            grpc_mod._reap_stale_grpc_servers = lambda _exe: None
            grpc_mod.DENGJEN_VOICES_BASE_DIR = voices_dir
            grpc_mod.subprocess = types.SimpleNamespace(
                Popen=_fake_grpc_popen,
                STDOUT=subprocess.STDOUT,
                TimeoutExpired=subprocess.TimeoutExpired,
                DETACHED_PROCESS=0,
                CREATE_NEW_PROCESS_GROUP=0,
                ABOVE_NORMAL_PRIORITY_CLASS=0,
            )
            grpc_mod.grpc = types.SimpleNamespace(
                aio=types.SimpleNamespace(
                    insecure_channel=lambda _target: _FakeGrpcChannel()
                )
            )
            grpc_mod.DengjenGrpcStub = lambda _channel: service
            yield grpc_mod, service
        finally:
            try:
                _reset_grpc_state(grpc_mod)
            finally:
                for name, value in saved_attrs.items():
                    setattr(grpc_mod, name, value)
                _restore_attrs(global_vars, saved_globals)


def _enter_patched_grpc(target):
    """Enter `_patched_grpc` on an ExitStack so `run_case` can close it cleanly."""
    stack = contextlib.ExitStack()
    try:
        grpc_mod, service = stack.enter_context(_patched_grpc(target))
    except BaseException:
        stack.close()
        raise
    return stack, grpc_mod, service


def _grpc_startup_make(target):
    """Build the add-on gRPC startup benchmark (`initialize` + `check_version`).

    Uses a stub `Popen`, channel, and service, so timings reflect Python adapter
    initialization, log-port parsing, and version-check glue rather than child
    process creation or socket transport.
    """
    stack, grpc_mod, service = _enter_patched_grpc(target)
    backend = grpc_mod.DengjenGrpcBackend()

    def run():
        _reset_grpc_state(grpc_mod)
        start = time.perf_counter()
        backend.initialize()
        backend.check_version()
        return (time.perf_counter() - start) * 1000

    run.close = stack.close
    run.service = service
    return run


def _grpc_first_audio_make(target):
    """Build the add-on gRPC time-to-first-audio benchmark against an in-process stub.

    Measures the Python/asyncio path from `SpeechTask` through `SpeechProvider`
    and `DengjenGrpcBackend.synthesize` to the first player feed, excluding real
    engine inference and wire transport.
    """
    stack, grpc_mod, service = _enter_patched_grpc(target)
    try:
        _reset_grpc_state(grpc_mod)
        backend = grpc_mod.DengjenGrpcBackend()
        backend.initialize()
        tts = target.module("domain.tts_system")
        voice = tts.DengjenVoice(
            key="bench",
            name="bench",
            language="en_US",
            description="bench",
            location="",
            backend=backend,
            remote_id="bench",
        )
        voice.is_multi_speaker = False
        task = tts.SpeechProvider("hello", tts.SpeechOptions(voice=voice))
        speak_fn = _make_speak(target, task, False)
    except BaseException:
        stack.close()
        raise

    def run():
        return speak_fn()

    run.close = stack.close
    run.service = service
    return run


def grpc_cases():
    """Return add-on gRPC glue benchmark cases (`grpc/startup`, `grpc/first_audio`)."""
    return [
        Case("grpc/startup", _grpc_startup_make),
        Case("grpc/first_audio", _grpc_first_audio_make),
    ]


def all_cases():
    """Return the complete driver benchmark suite."""
    return processor_cases() + cache_cases() + first_audio_cases() + grpc_cases()


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="repository root whose addon code is measured")
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    target = load_target(args.root)
    try:
        results = run_cases(all_cases(), target, args.repeats)
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    finally:
        target.module("aio").terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
