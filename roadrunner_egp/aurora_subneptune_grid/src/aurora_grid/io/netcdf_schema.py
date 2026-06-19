from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ..parameters import NOTEBOOK_REFERENCE, REPO_ROOT


AURORA_SCHEMA_NAME = "aurora_subneptune_netcdf"
AURORA_SCHEMA_VERSION = "1.0"

ABSOLUTE_FLUX_UNITS = "erg cm-2 s-1 um-1"

OPTIONAL_VARIABLES = (
    "bond_albedo",
    "thermal_planet_star_flux_ratio",
    "total_planet_star_flux_ratio",
    "mean_molecular_weight_amu",
)

QC_DIAGNOSTIC_VARIABLES = (
    "qc_adiabat",
    "qc_dtdp",
    "qc_adiabat_pressure",
    "fnet_irfnet",
    "qc_brightness_temperature",
    "qc_brightness_wavelength",
)

REQUIRED_DIMS = ("wavelength", "level", "layer", "species")
REQUIRED_COORDS = ("wavelength_um", "wavenumber_cm1", "level", "layer", "species")
REQUIRED_SPECTRAL_VARS = (
    "reflected_planet_star_flux_ratio",
    "geometric_albedo",
    "reflected_flux",
    "thermal_flux",
)
REQUIRED_PT_VARS = ("pressure_bar", "temperature_k", "mole_fraction")
REQUIRED_LAYER_VARS = ("layer_pressure_bar", "layer_temperature_k")
REQUIRED_CLOUD_VARS = (
    "cloud_optical_depth",
    "single_scattering_albedo",
    "asymmetry_factor",
)
REQUIRED_SCALAR_VARS = (
    "run_index",
    "star_teff_k",
    "star_radius_rsun",
    "star_mass_msun",
    "star_logg_cgs",
    "star_metallicity_feh",
    "planet_radius_rearth",
    "planet_mass_mearth",
    "gravity_ms2",
    "insolation_searth",
    "semi_major_axis_au",
    "equilibrium_temperature_k",
    "phase_angle_deg",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_fraction",
    "fsed",
    "run_success",
    "runtime_seconds",
)
REQUIRED_GLOBAL_ATTRS = (
    "title",
    "schema_name",
    "schema_version",
    "model_name",
    "run_id",
    "created_utc",
    "author",
    "contact",
    "code",
    "picaso_version",
    "xarray_version",
    "python_version",
    "git_commit",
    "source_manifest_row",
    "source_notebook_reference",
    "stellar_params",
    "planet_params",
    "orbit_params",
    "cld_params",
    "grid_params",
    "notes",
)

_IGNORED_PROFILE_COLUMNS = {
    "pressure",
    "temperature",
    "e-",
    "kz",
    "kzz",
    "lvl",
    "wv",
    "sigma",
}


@dataclass(frozen=True)
class AuroraNetCDFOptions:
    """Configuration for optional schema v1 variables."""

    optional_variables: tuple[str, ...] = ()
    strict_optional: bool = False

    @classmethod
    def from_value(cls, value: Any = None, *, strict_optional: Any = False) -> "AuroraNetCDFOptions":
        if isinstance(value, AuroraNetCDFOptions):
            return value
        if isinstance(value, dict):
            return cls.from_value(
                value.get("optional_variables", ()),
                strict_optional=value.get("strict_optional", strict_optional),
            )
        optional_variables = _parse_optional_variables(value)
        return cls(
            optional_variables=optional_variables,
            strict_optional=_as_bool(strict_optional),
        )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AuroraNetCDFOptions":
        return cls.from_value(
            row.get("netcdf_optional_variables", ()),
            strict_optional=row.get("netcdf_strict_optional", False),
        )

    def enabled_optional_variables(self) -> tuple[str, ...]:
        if "all" in self.optional_variables:
            return OPTIONAL_VARIABLES
        unknown = [name for name in self.optional_variables if name not in OPTIONAL_VARIABLES]
        if unknown:
            raise ValueError(f"Unknown optional NetCDF variable(s): {unknown}")
        return self.optional_variables


def _parse_optional_variables(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [part.strip() for part in text.split(",") if part.strip()]
        return _parse_optional_variables(parsed)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _json_clean(value: Any) -> Any:
    value = _json_safe(value)
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_clean(item) for item in value]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_clean(value), sort_keys=True, allow_nan=False)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _picaso_version() -> str:
    try:
        return metadata.version("picaso")
    except Exception:
        try:
            import picaso

            return str(getattr(picaso, "__version__", "unknown"))
        except Exception:
            return "unknown"


def _row_value(row: dict[str, Any], key: str, default: Any = np.nan) -> Any:
    value = row.get(key, default)
    if value is None or value == "":
        return default
    try:
        array = np.asarray(value)
        if array.shape == () and bool(array != array):
            return default
    except Exception:
        pass
    return value


def _float_row_value(row: dict[str, Any], key: str, default: float = np.nan) -> float:
    value = _row_value(row, key, default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _planet_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rp": {"value": _float_row_value(row, "planet_radius_rearth"), "unit": "R_earth"},
        "mass": {"value": _float_row_value(row, "planet_mass_mearth"), "unit": "M_earth"},
        "gravity": {"value": _float_row_value(row, "gravity_ms2"), "unit": "m s-2"},
        "mh": {"value": _float_row_value(row, "metallicity_xsolar"), "unit": "x_solar"},
        "cto": {"value": _float_row_value(row, "c_to_o_xsolar"), "unit": "x_solar_C_to_O"},
        "cto_picaso_tag": {"value": str(_row_value(row, "c_to_o_picaso_tag", "")).zfill(3), "unit": "table_tag"},
        "logkzz": {"value": _float_row_value(row, "logkzz"), "unit": "log10_cm2_s-1"},
        "picaso_tint": {"value": _float_row_value(row, "picaso_tint_k"), "unit": "K"},
    }


