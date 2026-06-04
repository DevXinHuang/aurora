#!/usr/bin/env python
"""Validate isolated PICASO 4 outputs against the frozen PICASO 3.4 workflow.

This script deliberately runs each PICASO version in a separate conda
environment. Outputs go into timestamped directories under
``validation/outputs/`` so existing science products are not overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCIENCE_ROOT = Path("/Users/xin/Documents/Documents/College/timestep")
SCIENCE_INPUTS = REPO_ROOT / "science_inputs"
SLGRID_PT_DIR = SCIENCE_INPUTS / "slgrid" / "climate"
SLGRID_CLD_DIR = SCIENCE_INPUTS / "slgrid" / "clouds"
OUTPUT_ROOT = REPO_ROOT / "validation" / "outputs"
NOTES_PATH = REPO_ROOT / "validation" / "AURORA_VALIDATION_NOTES.md"

OLD_ENV = "picaso"
NEW_ENV = "picaso4"
ENV_PYTHON = {
    OLD_ENV: Path("/Users/xin/anaconda3/envs/picaso/bin/python"),
    NEW_ENV: Path("/Users/xin/anaconda3/envs/picaso4/bin/python"),
}
OLD_REFDATA = SCIENCE_ROOT / "picaso" / "reference"
OLD_PYSYN_CDBS = OLD_REFDATA / "grp" / "redcat" / "trds"
NEW_REFDATA = REPO_ROOT / "picaso4_reference"
NEW_PYSYN_CDBS = NEW_REFDATA / "stellar_grids"

THRESHOLD = 0.10
MAX_ALLOWED_F_REFLECT_DELTA = 0.02


def remove_user_site_packages() -> None:
    """Avoid accidentally importing user-site packages over conda packages."""
    try:
        import site

        user_sites = site.getusersitepackages()
        if isinstance(user_sites, str):
            user_sites = [user_sites]
        user_sites = {str(Path(path).resolve()) for path in user_sites}
        sys.path[:] = [
            path
            for path in sys.path
            if str(Path(path or os.getcwd()).resolve()) not in user_sites
        ]
    except Exception:
        pass


WORKER_CODE = r'''
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.constants import R_jup, au


CGI_BANDS = {
    "CGI-1": (0.546, 0.604),
    "CGI-2": (0.610, 0.710),
    "CGI-3": (0.675, 0.785),
    "CGI-4": (0.783, 0.867),
}
THRESHOLD = 0.10
LAM_GRID_UM = np.linspace(0.3, 1.0, 1200)
REFLECT_NUM_GANGLE = 4
REFLECT_NUM_TANGLE = 4
THERMAL_NUM_GANGLE = 8
THERMAL_NUM_TANGLE = 1
ATMOSPHERE_CASES = [
    {
        "case_id": "cool_vulnerable_T500_a5_phase60",
        "label": "Cool vulnerable",
        "teff_k": 500.0,
        "logg_cgs": 3.5,
        "rj": 1.0,
        "a_au": 5.0,
        "phase_deg": 60.0,
        "tstar_k": 5778.0,
        "rstar_rsun": 1.0,
        "pt_file": "SLGRID_T500_g31_m+000_CO100_fsed3_full.pt",
        "cld_file": "SLGRID_T500_g31_m+000_CO100_fsed3_picaso.cld",
    },
    {
        "case_id": "warm_comparison_T1000_a5_phase60",
        "label": "Warm comparison",
        "teff_k": 1000.0,
        "logg_cgs": 3.5,
        "rj": 1.0,
        "a_au": 5.0,
        "phase_deg": 60.0,
        "tstar_k": 5778.0,
        "rstar_rsun": 1.0,
        "pt_file": "SLGRID_T1000_g31_m+000_CO100_fsed3_full.pt",
        "cld_file": "SLGRID_T1000_g31_m+000_CO100_fsed3_picaso.cld",
    },
]
EXPECTED_OUTPUT_KEYS = ("fpfs_reflected", "fpfs_thermal", "thermal", "albedo")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--refdata", required=True, type=Path)
    parser.add_argument("--pysyn-cdbs", required=True, type=Path)
    parser.add_argument("--slgrid-pt-dir", required=True, type=Path)
    parser.add_argument("--slgrid-cld-dir", required=True, type=Path)
    return parser.parse_args()


def remove_local_repo_import_paths(repo_root: Path) -> None:
    repo_root = repo_root.resolve()
    local_picaso = repo_root / "picaso"
    cleaned = []
    for item in sys.path:
        candidate = Path(item or os.getcwd()).resolve()
        if candidate in (repo_root, local_picaso):
            continue
        cleaned.append(item)
    sys.path[:] = cleaned


def trapz_band(wavelength_um: np.ndarray, flux: np.ndarray, lo: float, hi: float) -> float:
    mask = (wavelength_um >= lo) & (wavelength_um <= hi)
    if mask.sum() < 2:
        return float("nan")
    trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(trapezoid(flux[mask], wavelength_um[mask]))


def interpolate_to_grid(native_wavelength_um: np.ndarray, native_flux: np.ndarray) -> np.ndarray:
    native_wavelength_um = np.asarray(native_wavelength_um, dtype=float)
    native_flux = np.asarray(native_flux, dtype=float)
    order = np.argsort(native_wavelength_um)
    interpolated = np.interp(
        LAM_GRID_UM,
        native_wavelength_um[order],
        native_flux[order],
        left=0.0,
        right=0.0,
    )
    return np.nan_to_num(interpolated, nan=0.0, posinf=0.0, neginf=0.0)


def output_key_report(out_ref: dict, out_em: dict) -> tuple[dict, list[str]]:
    ref_keys = sorted(str(key) for key in out_ref.keys())
    thermal_keys = sorted(str(key) for key in out_em.keys())
    combined = set(ref_keys) | set(thermal_keys)
    missing = [key for key in EXPECTED_OUTPUT_KEYS if key not in combined]
    report = {
        "reflected_output_keys": ref_keys,
        "thermal_output_keys": thermal_keys,
        "expected_output_keys": list(EXPECTED_OUTPUT_KEYS),
        "missing_expected_output_keys": missing,
    }
    warnings = []
    if missing:
        warnings.append(
            "Missing expected PICASO output key(s): "
            + ", ".join(missing)
            + ". Reflected keys="
            + ", ".join(ref_keys)
            + "; thermal keys="
            + ", ".join(thermal_keys)
        )
    return report, warnings


def run_case(
    case: dict,
    slgrid_pt_dir: Path,
    slgrid_cld_dir: Path,
    tag: str,
    output_dir: Path,
    jdi,
    blackbody,
) -> dict:
    warnings = []
    wave_range = [float(LAM_GRID_UM.min()), float(LAM_GRID_UM.max())]
    opa = jdi.opannection(wave_range=wave_range)

    model = jdi.inputs()
    gravity_cgs = 10.0 ** float(case["logg_cgs"])
    model.gravity(
        gravity=gravity_cgs,
        gravity_unit=u.cm / u.s**2,
        radius=float(case["rj"]),
        radius_unit=u.R_jup,
    )
    model.star(
        opa,
        temp=float(case["tstar_k"]),
        metal=0,
        logg=4.44,
        radius=float(case["rstar_rsun"]),
        radius_unit=u.R_sun,
        semi_major=float(case["a_au"]),
        semi_major_unit=u.AU,
    )

    pt_path = slgrid_pt_dir / case["pt_file"]
    cld_path = slgrid_cld_dir / case["cld_file"]
    if not pt_path.exists():
        raise FileNotFoundError(f"Missing PT file: {pt_path}")
    if not cld_path.exists():
        raise FileNotFoundError(f"Missing cloud file: {cld_path}")

    try:
        model.atmosphere(filename=str(pt_path), sep=r"\s+")
    except TypeError as exc:
        warnings.append(f"model.atmosphere(..., sep=...) failed with {exc!r}; trying delim_whitespace=True")
        model.atmosphere(filename=str(pt_path), delim_whitespace=True)

    cld_df = pd.read_csv(cld_path, sep=r"\s+")
    cld_df.columns = [str(column).lower() for column in cld_df.columns]
    model.clouds(df=cld_df)

    model.phase_angle(
        np.deg2rad(float(case["phase_deg"])),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    out_ref = model.spectrum(opa, calculation="reflected", as_dict=True, full_output=True)

    model.phase_angle(
        0.0,
        num_gangle=THERMAL_NUM_GANGLE,
        num_tangle=THERMAL_NUM_TANGLE,
    )
    out_em = model.spectrum(opa, calculation="thermal", as_dict=True)

    key_report, key_warnings = output_key_report(out_ref, out_em)
    warnings.extend(key_warnings)

    wno_ref = np.asarray(out_ref["wavenumber"], dtype=float)
    wavelength_ref_um = (1.0 / wno_ref) * 1.0e4

    fpfs_data = out_ref.get("fpfs_reflected")
    fpfs_reflected = None
    if fpfs_data is None:
        warnings.append("Using albedo-derived reflected fp/fs because fpfs_reflected is missing.")
    else:
        try:
            fpfs_reflected = np.squeeze(np.asarray(fpfs_data, dtype=float))
        except (TypeError, ValueError) as exc:
            warnings.append(
                "Using albedo-derived reflected fp/fs because fpfs_reflected is present "
                f"but non-numeric ({type(fpfs_data).__name__}: {fpfs_data!r}; error={exc!r})."
            )

    if fpfs_reflected is None:
        if "albedo" not in out_ref:
            raise KeyError("Neither numeric fpfs_reflected nor albedo exists in reflected output.")
        albedo = np.squeeze(np.asarray(out_ref["albedo"], dtype=float))
        rp_cm = float(case["rj"]) * R_jup.value
        a_cm = float(case["a_au"]) * au.value
        fpfs_reflected = albedo * (rp_cm / a_cm) ** 2

    stellar_flux_per_cm = np.pi * np.squeeze(blackbody(float(case["tstar_k"]), 1.0 / wno_ref))
    fp_reflected_per_um_native = fpfs_reflected * stellar_flux_per_cm * 1.0e-4
    fp_reflected = interpolate_to_grid(wavelength_ref_um, fp_reflected_per_um_native)

    if "thermal" not in out_em:
        raise KeyError(
            "Thermal output is missing key 'thermal'. Available thermal keys: "
            + ", ".join(sorted(str(key) for key in out_em.keys()))
        )
    wno_em = np.asarray(out_em["wavenumber"], dtype=float)
    wavelength_em_um = (1.0 / wno_em) * 1.0e4
    fp_thermal_per_um_native = np.squeeze(np.asarray(out_em["thermal"], dtype=float)) * 1.0e-4
    fp_thermal = interpolate_to_grid(wavelength_em_um, fp_thermal_per_um_native)

    spectra_path = output_dir / f"spectra_{tag}_{case['case_id']}.csv"
    pd.DataFrame(
        {
            "wavelength_um": LAM_GRID_UM,
            "Fp_reflected_erg_s_cm2_um": fp_reflected,
            "Fp_thermal_erg_s_cm2_um": fp_thermal,
        }
    ).to_csv(spectra_path, index=False)

    band_records = []
    for band_name, (lo, hi) in CGI_BANDS.items():
        fp_ref_band = trapz_band(LAM_GRID_UM, fp_reflected, lo, hi)
        fp_th_band = trapz_band(LAM_GRID_UM, fp_thermal, lo, hi)
        denom = fp_ref_band + fp_th_band
        f_reflect = fp_ref_band / denom if np.isfinite(denom) and denom > 0 else float("nan")
        band_records.append(
            {
                "env_tag": tag,
                "case_id": case["case_id"],
                "case_label": case["label"],
                "T_eff_K": case["teff_k"],
                "logg_cgs": case["logg_cgs"],
                "R_p_Rj": case["rj"],
                "a_AU": case["a_au"],
                "phase_deg": case["phase_deg"],
                "band": band_name,
                "band_lo_um": lo,
                "band_hi_um": hi,
                "F_reflected_erg_s_cm2": fp_ref_band,
                "F_thermal_erg_s_cm2": fp_th_band,
                "f_reflect": float(f_reflect) if np.isfinite(f_reflect) else np.nan,
                "threshold": THRESHOLD,
                "decision_reflection_important": bool(f_reflect >= THRESHOLD) if np.isfinite(f_reflect) else False,
            }
        )

    return {
        "case": case,
        "spectra_csv": str(spectra_path),
        "band_records": band_records,
        "key_report": key_report,
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ["picaso_refdata"] = str(args.refdata.resolve())
    os.environ["PYSYN_CDBS"] = str(args.pysyn_cdbs.resolve())

    remove_local_repo_import_paths(repo_root)

    report = {
        "tag": args.tag,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "picaso_refdata": os.environ.get("picaso_refdata"),
        "PYSYN_CDBS": os.environ.get("PYSYN_CDBS"),
        "SLGRID_PT_DIR": str(args.slgrid_pt_dir.resolve()),
        "SLGRID_CLD_DIR": str(args.slgrid_cld_dir.resolve()),
        "cases": [],
        "warnings": [],
        "errors": [],
    }

    try:
        import picaso
        from picaso import justdoit as jdi
        from picaso.fluxes import blackbody

        import_path = Path(getattr(picaso, "__file__", "")).resolve()
        local_source = repo_root / "picaso"
        if import_path.is_relative_to(local_source):
            raise RuntimeError(f"PICASO import resolved to local source checkout: {import_path}")

        report["picaso_import_path"] = str(import_path)
        report["picaso_version"] = importlib.metadata.version("picaso")
    except Exception as exc:
        report["errors"].append({"stage": "import", "error": repr(exc), "traceback": traceback.format_exc()})
        (output_dir / f"report_{args.tag}.json").write_text(json.dumps(report, indent=2))
        return 2

    all_band_records = []
    for case in ATMOSPHERE_CASES:
        try:
            case_report = run_case(
                case,
                args.slgrid_pt_dir.resolve(),
                args.slgrid_cld_dir.resolve(),
                args.tag,
                output_dir,
                jdi,
                blackbody,
            )
            report["cases"].append(case_report)
            report["warnings"].extend(case_report["warnings"])
            all_band_records.extend(case_report["band_records"])
        except Exception as exc:
            report["errors"].append(
                {
                    "stage": "case",
                    "case_id": case["case_id"],
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )

    if all_band_records:
        band_path = output_dir / f"band_integrated_reflected_fraction_{args.tag}.csv"
        pd.DataFrame(all_band_records).to_csv(band_path, index=False)
        report["band_csv"] = str(band_path)

    report_path = output_dir / f"report_{args.tag}.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"tag": args.tag, "report": str(report_path), "errors": len(report["errors"])}, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare frozen PICASO 3.4 results against isolated PICASO 4 results."
    )
    parser.add_argument(
        "--run-id",
        default=datetime.now().strftime("%Y%m%d_%H%M%S"),
        help="Output run identifier. Defaults to a timestamp.",
    )
    parser.add_argument("--old-env", default=OLD_ENV)
    parser.add_argument("--new-env", default=NEW_ENV)
    parser.add_argument("--skip-old", action="store_true")
    parser.add_argument("--skip-new", action="store_true")
    return parser.parse_args()


def run_conda_worker(
    *,
    tag: str,
    env_name: str,
    refdata: Path,
    pysyn_cdbs: Path,
    slgrid_pt_dir: Path = SLGRID_PT_DIR,
    slgrid_cld_dir: Path = SLGRID_CLD_DIR,
    run_dir: Path,
    worker_path: Path,
) -> dict:
    process_env = os.environ.copy()
    process_env.pop("PYTHONPATH", None)
    process_env["PYTHONNOUSERSITE"] = "1"
    process_env["picaso_refdata"] = str(refdata)
    process_env["PYSYN_CDBS"] = str(pysyn_cdbs)
    process_env["SLGRID_PT_DIR"] = str(slgrid_pt_dir)
    process_env["SLGRID_CLD_DIR"] = str(slgrid_cld_dir)
    python_executable = ENV_PYTHON.get(env_name, Path(f"/Users/xin/anaconda3/envs/{env_name}/bin/python"))
    if not python_executable.exists():
        raise FileNotFoundError(f"Could not find Python executable for {env_name}: {python_executable}")
    process_env["PATH"] = f"{python_executable.parent}{os.pathsep}{process_env.get('PATH', '')}"
    process_env["CONDA_PREFIX"] = str(python_executable.parents[1])
    process_env["CONDA_DEFAULT_ENV"] = env_name

    cmd = [
        str(python_executable),
        str(worker_path),
        "--tag",
        tag,
        "--output-dir",
        str(run_dir),
        "--repo-root",
        str(REPO_ROOT),
        "--refdata",
        str(refdata),
        "--pysyn-cdbs",
        str(pysyn_cdbs),
        "--slgrid-pt-dir",
        str(slgrid_pt_dir),
        "--slgrid-cld-dir",
        str(slgrid_cld_dir),
    ]
    completed = subprocess.run(
        cmd,
        cwd=run_dir,
        env=process_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    (run_dir / f"{tag}_worker_stdout.txt").write_text(completed.stdout)
    (run_dir / f"{tag}_worker_stderr.txt").write_text(completed.stderr)

    report_path = run_dir / f"report_{tag}.json"
    report = {}
    if report_path.exists():
        report = json.loads(report_path.read_text())
    else:
        report = {
            "tag": tag,
            "errors": [
                {
                    "stage": "env_python_run",
                    "error": f"Worker did not create {report_path.name}",
                    "returncode": completed.returncode,
                }
            ],
        }
    report["conda_env"] = env_name
    report["returncode"] = completed.returncode
    return report


def compare_band_outputs(run_dir: Path) -> dict:
    import csv

    old_path = run_dir / "band_integrated_reflected_fraction_old.csv"
    new_path = run_dir / "band_integrated_reflected_fraction_picaso4.csv"
    if not old_path.exists() or not new_path.exists():
        return {
            "status": "not_run",
            "reason": "Missing old or picaso4 band-integrated CSV.",
            "close_enough": False,
        }

    def read_rows(path: Path) -> list[dict]:
        with path.open(newline="") as handle:
            return list(csv.DictReader(handle))

    def as_bool(value: str) -> bool:
        return str(value).strip().lower() in {"true", "1", "yes"}

    old_by_key = {(row["case_id"], row["band"]): row for row in read_rows(old_path)}
    new_by_key = {(row["case_id"], row["band"]): row for row in read_rows(new_path)}
    shared_keys = sorted(set(old_by_key) & set(new_by_key))

    rows = []
    max_abs_delta = 0.0
    decision_flips = 0
    for case_id, band in shared_keys:
        old = old_by_key[(case_id, band)]
        new = new_by_key[(case_id, band)]
        f_old = float(old["f_reflect"])
        f_new = float(new["f_reflect"])
        delta = f_new - f_old
        abs_delta = abs(delta)
        old_decision = as_bool(old["decision_reflection_important"])
        new_decision = as_bool(new["decision_reflection_important"])
        decision_flip = old_decision != new_decision
        max_abs_delta = max(max_abs_delta, abs_delta)
        decision_flips += int(decision_flip)
        rows.append(
            {
                "case_id": case_id,
                "band": band,
                "f_reflect_old": f_old,
                "f_reflect_picaso4": f_new,
                "delta_f_reflect": delta,
                "abs_delta_f_reflect": abs_delta,
                "decision_old": old_decision,
                "decision_picaso4": new_decision,
                "decision_flip": decision_flip,
            }
        )

    comparison_path = run_dir / "band_integrated_comparison.csv"
    with comparison_path.open("w", newline="") as handle:
        fieldnames = [
            "case_id",
            "band",
            "f_reflect_old",
            "f_reflect_picaso4",
            "delta_f_reflect",
            "abs_delta_f_reflect",
            "decision_old",
            "decision_picaso4",
            "decision_flip",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    close_enough = bool(decision_flips == 0 and max_abs_delta <= MAX_ALLOWED_F_REFLECT_DELTA)
    return {
        "status": "compared",
        "comparison_csv": str(comparison_path),
        "rows_compared": int(len(rows)),
        "max_abs_delta_f_reflect": max_abs_delta,
        "decision_flips": decision_flips,
        "close_enough": close_enough,
    }


def make_plots(run_dir: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        return [f"Plotting skipped: {exc!r}"]

    warnings = []
    old_files = sorted(run_dir.glob("spectra_old_*.csv"))
    for old_file in old_files:
        case_id = old_file.name.removeprefix("spectra_old_").removesuffix(".csv")
        new_file = run_dir / f"spectra_picaso4_{case_id}.csv"
        if not new_file.exists():
            warnings.append(f"Skipping plot for {case_id}; missing {new_file.name}.")
            continue

        try:
            old = np.genfromtxt(old_file, delimiter=",", names=True)
            new = np.genfromtxt(new_file, delimiter=",", names=True)
        except Exception as exc:
            warnings.append(f"Skipping plot for {case_id}; could not read spectra CSVs: {exc!r}.")
            continue

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(
            old["wavelength_um"],
            old["Fp_reflected_erg_s_cm2_um"],
            label="old PICASO 3.4 reflected",
            color="tab:blue",
        )
        ax.plot(
            old["wavelength_um"],
            old["Fp_thermal_erg_s_cm2_um"],
            label="old PICASO 3.4 thermal",
            color="tab:red",
        )
        ax.plot(
            new["wavelength_um"],
            new["Fp_reflected_erg_s_cm2_um"],
            label="PICASO 4 reflected",
            color="tab:cyan",
            linestyle="--",
        )
        ax.plot(
            new["wavelength_um"],
            new["Fp_thermal_erg_s_cm2_um"],
            label="PICASO 4 thermal",
            color="tab:orange",
            linestyle="--",
        )
        ax.set_xlabel("Wavelength (um)")
        ax.set_ylabel("Planet flux (erg s^-1 cm^-2 um^-1)")
        ax.set_title(case_id)
        ax.set_yscale("symlog", linthresh=1e-30)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(run_dir / f"spectra_compare_{case_id}.png", dpi=160)
        plt.close(fig)
    return warnings


def write_text_summary(run_dir: Path, reports: dict, comparison: dict, plot_warnings: list[str]) -> None:
    lines = [
        "Aurora Validation Summary",
        "====================================",
        "",
        f"Run directory: {run_dir}",
        f"Old env: {reports.get('old', {}).get('conda_env', OLD_ENV)}",
        f"New env: {reports.get('picaso4', {}).get('conda_env', NEW_ENV)}",
        "",
        "Environment Reports",
        "-------------------",
    ]
    for tag in ("old", "picaso4"):
        report = reports.get(tag)
        if not report:
            lines.append(f"- {tag}: not run")
            continue
        lines.extend(
            [
                f"- {tag}: returncode={report.get('returncode')}",
                f"  picaso_version={report.get('picaso_version')}",
                f"  picaso_import_path={report.get('picaso_import_path')}",
                f"  picaso_refdata={report.get('picaso_refdata')}",
                f"  PYSYN_CDBS={report.get('PYSYN_CDBS')}",
                f"  SLGRID_PT_DIR={report.get('SLGRID_PT_DIR')}",
                f"  SLGRID_CLD_DIR={report.get('SLGRID_CLD_DIR')}",
                f"  errors={len(report.get('errors', []))}",
                f"  warnings={len(report.get('warnings', []))}",
            ]
        )
        for warning in report.get("warnings", []):
            lines.append(f"  WARNING: {warning}")
        for error in report.get("errors", []):
            lines.append(f"  ERROR: {error.get('stage')}: {error.get('error')}")

    lines.extend(
        [
            "",
            "Comparison",
            "----------",
            json.dumps(comparison, indent=2),
        ]
    )
    if plot_warnings:
        lines.extend(["", "Plot Warnings", "-------------", *plot_warnings])
    (run_dir / "validation_summary.txt").write_text("\n".join(lines) + "\n")


def write_validation_notes(run_dir: Path, reports: dict, comparison: dict) -> None:
    status_line = "not close enough for production"
    if comparison.get("status") == "compared" and comparison.get("close_enough"):
        status_line = "close enough for Aurora validation"
    elif comparison.get("status") == "not_run":
        status_line = "validation incomplete"

    old_report = reports.get("old", {})
    new_report = reports.get("picaso4", {})
    notes = f"""# Aurora Notes

