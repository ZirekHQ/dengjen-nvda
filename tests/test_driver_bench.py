import json
import os
import subprocess
import sys
import types

import pytest

from benchmarks import driver_bench
from benchmarks.driver_bench import Case
from tests.conftest import REPO_ROOT


def test_median_ms_uses_the_value_a_case_reports():
    assert driver_bench.median_ms(lambda: 5.0, repeats=3) == 5.0


def test_median_ms_falls_back_to_wall_time():
    assert driver_bench.median_ms(lambda: None, repeats=3) > 0


def test_median_ms_takes_the_median_not_the_mean():
    values = iter([1.0, 100.0, 2.0, 3.0])
    assert driver_bench.median_ms(lambda: next(values), repeats=3) == 3.0


def test_run_case_records_unavailable_when_setup_fails():
    def make(_target):
        raise ImportError("no phrase_cache")

    entry = driver_bench.run_case(Case("x", make), None, repeats=1)
    assert entry == {"unavailable": "ImportError: no phrase_cache"}


def test_run_case_records_unavailable_when_the_run_fails():
    def make(_target):
        def run():
            raise TypeError("unexpected keyword 'spatial_audio'")

        return run

    entry = driver_bench.run_case(Case("x", make), None, repeats=1)
    assert entry["unavailable"].startswith("TypeError")


def test_run_case_records_unavailable_when_cleanup_fails():
    def make(_target):
        def run():
            return 1.5

        def close():
            raise OSError("handle busy")

        run.close = close
        return run

    entry = driver_bench.run_case(Case("x", make), None, repeats=1)
    assert entry == {"unavailable": "OSError: handle busy"}


def test_run_case_preserves_timing_error_when_cleanup_also_fails():
    def make(_target):
        def run():
            raise RuntimeError("timing boom")

        def close():
            raise OSError("cleanup boom")

        run.close = close
        return run

    entry = driver_bench.run_case(Case("x", make), None, repeats=1)
    assert entry == {
        "unavailable": "RuntimeError: timing boom; cleanup failed (OSError: cleanup boom)"
    }


def test_run_case_includes_audio_ms_when_given():
    entry = driver_bench.run_case(Case("x", lambda _t: lambda: 2.0, 100.0), None, 1)
    assert entry == {"median_ms": 2.0, "audio_ms": 100.0}


def test_run_cases_keys_results_by_case_id():
    cases = [Case("a", lambda _t: lambda: 1.0), Case("b", lambda _t: lambda: 2.0)]
    assert set(driver_bench.run_cases(cases, None, 1)) == {"a", "b"}


def test_pcm_chunk_holds_chunk_ms_of_16_bit_samples():
    assert len(driver_bench.pcm_chunk(16000, ms=100)) == 16000 * 100 // 1000 * 2


def test_case_ids_are_unique_and_cover_the_matrix():
    """Verify every benchmark case ID is unique and includes gRPC cases."""
    ids = [c.case_id for c in driver_bench.all_cases()]
    assert len(ids) == len(set(ids)) == 24 + 3 + 6 + 2
    assert {"grpc/startup", "grpc/first_audio"} <= set(ids)


def test_processor_cases_report_chunk_duration():
    assert {c.audio_ms for c in driver_bench.processor_cases()} == {100}


def _release_target(target):
    if target is None:
        return
    try:
        driver_bench._reset_grpc_state(target.module("adapters.dengjen_grpc"))
    finally:
        target.module("aio").terminate()


def _restore_process_state(saved_modules, saved_pkg_dict):
    for name in set(sys.modules) - set(saved_modules):
        sys.modules.pop(name, None)
    sys.modules.update(saved_modules)
    pkg_dict = sys.modules[driver_bench.PACKAGE].__dict__
    for attr in set(pkg_dict) - set(saved_pkg_dict):
        pkg_dict.pop(attr, None)
    pkg_dict.update(saved_pkg_dict)


def _teardown_bench_target(target, saved):
    """Release `target`, then restore `saved` state even when the release raises."""
    global_vars, saved_globals, saved_modules, saved_pkg_dict = saved
    try:
        _release_target(target)
    finally:
        driver_bench._restore_attrs(global_vars, saved_globals)
        _restore_process_state(saved_modules, saved_pkg_dict)


@pytest.fixture
def bench_target():
    """Load `driver_bench.Target` in-process and restore module state afterward."""
    global_vars = sys.modules["globalVars"]
    saved = (
        global_vars,
        {
            name: getattr(global_vars, name, driver_bench._MISSING)
            for name in driver_bench._GRPC_GLOBAL_ATTRS
        },
        dict(sys.modules),
        dict(sys.modules[driver_bench.PACKAGE].__dict__),
    )
    target = None
    try:
        target = driver_bench.load_target(REPO_ROOT)
        yield target
    finally:
        _teardown_bench_target(target, saved)


