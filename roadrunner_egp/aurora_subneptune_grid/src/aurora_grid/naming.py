from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np


RUN_ID_EXCLUDE_KEYS = {
    "run_index",
    "run_id",
    "output_nc",
    "status",
    "author",
    "contact",
    "project",
    "notes",
    "code",
    "netcdf_optional_variables",
    "netcdf_strict_optional",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    return value


def safe_label(value: str) -> str:
    """Return a filesystem-safe string while preserving common name separators."""
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    label = re.sub(r"_+", "_", label).strip("_.")
    if not label:
        raise ValueError("Label cannot be empty after filesystem-safe cleanup.")
    return label


def safe_float_tag(value: Any, *, keep_trailing_zero: bool = True) -> str:
    """Format a number for filenames, using ``p`` instead of decimal points."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, str):
        text = value.strip()
    else:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Cannot format non-finite value {value!r}.")
        if number.is_integer():
            text = f"{int(number)}.0" if keep_trailing_zero else str(int(number))
        else:
            text = f"{number:.12g}"
    return text.replace("-", "m").replace("+", "").replace(".", "p")


def kzz_tag(kzz_cm2_s: Any) -> str:
    exponent = math.log10(float(kzz_cm2_s))
    rounded = int(round(exponent))
    if not math.isclose(exponent, rounded, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Kzz must be an exact power of ten for tagging: {kzz_cm2_s!r}")
    return f"kzz{rounded:02d}"


def cto_to_picaso_tag(c_to_o_xsolar: float) -> str:
    mapping = {
        0.5: "050",
        1.0: "100",
        2.0: "200",
    }
    key = round(float(c_to_o_xsolar), 6)
    if key not in mapping:
        raise ValueError(
            f"Unsupported C/O x-solar value {c_to_o_xsolar!r}; "
            f"expected one of {sorted(mapping)}."
        )
    return mapping[key]


def picaso_tag_to_cto(tag: str) -> float:
    mapping = {
        "050": 0.5,
        "100": 1.0,
        "200": 2.0,
    }
    key = str(tag).strip().zfill(3)
    if key not in mapping:
        raise ValueError(
            f"Unsupported PICASO C/O tag {tag!r}; expected one of {sorted(mapping)}."
        )
    return mapping[key]


def make_run_id(row_dict: dict[str, Any]) -> str:
    payload = {
        key: _json_safe(value)
        for key, value in row_dict.items()
        if key not in RUN_ID_EXCLUDE_KEYS
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:12]


def make_output_filename(row_dict: dict[str, Any]) -> str:
    model_name = safe_label(str(row_dict["model_name"]))
    run_id = str(row_dict["run_id"])
    phase = int(round(float(row_dict["phase_deg"])))
    parts = [
        model_name,
        f"steff{int(round(float(row_dict['star_teff_k'])))}",
        f"rs{safe_float_tag(row_dict['star_radius_rsun'])}",
        f"rp{safe_float_tag(row_dict['planet_radius_rearth'])}",
        f"g{safe_float_tag(row_dict['gravity_ms2'], keep_trailing_zero=False)}",
        f"mh{safe_float_tag(row_dict['metallicity_xsolar'], keep_trailing_zero=False)}",
        f"cto{safe_float_tag(row_dict['c_to_o_xsolar'])}",
        kzz_tag(row_dict["kzz_cm2_s"]),
        f"cfrac{safe_float_tag(row_dict['cloud_fraction'])}",
        f"fsed{safe_float_tag(row_dict['fsed'], keep_trailing_zero=False)}",
        f"s{safe_float_tag(row_dict['insolation_searth'])}",
        f"phase{phase:03d}",
    ]
    return "_".join(parts) + f"__{run_id}.nc"


def make_output_path(row_dict: dict[str, Any], output_root: str | Path) -> str:
    return str(Path(output_root) / "nc" / f"run_{int(row_dict['run_index']):06d}.nc")