Last validation run: `{run_dir.name}`

## What Changed

- Legacy baseline environment remains frozen: conda env `picaso`, PICASO `{old_report.get('picaso_version', 'unknown')}`, refdata `{OLD_REFDATA}`.
- Current Aurora environment: conda env `picaso4`, PICASO `{new_report.get('picaso_version', 'pending')}`, refdata `{NEW_REFDATA}`.
- PICASO 4 optional data installed: `ck04models`, `phoenix`, default Virga Mieff files, and Virga aggregate Mieff files.
- Validation science inputs are read from local `{SCIENCE_INPUTS}`, copied from frozen `{SCIENCE_ROOT}`; validation outputs stay in this Aurora folder.
- New validation outputs are written only under `validation/outputs/<run_id>/`.
- Base conda still restores the old PICASO variables through its existing activation hook; this was left untouched to preserve production behavior.

## Commands

```bash
bash env/create_picaso4_env.sh
/Users/xin/anaconda3/envs/picaso4/bin/python env/setup_picaso4_reference_data.py
/Users/xin/anaconda3/envs/picaso4/bin/python validation/validate_picaso4_against_legacy.py
```

## Validation Cases

- Cool vulnerable case: `Teff=500 K`, `a=5 AU`, `phase=60 deg`, `logg=3.5`, `radius=1 Rj`, Sun-like star.
- Warm comparison case: `Teff=1000 K`, `a=5 AU`, `phase=60 deg`, `logg=3.5`, `radius=1 Rj`, Sun-like star.
- Roman CGI bands: `CGI-1=0.546-0.604 um`, `CGI-2=0.610-0.710 um`, `CGI-3=0.675-0.785 um`, `CGI-4=0.783-0.867 um`.
- Reflection threshold: `f_reflect >= 0.10`, where `f_reflect = F_reflected / (F_reflected + F_thermal)`.

