#!/usr/bin/env python
from __future__ import annotations

import argparse
import typing
from pathlib import Path

import numpy as np

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import xarray as xr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect one Aurora NetCDF output.")
    parser.add_argument("output_nc", help="Path to a NetCDF file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.output_nc)
    with xr.open_dataset(path) as dataset:
        print(f"file: {path}")
        print("dimensions:")
        print(dict(dataset.sizes))
        print("data_variables:")
        print(list(dataset.data_vars))
        print("attrs:")
        for key, value in dataset.attrs.items():
            print(f"{key}: {value}")
        wavelength_name = "wavelength" if "wavelength" in dataset else "wavelength_um"
        wavelength = dataset[wavelength_name].values
        print(f"first_{wavelength_name}: {float(wavelength[0])}")
        print(f"last_{wavelength_name}: {float(wavelength[-1])}")
        if "fpfs_reflection" in dataset:
            values = np.asarray(dataset["fpfs_reflection"].values, dtype=float)
            print(f"fpfs_reflection_min: {float(np.nanmin(values))}")
            print(f"fpfs_reflection_max: {float(np.nanmax(values))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
