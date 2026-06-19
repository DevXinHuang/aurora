#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
import typing
from collections.abc import Mapping
from pathlib import Path
from typing import Any


if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
REPO_ROOT = ROADRUNNER_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from aurora_grid.parameters import read_manifest_csv
from aurora_grid.picaso_runner import run_picaso_model


DEFAULT_MANIFEST = GRID_ROOT / "manifests" / "smoke_test_manifest.csv"
DIAGNOSTIC_KEYS = [
    "moistgrad",
    "conv",
    "dtdp",
    "pressure",
    "temperature",
    "Fnet_IRFnet",
    "fnet_irfnet",
    "wavenumber",
    "thermal",
    "spectrum_output",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect exact PICASO QC diagnostic availability.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Manifest CSV path.")
    parser.add_argument("--array-index", type=int, required=True, help="Manifest run_index to execute.")
    return parser.parse_args()


def _select_row(manifest_path: str | Path, array_index: int) -> dict[str, Any]:
    manifest = read_manifest_csv(manifest_path)
    matches = [row for row in manifest if int(row["run_index"]) == int(array_index)]
    if not matches:
        raise ValueError(f"No manifest row found for run_index={array_index}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple manifest rows found for run_index={array_index}.")
    return matches[0]


def _type_name(value: Any) -> str:
    return type(value).__name__


def _shape_text(value: Any) -> str:
    shape = getattr(value, "shape", None)
    if shape is None:
        return ""
    return f" shape={tuple(shape)}"


def _mapping_keys(value: Any) -> list[str] | None:
    if isinstance(value, Mapping):
        return sorted(str(key) for key in value.keys())
    return None


def _print_keys(label: str, value: Any) -> None:
    print(f"\n[{label}]")
    print(f"type: {_type_name(value)}{_shape_text(value)}")
    keys = _mapping_keys(value)
    if keys is None:
        print("keys: <not a mapping>")
        return
    print(f"n_keys: {len(keys)}")
    for key in keys:
        item = value.get(key)
        print(f"  {key}: {_type_name(item)}{_shape_text(item)}")


def _iter_children(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        return [(f"[{key!r}]", child) for key, child in value.items()]
    if isinstance(value, (list, tuple)):
        return [(f"[{index}]", child) for index, child in enumerate(value)]
    if hasattr(value, "__dict__"):
        return [(f".{key}", child) for key, child in vars(value).items()]
    return []


def _find_key_paths(root: Any, target_key: str, max_depth: int = 12) -> list[str]:
    paths: list[str] = []
    seen: set[int] = set()

    def visit(value: Any, path: str, depth: int) -> None:
        value_id = id(value)
        if value_id in seen:
            return
        seen.add(value_id)
        if depth > max_depth:
            return

        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{path}[{key!r}]"
                if str(key) == target_key:
                    paths.append(child_path)
                visit(child, child_path, depth + 1)
            return

        if hasattr(value, target_key):
            paths.append(f"{path}.{target_key}")

        for suffix, child in _iter_children(value):
            visit(child, f"{path}{suffix}", depth + 1)

    visit(root, "model_output", 0)
    return paths


def _print_key_search(model_output: dict[str, Any]) -> None:
    print("\n[key search]")
    for key in DIAGNOSTIC_KEYS:
        paths = _find_key_paths(model_output, key)
        print(f"{key}: {'YES' if paths else 'NO'}")
        for path in paths[:20]:
            print(f"  {path}")
        if len(paths) > 20:
            print(f"  ... {len(paths) - 20} more")


def _print_justplotit_attrs() -> None:
    print("\n[picaso.justplotit]")
    try:
        from picaso import justplotit as jpi
    except Exception as exc:
        print(f"import_error: {exc}")
        return
    for name in ("pt_adiabat", "brightness_temperature"):
        value = getattr(jpi, name, None)
        print(f"{name}: {'YES' if value is not None else 'NO'} ({_type_name(value)})")


def _print_output_xarray(model_output: dict[str, Any]) -> None:
    print("\n[picaso.justdoit.output_xarray]")
    out_ref = model_output.get("picaso_out_reflected")
    out_em = model_output.get("picaso_out_emission")
    case = model_output.get("picaso_case")
    if out_ref is None or case is None:
        print("skipped: picaso_out_reflected or picaso_case missing")
        return
    try:
        from picaso import justdoit as jdi
    except Exception as exc:
        print(f"import_error: {exc}")
        return
    output_xarray = getattr(jdi, "output_xarray", None)
    if output_xarray is None:
        print("missing: picaso.justdoit.output_xarray")
        return
    try:
        dataset = output_xarray(out_ref, case, add_output={"thermal_output": out_em}, savefile=None)
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}")
        return

    print(f"type: {_type_name(dataset)}")
    dims = getattr(dataset, "sizes", getattr(dataset, "dims", {}))
    print(f"dims: {dict(dims)}")
    print(f"coords: {list(getattr(dataset, 'coords', []))}")
    print(f"data_vars: {list(getattr(dataset, 'data_vars', []))}")
    close = getattr(dataset, "close", None)
    if close is not None:
        close()


def main() -> int:
    args = parse_args()
    row = _select_row(args.manifest, args.array_index)

    print(f"manifest: {args.manifest}")
    print(f"array_index: {args.array_index}")
    print("selected_row:")
    for key in sorted(row):
        print(f"  {key}: {row[key]}")

    print("\n[running PICASO]")
    model_output = run_picaso_model(row, dry_run=False)

    out_ref = model_output.get("picaso_out_reflected")
    out_em = model_output.get("picaso_out_emission")
    ref_spectrum = out_ref.get("spectrum_output", {}) if isinstance(out_ref, Mapping) else {}
    em_spectrum = out_em.get("spectrum_output", {}) if isinstance(out_em, Mapping) else {}

    _print_keys("model_output", model_output)
    _print_keys('model_output["picaso_out_reflected"]', out_ref)
    _print_keys('model_output["picaso_out_emission"]', out_em)
    _print_keys('picaso_out_reflected.get("spectrum_output", {})', ref_spectrum)
    _print_keys('picaso_out_emission.get("spectrum_output", {})', em_spectrum)
    _print_key_search(model_output)
    _print_justplotit_attrs()
    _print_output_xarray(model_output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