def _stellar_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "steff": {"value": _float_row_value(row, "star_teff_k"), "unit": "K"},
        "rs": {"value": _float_row_value(row, "star_radius_rsun"), "unit": "R_sun"},
        "mass": {"value": _float_row_value(row, "star_mass_msun"), "unit": "M_sun"},
        "logg": {"value": _float_row_value(row, "star_logg_cgs"), "unit": "cgs"},
        "feh": {"value": _float_row_value(row, "star_metallicity_feh"), "unit": "dex"},
        "luminosity": {"value": _float_row_value(row, "stellar_luminosity_lsun"), "unit": "L_sun"},
    }


def _orbit_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sma": {"value": _float_row_value(row, "semi_major_au"), "unit": "AU"},
        "insolation": {"value": _float_row_value(row, "insolation_searth"), "unit": "S_earth"},
        "phase": {"value": _float_row_value(row, "phase_deg"), "unit": "deg"},
        "equilibrium_temperature": {"value": _float_row_value(row, "equilibrium_temperature_k"), "unit": "K"},
    }


def _cld_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cloud_fraction": {"value": _float_row_value(row, "cloud_fraction"), "unit": "unitless"},
        "cloud_model": {"value": str(row.get("cloud_model", "")), "unit": "label"},
        "fsed": {"value": _float_row_value(row, "fsed"), "unit": "unitless"},
        "kzz": {"value": _float_row_value(row, "kzz_cm2_s"), "unit": "cm2 s-1"},
    }


def _grid_params(row: dict[str, Any], model_output: dict[str, Any], wavelength_um: np.ndarray) -> dict[str, Any]:
    return {
        "run_index": int(_float_row_value(row, "run_index", -1)),
        "model_name": str(row.get("model_name", "")),
        "picaso_tint_mode": str(row.get("picaso_tint_mode", "equilibrium")),
        "picaso_tint_fixed_k": _float_row_value(row, "picaso_tint_fixed_k", 1000.0),
        "picaso_tint_floor_k": _float_row_value(row, "picaso_tint_floor_k", 100.0),
        "wavelength_min_um": float(np.nanmin(wavelength_um)),
        "wavelength_max_um": float(np.nanmax(wavelength_um)),
        "wavelength_points": int(wavelength_um.size),
        "picaso_metadata": model_output.get("picaso_metadata", {}),
    }


def _config_code(row: dict[str, Any]) -> str:
    code = row.get("code", "{}")
    if isinstance(code, str):
        return code
    return _json_dumps(code)


def _as_1d_float(values: Any, name: str) -> np.ndarray:
    if values is None:
        raise ValueError(f"Missing required array: {name}")
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional; got shape {array.shape}")
    return array


def _as_optional_1d_float(values: Any) -> np.ndarray | None:
    if values is None:
        return None
    try:
        array = np.asarray(values, dtype=float)
    except Exception:
        return None
    if array.ndim != 1:
        array = np.ravel(array)
    if array.size == 0:
        return None
    return array


def _match_wavelength_array(values: Any, wavelength_size: int, name: str) -> np.ndarray:
    array = _as_1d_float(values, name)
    if array.size != wavelength_size:
        raise ValueError(f"{name} has length {array.size}; expected {wavelength_size}")
    return array


def _profile_columns(profile: Any) -> list[str]:
    if profile is None:
        return []
    if hasattr(profile, "columns"):
        return [str(col) for col in profile.columns]
    if isinstance(profile, dict):
        return [str(col) for col in profile]
    return []


def _profile_values(profile: Any, key: str) -> np.ndarray | None:
    if profile is None:
        return None
    try:
        values = profile[key]
    except Exception:
        return None
    if hasattr(values, "values"):
        values = values.values
    try:
        return np.asarray(values, dtype=float)
    except Exception:
        return None


def _profile_from_model_output(model_output: dict[str, Any]) -> Any:
    if model_output.get("pt_profile") is not None:
        return model_output["pt_profile"]
    case = model_output.get("picaso_case")
    try:
        return case.inputs["atmosphere"]["profile"]
    except Exception:
        return None