## Current Result

- Status: **{status_line}**
- Comparison: `{comparison.get('status')}`
- Max absolute `f_reflect` difference: `{comparison.get('max_abs_delta_f_reflect', 'n/a')}`
- Decision flips: `{comparison.get('decision_flips', 'n/a')}`
- Comparison CSV: `{comparison.get('comparison_csv', 'n/a')}`

## API / Output Differences

See `{run_dir / 'validation_summary.txt'}` and `report_old.json` / `report_picaso4.json` for full output-key diagnostics. Expected keys checked: `fpfs_reflected`, `fpfs_thermal`, `thermal`, and `albedo`.
"""
    NOTES_PATH.write_text(notes)


def main() -> int:
    remove_user_site_packages()
    args = parse_args()
    run_dir = OUTPUT_ROOT / args.run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    worker_path = run_dir / "_picaso_validation_worker.py"
    worker_path.write_text(WORKER_CODE)

    reports = {}
    if not args.skip_old:
        reports["old"] = run_conda_worker(
            tag="old",
            env_name=args.old_env,
            refdata=OLD_REFDATA,
            pysyn_cdbs=OLD_PYSYN_CDBS,
            run_dir=run_dir,
            worker_path=worker_path,
        )
    if not args.skip_new:
        reports["picaso4"] = run_conda_worker(
            tag="picaso4",
            env_name=args.new_env,
            refdata=NEW_REFDATA,
            pysyn_cdbs=NEW_PYSYN_CDBS,
            run_dir=run_dir,
            worker_path=worker_path,
        )

    comparison = compare_band_outputs(run_dir)
    plot_warnings = make_plots(run_dir)
    write_text_summary(run_dir, reports, comparison, plot_warnings)
    write_validation_notes(run_dir, reports, comparison)

    print(f"Validation outputs: {run_dir}")
    print(f"Comparison status: {comparison.get('status')}")
    print(f"Close enough: {comparison.get('close_enough')}")

    any_errors = any(report.get("errors") for report in reports.values())
    if any_errors or not comparison.get("close_enough", False):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
