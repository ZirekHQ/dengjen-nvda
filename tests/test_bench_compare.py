import json

from benchmarks import compare


def _ok(ms, audio_ms=None):
    entry = {"median_ms": ms}
    return {**entry, "audio_ms": audio_ms} if audio_ms else entry


def _status(base, head):
    return compare.build_rows({"c": base}, {"c": head})[0].status


def test_ratio_below_threshold_is_ok():
    assert _status(_ok(1.0), _ok(1.9)) == "ok"


def test_ratio_at_threshold_is_slower():
    assert _status(_ok(1.0), _ok(2.0)) == "slower"


def test_faster_head_is_ok():
    assert _status(_ok(2.0), _ok(1.0)) == "ok"


def test_zero_base_has_no_ratio_and_no_warning():
    row = compare.build_rows({"c": _ok(0.0)}, {"c": _ok(5.0)})[0]
    assert row.ratio is None
    assert compare.warnings([row]) == []


def test_case_missing_from_base_is_new():
    assert compare.build_rows({}, {"c": _ok(1.0)})[0].status == "new"


def test_unavailable_base_case_is_new_without_warning():
    rows = compare.build_rows({"c": {"unavailable": "ImportError: x"}}, {"c": _ok(9.0)})
    assert rows[0].status == "new"
    assert compare.warnings(rows) == []


def test_case_missing_from_head_is_removed():
    assert compare.build_rows({"c": _ok(1.0)}, {})[0].status == "removed"


def test_warning_line_names_case_and_ratio():
    rows = compare.build_rows({"c": _ok(1.0)}, {"c": _ok(3.0)})
    [line] = compare.warnings(rows)
    assert line.startswith("::warning")
    assert "c" in line
    assert "3.0x" in line


def test_merge_runs_keeps_the_lowest_median_per_case():
    merged = compare.merge_runs([{"c": _ok(2.0)}, {"c": _ok(1.5)}])
    assert merged["c"]["median_ms"] == 1.5


def test_merge_runs_prefers_a_measurement_over_unavailable():
    merged = compare.merge_runs([{"c": {"unavailable": "x"}}, {"c": _ok(1.0)}])
    assert merged["c"]["median_ms"] == 1.0


def test_table_has_header_and_one_row_per_case():
    rows = compare.build_rows({"a": _ok(1.0), "b": _ok(1.0)}, {"a": _ok(1.0, 100.0)})
    lines = compare.render_table(rows).splitlines()
    assert lines[0].startswith("| Case")
    assert len(lines) == 2 + 2


def test_real_time_factor_is_head_over_audio():
    row = compare.build_rows({"c": _ok(1.0)}, {"c": _ok(10.0, 100.0)})[0]
    assert row.real_time_factor == 0.1


def test_main_exits_zero_and_appends_to_step_summary(tmp_path, monkeypatch, capsys):
    base, head = tmp_path / "base.json", tmp_path / "head.json"
    base.write_text(json.dumps({"c": _ok(1.0)}))
    head.write_text(json.dumps({"c": _ok(4.0)}))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = compare.main(["--base", str(base), "--head", str(head)])
    assert code == 0
    assert "| c |" in summary.read_text()
    assert "::warning" in capsys.readouterr().out


def test_main_without_any_base_file_reports_head_only(tmp_path, monkeypatch, capsys):
    head = tmp_path / "head.json"
    head.write_text(json.dumps({"c": _ok(4.0)}))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code = compare.main(["--base", str(tmp_path / "missing.json"), "--head", str(head)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Base run produced no results" in out
    assert "new" in out


def test_head_failure_with_a_working_base_is_failed_and_warns():
    head = {"unavailable": "TypeError: unexpected keyword 'x'"}
    rows = compare.build_rows({"c": _ok(1.0)}, {"c": head})
    assert rows[0].status == "failed"
    [line] = compare.warnings(rows)
    assert line.startswith("::warning")
    assert "TypeError: unexpected keyword 'x'" in line


def test_head_failure_with_an_unavailable_base_is_not_a_regression():
    both = {"unavailable": "ImportError: x"}
    rows = compare.build_rows({"c": both}, {"c": both})
    assert rows[0].status == "unavailable"
    assert compare.warnings(rows) == []


def test_case_absent_from_head_stays_removed_without_warning():
    rows = compare.build_rows({"c": _ok(1.0)}, {})
    assert rows[0].status == "removed"
    assert compare.warnings(rows) == []
