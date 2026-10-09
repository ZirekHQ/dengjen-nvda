import json
import subprocess
import sys
import types

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


def test_run_case_includes_audio_ms_when_given():
    entry = driver_bench.run_case(Case("x", lambda _t: lambda: 2.0, 100.0), None, 1)
    assert entry == {"median_ms": 2.0, "audio_ms": 100.0}


def test_run_cases_keys_results_by_case_id():
    cases = [Case("a", lambda _t: lambda: 1.0), Case("b", lambda _t: lambda: 2.0)]
    assert set(driver_bench.run_cases(cases, None, 1)) == {"a", "b"}


def test_pcm_chunk_holds_chunk_ms_of_16_bit_samples():
    assert len(driver_bench.pcm_chunk(16000, ms=100)) == 16000 * 100 // 1000 * 2


def test_case_ids_are_unique_and_cover_the_matrix():
    ids = [c.case_id for c in driver_bench.all_cases()]
    assert len(ids) == len(set(ids)) == 24 + 3 + 6


def test_processor_cases_report_chunk_duration():
    assert {c.audio_ms for c in driver_bench.processor_cases()} == {100}


def test_smoke_run_measures_every_case_on_the_head_tree(tmp_path):
    out = tmp_path / "result.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.driver_bench",
            REPO_ROOT,
            "--out",
            str(out),
            "--repeats",
            "1",
        ],
        cwd=REPO_ROOT,
        check=True,
        timeout=180,
    )
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