def _extract_pt_profile(model_output: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    profile = _profile_from_model_output(model_output)
    pressure = _profile_values(profile, "pressure")
    temperature = _profile_values(profile, "temperature")
    if pressure is None or temperature is None:
        raise ValueError("PT profile must include pressure and temperature columns")
    pressure = _as_1d_float(pressure, "pressure_bar")
    temperature = _as_1d_float(temperature, "temperature_k")
    if pressure.size != temperature.size:
        raise ValueError("pressure_bar and temperature_k must have the same length")

    species: list[str] = []
    mole_arrays: list[np.ndarray] = []
    for column in _profile_columns(profile):
        key = column.strip()
        lower = key.lower()
        if key in _IGNORED_PROFILE_COLUMNS or lower in _IGNORED_PROFILE_COLUMNS or lower.startswith("guess"):
            continue
        values = _profile_values(profile, column)
        if values is None:
            continue
        values = np.asarray(values, dtype=float)
        if values.ndim != 1 or values.size != pressure.size:
            continue
        species.append(key)
        mole_arrays.append(values)

    if not species:
        raise ValueError("PT profile must include at least one gas species column")
    mole_fraction = np.stack(mole_arrays, axis=1)
    return pressure, temperature, species, mole_fraction


def _native_wavelength_um_from_reflected_output(model_output: dict[str, Any]) -> np.ndarray | None:
    out_ref = model_output.get("picaso_out_reflected")
    if isinstance(out_ref, dict) and "wavenumber" in out_ref:
        with np.errstate(divide="ignore", invalid="ignore"):
            return 1.0e4 / np.asarray(out_ref["wavenumber"], dtype=float)
    return None


def _interp_2d_native_to_schema(values: Any, native_wavelength_um: np.ndarray, wavelength_um: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise ValueError(f"{name} must be 2D (layer, wavelength); got shape {array.shape}")
    if array.shape[1] != native_wavelength_um.size:
        raise ValueError(
            f"{name} wavelength axis has length {array.shape[1]}; "
            f"expected {native_wavelength_um.size}"
        )
    order = np.argsort(native_wavelength_um)
    sorted_wavelength = native_wavelength_um[order]
    sorted_values = array[:, order]
    out = np.empty((array.shape[0], wavelength_um.size), dtype=float)
    for layer_index in range(array.shape[0]):
        row = sorted_values[layer_index]
        out[layer_index] = np.interp(
            wavelength_um,
            sorted_wavelength,
            row,
            left=float(row[0]),
            right=float(row[-1]),
        )
    return np.nan_to_num(out)


def _is_cloud_free(row: dict[str, Any], model_output: dict[str, Any]) -> bool:
    metadata = model_output.get("picaso_metadata", {})
    cloud_model = str(metadata.get("cloud_model", row.get("cloud_model", ""))).strip().lower()
    if cloud_model in {"none", "clear", "cloudfree", "cloud-free"}:
        return True
    try:
        return math.isclose(float(row.get("cloud_fraction", np.nan)), 0.0, abs_tol=1.0e-12)
    except Exception:
        return False


def _cloud_from_model_output(model_output: dict[str, Any], key: str) -> Any:
    cloud_profile = model_output.get("cloud_profile")
    if isinstance(cloud_profile, dict):
        aliases = {
            "opd": ("opd", "cloud_optical_depth"),
            "w0": ("w0", "ssa", "single_scattering_albedo"),
            "g0": ("g0", "asy", "asymmetry_factor"),
        }[key]
        for alias in aliases:
            if alias in cloud_profile:
                return cloud_profile[alias]
    out_ref = model_output.get("picaso_out_reflected")
    if isinstance(out_ref, dict):
        full_output = out_ref.get("full_output")
        try:
            return full_output["layer"]["cloud"][key]
        except Exception:
            return None
    return None


def _extract_cloud_profile(
    model_output: dict[str, Any],
    row: dict[str, Any],
    wavelength_um: np.ndarray,
    nlayer: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    direct_profile = model_output.get("cloud_profile")
    native_wavelength = None
    if isinstance(direct_profile, dict):
        native_wavelength = direct_profile.get("wavelength_um")
    if native_wavelength is None:
        native_wavelength = _native_wavelength_um_from_reflected_output(model_output)
    if native_wavelength is None:
        native_wavelength = wavelength_um
    native_wavelength = _as_1d_float(native_wavelength, "cloud_native_wavelength_um")

    cloud_arrays = []
    for source_key, output_name in (
        ("opd", "cloud_optical_depth"),
        ("w0", "single_scattering_albedo"),
        ("g0", "asymmetry_factor"),
    ):
        values = _cloud_from_model_output(model_output, source_key)
        if values is None:
            if _is_cloud_free(row, model_output):
                cloud_arrays.append(np.zeros((nlayer, wavelength_um.size), dtype=float))
                continue
            raise ValueError(f"Missing required cloud array: {output_name}")
        array = np.asarray(values, dtype=float)
        if array.ndim > 2:
            array = np.squeeze(array)
        if array.ndim == 1 and array.size == nlayer * native_wavelength.size:
            array = array.reshape(nlayer, native_wavelength.size)
        if (
            array.shape != (nlayer, wavelength_um.size)
            or native_wavelength.size != wavelength_um.size
            or not np.allclose(native_wavelength, wavelength_um, rtol=0.0, atol=1.0e-12)
        ):
            array = _interp_2d_native_to_schema(array, native_wavelength, wavelength_um, output_name)
        if array.shape != (nlayer, wavelength_um.size):
            raise ValueError(f"{output_name} has shape {array.shape}; expected {(nlayer, wavelength_um.size)}")
        cloud_arrays.append(array)
    return tuple(cloud_arrays)  # type: ignore[return-value]


def _optional_array_from_model_output(model_output: dict[str, Any], name: str, wavelength_size: int) -> np.ndarray | None:
    if name == "bond_albedo":
        value = model_output.get("bond_albedo")
        if value is None:
            return None
        array = np.asarray(value, dtype=float)
        if array.shape == ():
            return np.full(wavelength_size, float(array), dtype=float)
        return _match_wavelength_array(array, wavelength_size, name)
    if name == "thermal_planet_star_flux_ratio":
        value = model_output.get("thermal_planet_star_flux_ratio", model_output.get("fpfs_emission"))
        if value is None:
            return None
        return _match_wavelength_array(value, wavelength_size, name)
    if name == "total_planet_star_flux_ratio":
        value = model_output.get("total_planet_star_flux_ratio")
        if value is not None:
            return _match_wavelength_array(value, wavelength_size, name)
        reflected = model_output.get("fpfs_reflection")
        thermal = model_output.get("thermal_planet_star_flux_ratio", model_output.get("fpfs_emission"))
        if reflected is None or thermal is None:
            return None
        return _match_wavelength_array(reflected, wavelength_size, "reflected") + _match_wavelength_array(
            thermal,
            wavelength_size,
            "thermal",
        )
    return None


def _optional_level_array_from_model_output(model_output: dict[str, Any], name: str, nlevel: int) -> np.ndarray | None:
    if name != "mean_molecular_weight_amu":
        return None
    value = model_output.get("mean_molecular_weight_amu")
    if value is None:
        profile = _profile_from_model_output(model_output)
        for key in ("mean_molecular_weight_amu", "mmw", "mean_molecular_weight"):
            values = _profile_values(profile, key)
            if values is not None:
                value = values
                break
    if value is None:
        return None
    return _match_wavelength_array(value, nlevel, name)


def _optional_description(name: str) -> str:
    descriptions = {
        "bond_albedo": "Bond albedo spectrum when supplied by the model output.",
        "thermal_planet_star_flux_ratio": "Thermal-emission planet/star flux ratio.",
        "total_planet_star_flux_ratio": "Total planet/star flux ratio, reflected plus thermal.",
    }
    return descriptions.get(name, "Optional schema v1 diagnostic.")


def _parse_adiabat_result(result: Any) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if result is None or not isinstance(result, (tuple, list)):
        return None, None, None
    if len(result) >= 4:
        _, adiabat, dtdp, pressure = result[:4]
    elif len(result) >= 3:
        adiabat, dtdp, pressure = result[:3]
    else:
        return None, None, None
    return (
        _as_optional_1d_float(adiabat),
        _as_optional_1d_float(dtdp),
        _as_optional_1d_float(pressure),
    )


def _brightness_wavelength(raw_output: dict[str, Any], brightness: np.ndarray) -> np.ndarray | None:
    spectrum = raw_output.get("spectrum_output") if isinstance(raw_output, dict) else None
    if isinstance(spectrum, dict) and "wavenumber" in spectrum:
        wavenumber = _as_optional_1d_float(spectrum["wavenumber"])
    elif isinstance(raw_output, dict) and "wavenumber" in raw_output:
        wavenumber = _as_optional_1d_float(raw_output["wavenumber"])
    else:
        return None
    if wavenumber is None or wavenumber.size != brightness.size:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0e4 / wavenumber


def _maybe_picaso_output_xarray(model_output: dict[str, Any]) -> tuple[xr.Dataset | None, str | None]:
    out_ref = model_output.get("picaso_out_reflected")
    case = model_output.get("picaso_case")
    if out_ref is None or case is None:
        return None, None

    try:
        from picaso import justdoit as jdi
    except Exception as exc:
        return None, f"PICASO output_xarray import failed: {exc}"
    output_xarray = getattr(jdi, "output_xarray", None)
    if output_xarray is None:
        return None, "picaso.justdoit.output_xarray unavailable"

    add_output = {}
    out_emission = model_output.get("picaso_out_emission")
    if isinstance(out_emission, dict):
        add_output["thermal_output"] = out_emission
    try:
        dataset = output_xarray(out_ref, case, add_output=add_output, savefile=None)
    except Exception as exc:
        if not add_output:
            return None, f"PICASO output_xarray failed: {exc}"
        try:
            dataset = output_xarray(out_ref, case, add_output={}, savefile=None)
        except Exception:
            return None, f"PICASO output_xarray failed: {exc}"
    if not isinstance(dataset, xr.Dataset):
        return None, f"PICASO output_xarray returned {type(dataset).__name__}"
    return dataset, None


def _raw_picaso_outputs(model_output: dict[str, Any]) -> tuple[Any, ...]:
    return (
        model_output.get("picaso_out_emission"),
        model_output.get("picaso_out_reflected"),
    )


def _extract_explicit_qc_diagnostics(model_output: dict[str, Any]) -> dict[str, np.ndarray]:
    diagnostics: dict[str, np.ndarray] = {}
    nested = model_output.get("qc_diagnostics")
    sources = [nested] if isinstance(nested, dict) else []
    sources.append(model_output)
    aliases = {
        "qc_adiabat": ("qc_adiabat",),
        "qc_dtdp": ("qc_dtdp",),
        "qc_adiabat_pressure": ("qc_adiabat_pressure",),
        "fnet_irfnet": ("fnet_irfnet", "Fnet_IRFnet", "Fnet/IR-Fnet"),
        "qc_brightness_temperature": ("qc_brightness_temperature", "brightness_temperature"),
        "qc_brightness_wavelength": ("qc_brightness_wavelength", "brightness_wavelength", "brightness_wavelength_um"),
    }
    for target, names in aliases.items():
        for source in sources:
            for name in names:
                array = _as_optional_1d_float(source.get(name))
                if array is not None:
                    diagnostics[target] = array
                    break
            if target in diagnostics:
                break
    return diagnostics


def _extract_jpi_adiabat(model_output: dict[str, Any], warnings: list[str]) -> dict[str, np.ndarray]:
    case = model_output.get("picaso_case")
    opacity = model_output.get("picaso_opacity")
    if case is None or opacity is None:
        return {}
    raw_outputs = [raw for raw in _raw_picaso_outputs(model_output) if isinstance(raw, dict)]
    if not raw_outputs:
        return {}
    try:
        from picaso import justplotit as jpi
    except Exception as exc:
        warnings.append(f"exact adiabat diagnostic unavailable: PICASO plotting import failed: {exc}")
        return {}
    pt_adiabat = getattr(jpi, "pt_adiabat", None)
    if pt_adiabat is None:
        warnings.append("exact adiabat diagnostic unavailable: picaso.justplotit.pt_adiabat missing")
        return {}
    for raw_output in raw_outputs:
        try:
            adiabat, dtdp, pressure = _parse_adiabat_result(pt_adiabat(raw_output, case, opacity, plot=False))
        except Exception as exc:
            warnings.append(f"exact adiabat diagnostic unavailable: {exc}")
            continue
        if adiabat is not None and dtdp is not None and pressure is not None:
            return {
                "qc_adiabat": adiabat,
                "qc_dtdp": dtdp,
                "qc_adiabat_pressure": pressure,
            }
    return {}


def _extract_jpi_brightness(model_output: dict[str, Any], warnings: list[str]) -> dict[str, np.ndarray]:
    raw_outputs = [
        raw
        for raw in _raw_picaso_outputs(model_output)
        if isinstance(raw, dict) and "spectrum_output" in raw
    ]
    if not raw_outputs:
        return {}
    try:
        from picaso import justplotit as jpi
    except Exception as exc:
        warnings.append(f"exact brightness-temperature diagnostic unavailable: PICASO plotting import failed: {exc}")
        return {}
    brightness_temperature = getattr(jpi, "brightness_temperature", None)
    if brightness_temperature is None:
        warnings.append("exact brightness-temperature diagnostic unavailable: picaso.justplotit.brightness_temperature missing")
        return {}

    for raw_output in raw_outputs:
        try:
            brightness = _as_optional_1d_float(brightness_temperature(raw_output["spectrum_output"], plot=False))
        except Exception as exc:
            warnings.append(f"exact brightness-temperature diagnostic unavailable: {exc}")
            continue
        if brightness is None:
            continue
        wavelength = _brightness_wavelength(raw_output, brightness)
        diagnostics = {"qc_brightness_temperature": brightness}
        if wavelength is not None:
            diagnostics["qc_brightness_wavelength"] = wavelength
        return diagnostics
    return {}


def _extract_output_xarray_flux(model_output: dict[str, Any], warnings: list[str]) -> dict[str, np.ndarray]:
    dataset, error = _maybe_picaso_output_xarray(model_output)
    if dataset is None:
        if error:
            warnings.append(f"exact flux-balance diagnostic unavailable: {error}")
        return {}
    try:
        for name in ("fnet_irfnet", "Fnet_IRFnet", "Fnet/IR-Fnet"):
            if name in dataset:
                values = _as_optional_1d_float(dataset[name].values)
                if values is not None:
                    return {"fnet_irfnet": values}
        return {}
    finally:
        dataset.close()


def extract_aurora_qc_diagnostics(model_output: dict[str, Any]) -> tuple[dict[str, np.ndarray], list[str]]:
    """Extract exact PICASO climate QC diagnostics without approximating them."""
    warnings: list[str] = []
    diagnostics = _extract_explicit_qc_diagnostics(model_output)

    if not {"qc_adiabat", "qc_dtdp", "qc_adiabat_pressure"}.issubset(diagnostics):
        diagnostics.update({key: value for key, value in _extract_jpi_adiabat(model_output, warnings).items() if key not in diagnostics})
    if "fnet_irfnet" not in diagnostics:
        diagnostics.update(_extract_output_xarray_flux(model_output, warnings))
    if "qc_brightness_temperature" not in diagnostics:
        diagnostics.update({key: value for key, value in _extract_jpi_brightness(model_output, warnings).items() if key not in diagnostics})

    return diagnostics, warnings


def _diagnostic_vertical_dim(size: int, nlevel: int, nlayer: int) -> str | None:
    if size == nlevel:
        return "level"
    if size == nlayer:
        return "layer"
    return None


def _align_to_schema_wavelength(
    values: np.ndarray,
    source_wavelength: np.ndarray | None,
    schema_wavelength: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if source_wavelength is None:
        if values.size == schema_wavelength.size:
            return values, schema_wavelength
        return None, None
    if values.size != source_wavelength.size:
        return None, None
    order = np.argsort(source_wavelength)
    sorted_wavelength = source_wavelength[order]
    if sorted_wavelength.size != schema_wavelength.size or not np.allclose(
        sorted_wavelength,
        schema_wavelength,
        rtol=0.0,
        atol=1.0e-10,
    ):
        return None, None
    return values[order], schema_wavelength


def _add_exact_qc_diagnostics(
    ds: xr.Dataset,
    diagnostics: dict[str, np.ndarray],
    wavelength_um: np.ndarray,
    nlevel: int,
    nlayer: int,
    warnings: list[str],
) -> None:
    if {"qc_adiabat", "qc_dtdp", "qc_adiabat_pressure"}.issubset(diagnostics):
        sizes = {diagnostics[name].size for name in ("qc_adiabat", "qc_dtdp", "qc_adiabat_pressure")}
        if len(sizes) == 1:
            size = sizes.pop()
            dim = _diagnostic_vertical_dim(size, nlevel, nlayer)
            if dim is not None:
                ds["qc_adiabat"] = (
                    (dim,),
                    diagnostics["qc_adiabat"],
                    {
                        "units": "K bar-1",
                        "description": "Exact PICASO adiabatic temperature gradient diagnostic.",
                    },
                )
                ds["qc_dtdp"] = (
                    (dim,),
                    diagnostics["qc_dtdp"],
                    {
                        "units": "K bar-1",
                        "description": "Exact PICASO atmospheric dT/dP diagnostic.",
                    },
                )
                ds["qc_adiabat_pressure"] = (
                    (dim,),
                    diagnostics["qc_adiabat_pressure"],
                    {
                        "units": "bar",
                        "description": "Pressure grid returned with exact PICASO adiabatic diagnostic.",
                    },
                )
            else:
                warnings.append(f"exact adiabat diagnostic length {size} does not match level or layer dimension")
        else:
            warnings.append("exact adiabat diagnostic arrays have inconsistent lengths")

    fnet = diagnostics.get("fnet_irfnet")
    if fnet is not None:
        dim = _diagnostic_vertical_dim(fnet.size, nlevel, nlayer)
        if dim is not None:
            ds["fnet_irfnet"] = (
                (dim,),
                fnet,
                {
                    "units": "dimensionless",
                    "description": "Exact PICASO Fnet/IR-Fnet flux-balance diagnostic.",
                },
            )
        else:
            warnings.append(f"exact flux-balance diagnostic length {fnet.size} does not match level or layer dimension")

    brightness = diagnostics.get("qc_brightness_temperature")
    if brightness is not None:
        brightness_wavelength = diagnostics.get("qc_brightness_wavelength")
        aligned_brightness, aligned_wavelength = _align_to_schema_wavelength(
            brightness,
            brightness_wavelength,
            wavelength_um,
        )
        if aligned_brightness is not None and aligned_wavelength is not None:
            ds["qc_brightness_temperature"] = (
                ("wavelength",),
                aligned_brightness,
                {
                    "units": "K",
                    "description": "Exact PICASO brightness-temperature diagnostic on the schema wavelength grid.",
                },
            )
            ds["qc_brightness_wavelength"] = (
                ("wavelength",),
                aligned_wavelength,
                {
                    "units": "um",
                    "description": "Wavelength grid for the exact PICASO brightness-temperature diagnostic.",
                },
            )
        else:
            warnings.append("exact brightness-temperature diagnostic does not match schema wavelength grid")


def _add_scalar(ds: xr.Dataset, name: str, value: Any, units: str | None = None) -> None:
    if name == "run_success":
        try:
            scalar: Any = np.int8(1 if _as_bool(value) else 0)
        except Exception:
            scalar = np.int8(0)
    elif name == "run_index":
        try:
            scalar = np.int64(value)
        except Exception:
            scalar = np.int64(-1)
    else:
        try:
            scalar = np.float64(value)
        except Exception:
            scalar = np.float64(np.nan)
    ds[name] = scalar
    if units:
        ds[name].attrs["units"] = units


def _schema_warning_for_missing_scalars(row: dict[str, Any]) -> list[str]:
    warnings = []
    for name in ("star_mass_msun", "star_logg_cgs", "star_metallicity_feh", "planet_mass_mearth"):
        value = row.get(name)
        if value is None or value == "":
            warnings.append(f"{name} unavailable; stored NaN")
    return warnings


def build_aurora_run_dataset(
    model_output: dict[str, Any],
    row: dict[str, Any],
    runtime_seconds: float | None = None,
    run_success: bool = True,
    schema_options: AuroraNetCDFOptions | dict[str, Any] | None = None,
) -> xr.Dataset:
    options = AuroraNetCDFOptions.from_value(schema_options) if schema_options is not None else AuroraNetCDFOptions.from_row(row)
    enabled_optional = options.enabled_optional_variables()
    schema_warnings = _schema_warning_for_missing_scalars(row)

    wavelength_um = _as_1d_float(model_output.get("wavelength_um"), "wavelength_um")
    n_wavelength = wavelength_um.size
    reflected_ratio = _match_wavelength_array(model_output.get("fpfs_reflection"), n_wavelength, "fpfs_reflection")
    geometric_albedo = _match_wavelength_array(model_output.get("albedo"), n_wavelength, "albedo")
    reflected_flux = _match_wavelength_array(model_output.get("absolute_flux_reflected"), n_wavelength, "absolute_flux_reflected")
    thermal_flux = _match_wavelength_array(model_output.get("absolute_flux_thermal"), n_wavelength, "absolute_flux_thermal")

    pressure_bar, temperature_k, species, mole_fraction = _extract_pt_profile(model_output)
    nlevel = pressure_bar.size
    nlayer = nlevel - 1
    if nlayer <= 0:
        raise ValueError("PT profile must contain at least two levels")

    layer_pressure_bar = np.sqrt(pressure_bar[:-1] * pressure_bar[1:])
    layer_temperature_k = 0.5 * (temperature_k[:-1] + temperature_k[1:])
    cloud_optical_depth, single_scattering_albedo, asymmetry_factor = _extract_cloud_profile(
        model_output,
        row,
        wavelength_um,
        nlayer,
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        wavenumber_cm1 = 1.0e4 / wavelength_um

    ds = xr.Dataset(
        data_vars={
            "reflected_planet_star_flux_ratio": (
                ("wavelength",),
                reflected_ratio,
                {
                    "units": "dimensionless",
                    "description": "Reflected-light planet/star flux ratio.",
                },
            ),
            "geometric_albedo": (
                ("wavelength",),
                geometric_albedo,
                {
                    "units": "dimensionless",
                    "description": "Geometric albedo spectrum.",
                },
            ),
            "reflected_flux": (
                ("wavelength",),
                reflected_flux,
                {
                    "units": ABSOLUTE_FLUX_UNITS,
                    "description": "Absolute reflected planet flux diagnostic converted from Roadrunner/PICASO output to per-micron wavelength units.",
                },
            ),
            "thermal_flux": (
                ("wavelength",),
                thermal_flux,
                {
                    "units": ABSOLUTE_FLUX_UNITS,
                    "description": "Absolute thermal planet flux diagnostic converted from Roadrunner/PICASO output to per-micron wavelength units. Only valid if the thermal calculation was run.",
                },
            ),
            "pressure_bar": (("level",), pressure_bar, {"units": "bar"}),
            "temperature_k": (("level",), temperature_k, {"units": "K"}),
            "mole_fraction": (
                ("level", "species"),
                mole_fraction,
                {
                    "units": "v/v",
                    "description": "Volume mixing ratio for each gas species.",
                },
            ),
            "layer_pressure_bar": (("layer",), layer_pressure_bar, {"units": "bar"}),
            "layer_temperature_k": (("layer",), layer_temperature_k, {"units": "K"}),
            "cloud_optical_depth": (
                ("layer", "wavelength"),
                cloud_optical_depth,
                {"units": "unitless per layer"},
            ),
            "single_scattering_albedo": (
                ("layer", "wavelength"),
                single_scattering_albedo,
                {"units": "dimensionless"},
            ),
            "asymmetry_factor": (
                ("layer", "wavelength"),
                asymmetry_factor,
                {"units": "dimensionless"},
            ),
        },
        coords={
            "wavelength_um": ("wavelength", wavelength_um, {"units": "um"}),
            "wavenumber_cm1": ("wavelength", wavenumber_cm1, {"units": "cm^-1"}),
            "level": ("level", np.arange(nlevel, dtype=np.int32), {"units": "index"}),
            "layer": ("layer", np.arange(nlayer, dtype=np.int32), {"units": "index"}),
            "species": ("species", np.asarray(species, dtype=str)),
        },
    )

    for optional_name in enabled_optional:
        optional_array = None
        if optional_name == "mean_molecular_weight_amu":
            optional_array = _optional_level_array_from_model_output(model_output, optional_name, nlevel)
            if optional_array is not None:
                ds[optional_name] = (
                    ("level",),
                    optional_array,
                    {
                        "units": "amu",
                        "description": "Level-valued atmospheric mean molecular weight.",
                    },
                )
        else:
            optional_array = _optional_array_from_model_output(model_output, optional_name, n_wavelength)
            if optional_array is not None:
                ds[optional_name] = (
                    ("wavelength",),
                    optional_array,
                    {
                        "units": "dimensionless",
                        "description": _optional_description(optional_name),
                    },
                )
        if optional_array is None:
            message = f"optional variable {optional_name} requested but unavailable"
            if options.strict_optional:
                raise ValueError(message)
            schema_warnings.append(message)

    qc_diagnostics, qc_warnings = extract_aurora_qc_diagnostics(model_output)
    schema_warnings.extend(qc_warnings)
    _add_exact_qc_diagnostics(
        ds,
        qc_diagnostics,
        wavelength_um,
        nlevel,
        nlayer,
        schema_warnings,
    )

    scalar_values = {
        "run_index": _row_value(row, "run_index", -1),
        "star_teff_k": _row_value(row, "star_teff_k"),
        "star_radius_rsun": _row_value(row, "star_radius_rsun"),
        "star_mass_msun": _row_value(row, "star_mass_msun"),
        "star_logg_cgs": _row_value(row, "star_logg_cgs"),
        "star_metallicity_feh": _row_value(row, "star_metallicity_feh"),
        "planet_radius_rearth": _row_value(row, "planet_radius_rearth"),
        "planet_mass_mearth": _row_value(row, "planet_mass_mearth"),
        "gravity_ms2": _row_value(row, "gravity_ms2"),
        "insolation_searth": _row_value(row, "insolation_searth"),
        "semi_major_axis_au": _row_value(row, "semi_major_au"),
        "equilibrium_temperature_k": _row_value(row, "equilibrium_temperature_k"),
        "phase_angle_deg": _row_value(row, "phase_deg"),
        "metallicity_xsolar": _row_value(row, "metallicity_xsolar"),
        "c_to_o_xsolar": _row_value(row, "c_to_o_xsolar"),
        "kzz_cm2_s": _row_value(row, "kzz_cm2_s"),
        "cloud_fraction": _row_value(row, "cloud_fraction"),
        "fsed": _row_value(row, "fsed"),
        "run_success": run_success,
        "runtime_seconds": np.nan if runtime_seconds is None else runtime_seconds,
    }
    scalar_units = {
        "star_teff_k": "K",
        "star_radius_rsun": "R_sun",
        "star_mass_msun": "M_sun",
        "star_logg_cgs": "log10(cm s-2)",
        "star_metallicity_feh": "dex",
        "planet_radius_rearth": "R_earth",
        "planet_mass_mearth": "M_earth",
        "gravity_ms2": "m s-2",
        "insolation_searth": "S_earth",
        "semi_major_axis_au": "AU",
        "equilibrium_temperature_k": "K",
        "phase_angle_deg": "deg",
        "metallicity_xsolar": "x_solar",
        "c_to_o_xsolar": "x_solar",
        "kzz_cm2_s": "cm2 s-1",
        "cloud_fraction": "dimensionless",
        "fsed": "dimensionless",
        "runtime_seconds": "s",
    }
    for name, value in scalar_values.items():
        _add_scalar(ds, name, value, scalar_units.get(name))

    ds.attrs.update(
        {
            "title": "AURORA sub-Neptune reflected-light model run",
            "schema_name": AURORA_SCHEMA_NAME,
            "schema_version": AURORA_SCHEMA_VERSION,
            "model_name": str(row.get("model_name", "")),
            "run_id": str(row.get("run_id", "")),
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "author": str(_row_value(row, "author", "")),
            "contact": str(_row_value(row, "contact", "")),
            "code": _config_code(row),
            "picaso_version": _picaso_version(),
            "xarray_version": xr.__version__,
            "python_version": platform.python_version(),
            "git_commit": _git_commit(),
            "source_manifest_row": _json_dumps(row),
            "source_notebook_reference": str(row.get("source_notebook_reference", NOTEBOOK_REFERENCE)),
            "stellar_params": _json_dumps(_stellar_params(row)),
            "planet_params": _json_dumps(_planet_params(row)),
            "orbit_params": _json_dumps(_orbit_params(row)),
            "cld_params": _json_dumps(_cld_params(row)),
            "grid_params": _json_dumps(_grid_params(row, model_output, wavelength_um)),
            "notes": str(_row_value(row, "notes", "")),
            "schema_warnings": _json_dumps(schema_warnings),
            "netcdf_optional_variables": _json_dumps(list(enabled_optional)),
            "netcdf_strict_optional": str(bool(options.strict_optional)),
        }
    )

    issues = validate_aurora_netcdf_schema(ds)
    errors = [issue for issue in issues if issue.startswith("ERROR:")]
    warnings = [issue for issue in issues if issue.startswith("WARNING:")]
    if warnings:
        schema_warnings.extend(issue.removeprefix("WARNING: ") for issue in warnings)
        ds.attrs["schema_warnings"] = _json_dumps(sorted(set(schema_warnings)))
    if errors:
        raise ValueError("; ".join(errors))
    return ds


def _best_netcdf_engine() -> str:
    """Return the best available xarray NetCDF engine.

    netcdf4 and h5netcdf support compression options like zlib/complevel/shuffle.
    scipy is a safe fallback, but it only writes basic NetCDF and must not receive
    compression encoding.
    """
    try:
        import netCDF4  # noqa: F401

        return "netcdf4"
    except Exception:
        pass

    try:
        import h5netcdf  # noqa: F401

        return "h5netcdf"
    except Exception:
        pass

    return "scipy"


def _numeric_data_encoding(ds: xr.Dataset) -> dict[str, dict[str, Any]]:
    encoding: dict[str, dict[str, Any]] = {}
    for name, data_array in ds.data_vars.items():
        if data_array.ndim == 0:
            continue
        if np.issubdtype(data_array.dtype, np.number):
            encoding[name] = {"zlib": True, "complevel": 4, "shuffle": True}
    return encoding


def write_aurora_run_netcdf(ds: xr.Dataset, output_path: str | Path, overwrite: bool = False) -> dict[str, str]:
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        return {"status": "skipped_exists", "output_nc": str(output_path)}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(str(output_path) + ".tmp.nc")
    if tmp_path.exists():
        tmp_path.unlink()

    engine = _best_netcdf_engine()
    encoding = {} if engine == "scipy" else _numeric_data_encoding(ds)

    try:
        ds.to_netcdf(tmp_path, engine=engine, encoding=encoding)
        os.replace(tmp_path, output_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    finally:
        ds.close()

    return {"status": "wrote", "output_nc": str(output_path), "netcdf_engine": engine}


def _has_all_nan(ds: xr.Dataset, name: str) -> bool:
    try:
        values = np.asarray(ds[name].values, dtype=float)
    except Exception:
        return False
    if values.size == 0:
        return True
    finite = values[np.isfinite(values)]
    return finite.size == 0


def _check_units(ds: xr.Dataset, name: str, units: str, issues: list[str]) -> None:
    if str(ds[name].attrs.get("units", "")) != units:
        issues.append(f"ERROR: {name} units must be {units!r}")


def validate_aurora_netcdf_schema(ds: xr.Dataset) -> list[str]:
    issues: list[str] = []
    for dim in REQUIRED_DIMS:
        if dim not in ds.sizes:
            issues.append(f"ERROR: missing required dimension {dim}")
    for coord in REQUIRED_COORDS:
        if coord not in ds.coords:
            issues.append(f"ERROR: missing required coordinate {coord}")
    for var in REQUIRED_SPECTRAL_VARS + REQUIRED_PT_VARS + REQUIRED_LAYER_VARS + REQUIRED_CLOUD_VARS + REQUIRED_SCALAR_VARS:
        if var not in ds.data_vars:
            issues.append(f"ERROR: missing required variable {var}")
    for attr in REQUIRED_GLOBAL_ATTRS:
        if attr not in ds.attrs:
            issues.append(f"ERROR: missing required global attribute {attr}")
    if issues:
        return issues

    if ds["wavelength_um"].dims != ("wavelength",):
        issues.append("ERROR: wavelength_um must have dimensions ('wavelength',)")
    if ds["wavenumber_cm1"].dims != ("wavelength",):
        issues.append("ERROR: wavenumber_cm1 must have dimensions ('wavelength',)")
    for name in REQUIRED_SPECTRAL_VARS:
        if ds[name].dims != ("wavelength",):
            issues.append(f"ERROR: {name} must have dimensions ('wavelength',)")
    for name in ("pressure_bar", "temperature_k"):
        if ds[name].dims != ("level",):
            issues.append(f"ERROR: {name} must have dimensions ('level',)")
    if ds["mole_fraction"].dims != ("level", "species"):
        issues.append("ERROR: mole_fraction must have dimensions ('level', 'species')")
    for name in REQUIRED_LAYER_VARS:
        if ds[name].dims != ("layer",):
            issues.append(f"ERROR: {name} must have dimensions ('layer',)")
    for name in REQUIRED_CLOUD_VARS:
        if ds[name].dims != ("layer", "wavelength"):
            issues.append(f"ERROR: {name} must have dimensions ('layer', 'wavelength')")
    if ds.sizes["layer"] != ds.sizes["level"] - 1:
        issues.append("ERROR: len(layer) must equal len(level) - 1")

    units = {
        "wavelength_um": "um",
        "wavenumber_cm1": "cm^-1",
        "level": "index",
        "layer": "index",
        "reflected_planet_star_flux_ratio": "dimensionless",
        "geometric_albedo": "dimensionless",
        "reflected_flux": ABSOLUTE_FLUX_UNITS,
        "thermal_flux": ABSOLUTE_FLUX_UNITS,
        "pressure_bar": "bar",
        "temperature_k": "K",
        "mole_fraction": "v/v",
        "layer_pressure_bar": "bar",
        "layer_temperature_k": "K",
        "cloud_optical_depth": "unitless per layer",
        "single_scattering_albedo": "dimensionless",
        "asymmetry_factor": "dimensionless",
    }
    for name, unit in units.items():
        _check_units(ds, name, unit, issues)

    wavelength = np.asarray(ds["wavelength_um"].values, dtype=float)
    if wavelength.ndim != 1 or not np.all(np.isfinite(wavelength)):
        issues.append("ERROR: wavelength_um must be finite and one-dimensional")
    elif wavelength.size > 1 and not np.all(np.diff(wavelength) > 0):
        issues.append("ERROR: wavelength_um must be strictly increasing")

    pressure = np.asarray(ds["pressure_bar"].values, dtype=float)
    if np.any(~np.isfinite(pressure)) or np.any(pressure <= 0):
        issues.append("ERROR: pressure_bar must be finite and positive")

    for name in REQUIRED_SPECTRAL_VARS + REQUIRED_PT_VARS + REQUIRED_LAYER_VARS + REQUIRED_CLOUD_VARS:
        if _has_all_nan(ds, name):
            issues.append(f"ERROR: {name} must not be all NaN")

    cloud_optical_depth = np.asarray(ds["cloud_optical_depth"].values, dtype=float)
    if np.nanmin(cloud_optical_depth) < -1.0e-12:
        issues.append("ERROR: cloud_optical_depth must be >= 0")
    single_scattering_albedo = np.asarray(ds["single_scattering_albedo"].values, dtype=float)
    if np.nanmin(single_scattering_albedo) < -1.0e-12 or np.nanmax(single_scattering_albedo) > 1.0 + 1.0e-12:
        issues.append("ERROR: single_scattering_albedo must be within [0, 1]")
    asymmetry_factor = np.asarray(ds["asymmetry_factor"].values, dtype=float)
    if np.nanmin(asymmetry_factor) < -1.0 - 1.0e-12 or np.nanmax(asymmetry_factor) > 1.0 + 1.0e-12:
        issues.append("ERROR: asymmetry_factor must be within [-1, 1]")

    reflected_units = str(ds["reflected_planet_star_flux_ratio"].attrs.get("units", ""))
    if reflected_units != "dimensionless":
        issues.append("ERROR: reflected_planet_star_flux_ratio must be dimensionless")
    albedo = np.asarray(ds["geometric_albedo"].values, dtype=float)
    finite_albedo = albedo[np.isfinite(albedo)]
    if finite_albedo.size and (np.nanmin(finite_albedo) < -1.0e-6 or np.nanmax(finite_albedo) > 1.0 + 1.0e-6):
        issues.append("WARNING: geometric_albedo is outside the usual [0, 1] range")

    return issues