def test_teardown_restores_shared_state_when_terminate_raises(bench_target):
    """Ensure a failing `aio.terminate()` cannot skip the shared-state restore."""
    global_vars = sys.modules["globalVars"]
    saved = (
        global_vars,
        {"appDir": "original-app-dir"},
        dict(sys.modules),
        dict(sys.modules[driver_bench.PACKAGE].__dict__),
    )
    global_vars.appDir = "modified-app-dir"
    sys.modules["bench_leaked_module"] = types.ModuleType("bench_leaked_module")

    class _FailingTarget:
        def module(self, name):
            if name == "aio":
                return types.SimpleNamespace(terminate=_raise_terminate)
            return types.SimpleNamespace(
                SERVER_LOG_HANDLE=None, _clear_saved_server_state=lambda: None
            )

    def _raise_terminate():
        raise OSError("terminate failed")

    with pytest.raises(OSError, match="terminate failed"):
        _teardown_bench_target(_FailingTarget(), saved)

    assert global_vars.appDir == "original-app-dir"
    assert "bench_leaked_module" not in sys.modules


def test_patched_grpc_restores_patches_and_globals_when_log_close_fails(bench_target):
    """Ensure patch and globalVars state are restored even if log handle close raises."""
    grpc_mod = bench_target.module("adapters.dengjen_grpc")
    orig_grpc = grpc_mod.grpc
    orig_voices_dir = grpc_mod.DENGJEN_VOICES_BASE_DIR
    global_vars = grpc_mod.globalVars
    sentinel_proc = object()
    global_vars.DENGJEN_GRPC_SERVER_PORT = 51234
    global_vars.GRPC_SERVER_PROCESS = sentinel_proc

    class _BrokenHandle:
        def close(self):
            raise OSError("close failed")

    with (
        pytest.raises(OSError, match="close failed"),
        driver_bench._patched_grpc(bench_target),
    ):
        grpc_mod.SERVER_LOG_HANDLE = _BrokenHandle()

    assert grpc_mod.SERVER_LOG_HANDLE is None
    assert grpc_mod.grpc is orig_grpc
    assert grpc_mod.DENGJEN_VOICES_BASE_DIR == orig_voices_dir
    assert global_vars.DENGJEN_GRPC_SERVER_PORT == 51234
    assert global_vars.GRPC_SERVER_PROCESS is sentinel_proc


def test_grpc_cases_measure_startup_and_first_audio(bench_target):
    """Verify gRPC benchmark cases exercise the stub service and clean up patches."""
    shared_grpc = sys.modules["grpc"]
    orig_insecure_channel = shared_grpc.aio.insecure_channel
    grpc_mod = bench_target.module("adapters.dengjen_grpc")
    orig_voices_dir = grpc_mod.DENGJEN_VOICES_BASE_DIR

    with driver_bench._patched_grpc(bench_target) as (_mod, _svc):
        temp_voices_dir = grpc_mod.DENGJEN_VOICES_BASE_DIR
        assert os.path.isdir(temp_voices_dir)
        assert shared_grpc.aio.insecure_channel is orig_insecure_channel

    assert not os.path.exists(temp_voices_dir)
    assert grpc_mod.DENGJEN_VOICES_BASE_DIR == orig_voices_dir
    assert grpc_mod.grpc is shared_grpc

    cases_by_id = {c.case_id: c for c in driver_bench.grpc_cases()}

    startup_fn = cases_by_id["grpc/startup"].make(bench_target)
    try:
        startup_ms = driver_bench.median_ms(startup_fn, repeats=1)
        assert startup_ms > 0
        assert startup_fn.service.version_checks == 2
    finally:
        startup_fn.close()

    first_audio_fn = cases_by_id["grpc/first_audio"].make(bench_target)
    try:
        first_audio_ms = driver_bench.median_ms(first_audio_fn, repeats=1)
        assert first_audio_ms > 0
        assert first_audio_fn.service.utterances == 2
        assert first_audio_fn.service.chunks_yielded == 6
    finally:
        first_audio_fn.close()

    results = driver_bench.run_cases(driver_bench.grpc_cases(), bench_target, repeats=1)
    assert set(results) == {"grpc/startup", "grpc/first_audio"}
    assert results["grpc/startup"]["median_ms"] > 0
    assert results["grpc/first_audio"]["median_ms"] > 0


def test_smoke_run_measures_every_case_on_the_head_tree(tmp_path):
    out = tmp_path / "result.json"
    cmd = [sys.executable, "-m", "benchmarks.driver_bench", REPO_ROOT]
    cmd += ["--out", str(out), "--repeats", "1"]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, timeout=180)
    results = json.loads(out.read_text("utf-8"))
    assert set(results) == {c.case_id for c in driver_bench.all_cases()}
    assert all(entry.get("median_ms", 0) > 0 for entry in results.values())


class _EchoCache:
    def get(self, *args):
        return [b"cached"]

    def put(self, *args):
        return True


def test_cache_cases_leave_timing_to_the_harness():
    target = types.SimpleNamespace(
        module=lambda _name: types.SimpleNamespace(PhraseCache=_EchoCache)
    )
    for case in driver_bench.cache_cases():
        assert case.make(target)() is None
