from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import EXPECTED_MODEL_COUNT, load_experiment, manifests, model_manifest
from .netcdf import build_dataset, validate_file, write_atomic


DEFAULT_CONFIG = "params/tint_sensitivity_36.yaml"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def cmd_validate_config(args: argparse.Namespace) -> int:
    config = load_experiment(args.config)
    rows = manifests(config)
    print(f"VALID: {len(rows)} unique models")
    for row in rows:
        print(row["run_index"], row["run_id"], row["output_path"])
    return 0


def cmd_run_one(args: argparse.Namespace) -> int:
    config = load_experiment(args.config)
    row = model_manifest(config, args.index)
    output = Path(row["output_path"])
    if output.exists() and not args.overwrite:
        issues = validate_file(output, row)
        if not issues:
            print(f"SKIP valid restart file: {output}")
            return 0
        print(f"Existing output is invalid and will be atomically replaced: {issues}", file=sys.stderr)
    try:
        from .runner import run_model

        result = run_model(row, verbose=not args.quiet)
        dataset = build_dataset(result, row)
        write_atomic(dataset, output)
        issues = validate_file(output, row)
        if issues:
            raise RuntimeError(f"post-write NetCDF validation failed: {issues}")
        failed_marker = output.with_suffix(".failed.json")
        if failed_marker.exists():
            failed_marker.unlink()
        print(f"WROTE {output}")
        chemistry_mode = str(result.get("chemistry_mode", row.get("chemistry_mode", "unknown")))
        print(f"climate_converged={bool(result['climate_converged'])} chemistry_mode={chemistry_mode}")
        if chemistry_mode == "disequilibrium_quench":
            print(
                f"quench_differs={bool(result['quench_profile_differs_from_equilibrium'])} "
                f"max_log10_difference={result['max_quench_log10_difference']:.6g}"
            )
        return 0
    except Exception as exc:
        marker = output.with_suffix(".failed.json")
        _atomic_json(
            marker,
            {
                "run_id": row["run_id"],
                "run_index": row["run_index"],
                "failed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "traceback": traceback.format_exc(),
                "manifest": row,
            },
        )
        raise


def cmd_summarize(args: argparse.Namespace) -> int:
    config = load_experiment(args.config)
    rows = manifests(config)
    valid = 0
    missing: list[int] = []
    invalid: dict[int, list[str]] = {}
    converged = 0
    quench_different = 0
    import xarray as xr

    for row in rows:
        path = Path(row["output_path"])
        issues = validate_file(path, row)
        if issues:
            if not path.exists():
                missing.append(row["run_index"])
            else:
                invalid[row["run_index"]] = issues
            continue
        valid += 1
        with xr.open_dataset(path) as ds:
            converged += int(ds["climate_converged"].item())
            quench_different += int(ds["quench_profile_differs_from_equilibrium"].item())
    summary = {
        "expected": EXPECTED_MODEL_COUNT,
        "valid": valid,
        "missing_indices": missing,
        "invalid": invalid,
        "climate_converged": converged,
        "chemistry_mode": rows[0]["chemistry_mode"] if rows else "unknown",
        "quench_profiles_different_from_equilibrium": quench_different,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if valid == EXPECTED_MODEL_COUNT else 1


def cmd_figures(args: argparse.Namespace) -> int:
    from .analysis import generate_package

    output = generate_package(args.config, args.output, args.mode, overwrite=args.overwrite)
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aurora 36-model PICASO Tint experiment")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config")
    validate.set_defaults(func=cmd_validate_config)
    run = sub.add_parser("run-one")
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--overwrite", action="store_true")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run_one)
    summary = sub.add_parser("summarize")
    summary.set_defaults(func=cmd_summarize)
    figures = sub.add_parser("figures")
    figures.add_argument("--mode", choices=("partial", "final"), required=True)
    figures.add_argument("--output", required=True)
    figures.add_argument("--overwrite", action="store_true")
    figures.set_defaults(func=cmd_figures)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
