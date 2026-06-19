#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


GRID_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, GRID_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DEFAULT_QC_SUMMARY = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.csv"
DEFAULT_TRIAGE = GRID_ROOT / "data" / "qc" / "triage_decisions.csv"
DEFAULT_OUT = GRID_ROOT / "data" / "rerun" / "rerun_manifest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a rerun manifest from Aurora QC and triage results.")
    parser.add_argument("--grid-manifest", required=True, help="Original grid manifest CSV.")
    parser.add_argument("--qc-summary", default=str(DEFAULT_QC_SUMMARY), help="QC summary CSV.")
    parser.add_argument("--triage-decisions", default=str(DEFAULT_TRIAGE), help="Triage decisions CSV.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output rerun manifest CSV.")
    return parser.parse_args()


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _run_id_from_plot(path: str) -> str:
    stem = Path(path).stem
    for suffix in ("_diagnostic", "_spectrum"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def main() -> int:
    args = parse_args()
    manifest_rows = _read_csv(Path(args.grid_manifest))
    qc_rows = _read_csv(Path(args.qc_summary))
    triage_rows = _read_csv(Path(args.triage_decisions))

    manifest_by_index = {str(row.get("run_index", "")): row for row in manifest_rows}
    manifest_by_id = {str(row.get("run_id", "")): row for row in manifest_rows}

    reasons: dict[str, list[str]] = {}
    for row in qc_rows:
        if _truthy(row.get("rerun_recommended")):
            key = str(row.get("run_index") or row.get("run_id"))
            reasons.setdefault(key, []).append(row.get("fail_reasons") or row.get("warning_reasons") or "qc rerun recommended")

    for row in triage_rows:
        if str(row.get("decision", "")).lower() != "bad":
            continue
        run_id = str(row.get("run_id") or _run_id_from_plot(str(row.get("plot_path", ""))))
        key = run_id
        reasons.setdefault(key, []).append(row.get("notes") or "triage marked bad")

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, reason_list in reasons.items():
        manifest_row = manifest_by_index.get(key) or manifest_by_id.get(key)
        if manifest_row is None:
            continue
        unique_key = str(manifest_row.get("run_index") or manifest_row.get("run_id"))
        if unique_key in seen:
            continue
        seen.add(unique_key)
        out_row = dict(manifest_row)
        out_row["qc_rerun_reasons"] = "; ".join(reason for reason in reason_list if reason)
        selected.append(out_row)

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(manifest_rows[0].keys()) if manifest_rows else []
    if "qc_rerun_reasons" not in fieldnames:
        fieldnames.append("qc_rerun_reasons")
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)

    print(f"rerun_rows: {len(selected)}")
    print(f"rerun_manifest: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
