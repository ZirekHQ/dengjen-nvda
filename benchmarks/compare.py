"""Compare benchmark result files and report regressions without failing."""

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

WARN_RATIO = 2.0


@dataclass(frozen=True)
class Row:
    case_id: str
    base_ms: float | None
    head_ms: float | None
    audio_ms: float | None = None
    head_error: str | None = None

    @property
    def ratio(self) -> float | None:
        if not self.base_ms or self.head_ms is None:
            return None
        return self.head_ms / self.base_ms

    @property
    def real_time_factor(self) -> float | None:
        if not self.audio_ms or self.head_ms is None:
            return None
        return self.head_ms / self.audio_ms

    def _missing_head_status(self) -> str:
        if self.base_ms is None:
            return "unavailable"
        return "failed" if self.head_error else "removed"

    @property
    def status(self) -> str:
        if self.head_ms is None:
            return self._missing_head_status()
        if self.base_ms is None:
            return "new"
        return "slower" if (self.ratio or 0.0) >= WARN_RATIO else "ok"


def _best(current, entry):
    if current is None or "median_ms" not in current:
        return entry
    if "median_ms" not in entry:
        return current
    return entry if entry["median_ms"] < current["median_ms"] else current


def merge_runs(runs):
    """Keep the lowest median per case across runs to damp runner noise."""
    merged = {}
    for run in runs:
        for case_id, entry in run.items():
            merged[case_id] = _best(merged.get(case_id), entry)
    return merged


def load_runs(paths):
    return [json.loads(Path(p).read_text("utf-8")) for p in paths if Path(p).exists()]


def _ms(entry):
    return None if entry is None else entry.get("median_ms")


def _row(case_id, base, head):
    head = head or {}
    return Row(
        case_id,
        _ms(base),
        _ms(head),
        head.get("audio_ms"),
        head.get("unavailable"),
    )


def build_rows(base, head):
    return [_row(i, base.get(i), head.get(i)) for i in sorted(set(base) | set(head))]


def _fmt(value, spec):
    return "-" if value is None else format(value, spec)


def _line(row):
    cells = [
        row.case_id,
        _fmt(row.base_ms, ".3f"),
        _fmt(row.head_ms, ".3f"),
        _fmt(row.ratio, ".2f"),
        _fmt(row.real_time_factor, ".1%"),
        row.status,
    ]
    return "| " + " | ".join(cells) + " |"


def render_table(rows):
    header = "| Case | Base ms | Head ms | Ratio | Head real-time factor | Status |"
    divider = "|---|---:|---:|---:|---:|---|"
    return "\n".join([header, divider, *map(_line, rows)])


def _warning(row):
    prefix = f"::warning title=Driver benchmark::{row.case_id}"
    if row.status == "failed":
        return f"{prefix} failed on the PR head: {row.head_error}"
    return (
        f"{prefix} is {row.ratio:.1f}x slower than the merge base "
        f"({row.base_ms:.3f} ms -> {row.head_ms:.3f} ms)"
    )


def warnings(rows):
    return [_warning(r) for r in rows if r.status in ("slower", "failed")]


def _write_summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        print(text)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", nargs="*", default=[])
    parser.add_argument("--head", nargs="+", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    base_runs = load_runs(args.base)
    rows = build_rows(merge_runs(base_runs), merge_runs(load_runs(args.head)))
    notice = "" if base_runs else "Base run produced no results; showing head only.\n\n"
    _write_summary(notice + render_table(rows))
    for line in warnings(rows):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
