"""Driver hot-path benchmark.

Usage: python -m benchmarks.driver_bench <repo_root> --out result.json [--repeats N]

Run from the head checkout after `python vendor_libs.py fetch`; <repo_root> picks
which tree's addon code is measured. The output maps each case id to
{"median_ms": float, "audio_ms": float?} or {"unavailable": str}.
"""

import argparse
import asyncio
import importlib
import itertools
import json
import math
import os
import statistics
import sys
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


def run_case(case, target, repeats):
    try:
        entry = {"median_ms": median_ms(case.make(target), repeats)}
    except Exception as exc:
        return {"unavailable": f"{type(exc).__name__}: {exc}"}
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


def all_cases():
    return processor_cases() + cache_cases() + first_audio_cases()


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
