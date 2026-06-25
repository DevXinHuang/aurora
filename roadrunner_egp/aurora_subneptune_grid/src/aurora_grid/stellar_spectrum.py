from __future__ import annotations

from pathlib import Path
from typing import Any

from .parameters import resolve_repo_path


def stellar_spectrum_fields_from_config(config: dict[str, Any]) -> dict[str, str]:
    """Extract flattened stellar-spectrum columns from a grid config."""
    spec = config.get("stellar_spectrum")
    if spec is None and isinstance(config.get("star"), dict):
        spec = config["star"].get("stellar_spectrum")
    if not isinstance(spec, dict) or not spec.get("filename"):
        return {}
    return {
        "stellar_spectrum_filename": str(spec["filename"]),
        "stellar_spectrum_w_unit": str(spec.get("w_unit", "AA")),
        "stellar_spectrum_f_unit": str(spec.get("f_unit", "erg/(s cm2 AA)")),
    }


def stellar_spectrum_from_row(row: dict[str, Any]) -> dict[str, str] | None:
    filename = row.get("stellar_spectrum_filename")
    if not filename:
        return None
    return {
        "filename": str(filename),
        "w_unit": str(row.get("stellar_spectrum_w_unit", "AA")),
        "f_unit": str(row.get("stellar_spectrum_f_unit", "erg/(s cm2 AA)")),
    }


def resolve_stellar_spectrum_path(filename: str | Path) -> Path:
    return resolve_repo_path(filename)


def _wavelength_unit(text: str):
    from astropy import units as u

    mapping = {
        "AA": u.AA,
        "ANGSTROM": u.AA,
        "UM": u.um,
        "MICRON": u.um,
        "NM": u.nm,
    }
    key = str(text).strip().upper().replace("µ", "U")
    if key not in mapping:
        raise ValueError(f"Unsupported stellar spectrum wavelength unit {text!r}")
    return mapping[key]


def _flux_unit(text: str):
    from astropy import units as u

    normalized = str(text).strip().lower().replace(" ", "")
    if normalized in {"erg/(scm2aa)", "erg/scm2/aa", "erg/(s*cm**2*aa)"}:
        return u.erg / (u.s * u.cm**2 * u.AA)
    if normalized in {"erg/(scm2um)", "erg/scm2/um"}:
        return u.erg / (u.s * u.cm**2 * u.um)
    raise ValueError(f"Unsupported stellar spectrum flux unit {text!r}")


def configure_picaso_star(case, opa, row: dict[str, Any], *, verbose: bool = True) -> str:
    """Attach a blackbody or custom-file host star to a PICASO case."""
    from astropy import units as u

    spec = stellar_spectrum_from_row(row)
    radius = float(row["star_radius_rsun"])
    semi_major = float(row["semi_major_au"])
    if spec is not None:
        spectrum_path = resolve_stellar_spectrum_path(spec["filename"])
        if verbose:
            print(f"Using custom stellar spectrum: {spectrum_path}")
        case.star(
            opa,
            filename=str(spectrum_path),
            w_unit=_wavelength_unit(spec["w_unit"]),
            f_unit=_flux_unit(spec["f_unit"]),
            radius=radius,
            radius_unit=u.R_sun,
            semi_major=semi_major,
            semi_major_unit=u.AU,
        )
        return str(spectrum_path)
    if verbose:
        print(
            f"Using blackbody host star: Teff={float(row['star_teff_k']):.1f} K, "
            f"R={radius:.3f} R_sun"
        )
    case.star(
        opa,
        temp=float(row["star_teff_k"]),
        metal=0,
        logg=4.44,
        radius=radius,
        radius_unit=u.R_sun,
        semi_major=semi_major,
        semi_major_unit=u.AU,
    )
    return ""


def stellar_spectrum_attrs(row: dict[str, Any]) -> dict[str, str]:
    spec = stellar_spectrum_from_row(row)
    if spec is None:
        return {}
    path = resolve_stellar_spectrum_path(spec["filename"])
    return {
        "stellar_spectrum_filename": str(path),
        "stellar_spectrum_w_unit": spec["w_unit"],
        "stellar_spectrum_f_unit": spec["f_unit"],
    }
