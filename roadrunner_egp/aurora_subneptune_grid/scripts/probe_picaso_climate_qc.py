#!/usr/bin/env python
from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"

for p in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from aurora_grid.naming import picaso_tag_to_cto
from aurora_grid.picaso_runner import wavelength_grid_um
from roadrunner.runner import (
    configure_climate_inputs,
    configure_picaso_atmosphere,
    equilibrium_temperature,
    select_picaso4_preweighted_ck_file,
)
from roadrunner.system import SystemParams
from roadrunner.config import HAVE_PICASO, jdi


def arr_summary(x):
    try:
        a = np.asarray(x)
    except Exception as exc:
        return {"type": type(x).__name__, "error": repr(exc)}

    out = {
        "type": type(x).__name__,
        "shape": list(a.shape),
        "dtype": str(a.dtype),
    }
    if a.size and np.issubdtype(a.dtype, np.number):
        finite = np.isfinite(a)
        out["finite"] = int(finite.sum())
        out["size"] = int(a.size)
        if finite.any():
            out["min"] = float(np.nanmin(a))
            out["max"] = float(np.nanmax(a))
            out["mean"] = float(np.nanmean(a))
    return out


def print_key_summary(label, obj):
    print("\n" + "=" * 100)
    print(label)
    print("=" * 100)

    if obj is None:
        print("None")
        return

    print("type:", type(obj).__name__)

    if isinstance(obj, dict):
        print("keys:")
        for k in sorted(obj.keys(), key=str):
            v = obj[k]
            if isinstance(v, dict):
                print(f"  {k}: dict keys={list(v.keys())[:20]}")
            else:
                print(f"  {k}: {arr_summary(v)}")
    else:
        print(obj)


def try_get(d, key):
    if isinstance(d, dict) and key in d:
        print(f"{key}: PRESENT", arr_summary(d[key]))
    else:
        print(f"{key}: missing")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--array-index", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Send all printed diagnostics to file.
    sys.stdout = open(out_path, "w", buffering=1)

    print("PICASO CLIMATE QC PROBE")
    print("manifest:", args.manifest)
    print("array_index:", args.array_index)

    manifest = pd.read_csv(args.manifest)
    row = manifest.iloc[args.array_index].to_dict()
    print("\nManifest row:")
    print(json.dumps({k: str(v) for k, v in row.items()}, indent=2, sort_keys=True))

    output_grid = wavelength_grid_um()
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    c_to_o = picaso_tag_to_cto(str(row["c_to_o_picaso_tag"]))
    metallicity_xsolar = float(row["metallicity_xsolar"])
    log_mh = math.log10(metallicity_xsolar)

    system = SystemParams(
        teff_k=float(row["picaso_tint_k"]),
        logg_cgs=math.log10(float(row["gravity_ms2"]) * 100.0),
        rj=float(row["planet_radius_rearth"]) * 0.0892141056,
        a_au=float(row["semi_major_au"]),
        phase_deg=float(row["phase_deg"]),
        tstar_k=float(row["star_teff_k"]),
        rstar_rsun=float(row["star_radius_rsun"]),
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        bond_albedo=0.0,
        chem_c_o=c_to_o,
        chem_log_mh=log_mh,
        kzz_cgs=float(row["kzz_cm2_s"]),
        virga_fsed=float(row["fsed"]),
    )

    print("\nSystem:")
    print(system)
    print("equilibrium_temperature:", equilibrium_temperature(system))
    print("chem_log_mh:", system.chem_log_mh)
    print("system.chem_c_o:", system.chem_c_o)
    print("absolute C/O:", system.chem_c_o * 0.55)
    print("sys.kzz_cgs:", system.kzz_cgs)

    # Climate runs need the correlated-k opacity object.
    # The normal spectrum opacity object is RetrieveOpacities and lacks delta_wno.
    selected_ck_file = select_picaso4_preweighted_ck_file(system)
    print("\nUsing PICASO climate CK opacity file:")
    print(selected_ck_file)
    print("selected CK file exists:", selected_ck_file.exists())

    if not HAVE_PICASO or jdi is None:
        print("\nPICASO unavailable: roadrunner.config.HAVE_PICASO is False and jdi is None.")
        raise RuntimeError("PICASO is not available in this Python environment.")

    print("\nPICASO API signatures:")
    print("jdi.inputs:", inspect.signature(jdi.inputs))
    print("jdi.opannection:", inspect.signature(jdi.opannection))

    opa = jdi.opannection(ck_db=str(selected_ck_file), method="preweighted")

    # Important: climate=True path.
    try:
        cl_run = jdi.inputs(calculation="planet", climate=True)
        print("\nCreated cl_run = jdi.inputs(calculation='planet', climate=True)")
    except Exception as exc:
        print("\nFAILED to create climate input:", repr(exc))
        raise

    from astropy import units as u

    g_cgs = 10 ** system.logg_cgs
    cl_run.gravity(
        gravity=g_cgs,
        gravity_unit=u.cm / u.s**2,
        radius=system.rj,
        radius_unit=u.R_jup,
    )
    print("\nPlanet effective temperature setup:")
    print("planet T_eff:", float(system.teff_k))
    cl_run.star(
        opa,
        temp=system.tstar_k,
        metal=0,
        logg=4.44,
        radius=system.rstar_rsun,
        radius_unit=u.R_sun,
        semi_major=system.a_au,
        semi_major_unit=u.AU,
    )

    print("\nConfiguring atmosphere/clouds with existing AURORA/Roadrunner helper...")
    configure_picaso_atmosphere(
        cl_run,
        system,
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        verbose=True,
    )

    kz = None
    try:
        kz = cl_run.inputs["atmosphere"]["profile"]["kz"]
    except Exception:
        pass
    print("\nKzz debug:")
    print("sys.kzz_cgs:", system.kzz_cgs)
    print("cl_run.inputs['atmosphere']['profile']['kz'] exists:", kz is not None)
    if kz is not None:
        try:
            kz_array = np.asarray(kz)
            print("kz summary:", arr_summary(kz))
            print("kz first values:", kz_array.ravel()[:5].tolist())
        except Exception as exc:
            print("kz first values unavailable:", repr(exc))

    print("\nConfiguring climate solver inputs from generated Guillot PT guess...")
    climate_input_summary = configure_climate_inputs(cl_run, system)
    planet_teff = None
    try:
        planet_teff = cl_run.inputs["planet"]["T_eff"]
    except Exception:
        pass
    print('inputs["planet"]["T_eff"]:', planet_teff)
    print("pressure guess shape:", list(np.asarray(climate_input_summary["pressure"]).shape))
    print("temp_guess shape:", list(np.asarray(climate_input_summary["temp_guess"]).shape))
    print("rcb_guess:", climate_input_summary["rcb_guess"])
    print("nstr:", np.asarray(climate_input_summary["nstr"]).tolist())
    print("rfacv:", climate_input_summary["rfacv"])
    print("rfaci:", climate_input_summary["rfaci"])
    print("moistgrad:", climate_input_summary["moistgrad"])

    print_key_summary("cl_run.inputs top-level", cl_run.inputs)
    if isinstance(cl_run.inputs, dict):
        print_key_summary("cl_run.inputs['climate']", cl_run.inputs.get("climate"))
        print_key_summary("cl_run.inputs['atmosphere']", cl_run.inputs.get("atmosphere"))

    print("\nClimate method signature:")
    print(inspect.signature(cl_run.climate))

    print("\nRunning cl_run.climate(...). This may take a little while.")
    climate_out = cl_run.climate(
        opa,
        save_all_profiles=True,
        with_spec=True,
    )

    print_key_summary("climate_out", climate_out)

    print("\nTarget key presence:")
    for key in [
        "dtdp",
        "fnet/fnetir",
        "flux_balance",
        "spectrum_output",
        "pressure",
        "temperature",
        "converged",
        "all_profiles",
    ]:
        try_get(climate_out, key)

    if isinstance(climate_out, dict):
        print_key_summary("climate_out['flux_balance']", climate_out.get("flux_balance"))
        print_key_summary("climate_out['spectrum_output']", climate_out.get("spectrum_output"))

    print("\nTrying justplotit diagnostics...")
    try:
        from picaso import justplotit as jpi

        print("jpi.pt_adiabat exists:", hasattr(jpi, "pt_adiabat"))
        print("jpi.brightness_temperature exists:", hasattr(jpi, "brightness_temperature"))

        if hasattr(jpi, "pt_adiabat"):
            print("jpi.pt_adiabat signature:", inspect.signature(jpi.pt_adiabat))
            for call_name, call in [
                ("pt_adiabat(climate_out, cl_run, opa, plot=False)", lambda: jpi.pt_adiabat(climate_out, cl_run, opa, plot=False)),
                ("pt_adiabat(climate_out, cl_run, plot=False)", lambda: jpi.pt_adiabat(climate_out, cl_run, plot=False)),
            ]:
                try:
                    res = call()
                    print(call_name, "SUCCESS")
                    if isinstance(res, (tuple, list)):
                        print("  tuple length:", len(res))
                        for i, item in enumerate(res):
                            print(f"  item {i}:", arr_summary(item))
                    else:
                        print("  result:", arr_summary(res))
                    break
                except Exception as exc:
                    print(call_name, "FAILED:", repr(exc))

        if hasattr(jpi, "brightness_temperature") and isinstance(climate_out, dict) and "spectrum_output" in climate_out:
            print("jpi.brightness_temperature signature:", inspect.signature(jpi.brightness_temperature))
            for call_name, call in [
                ("brightness_temperature(spectrum_output, plot=False)", lambda: jpi.brightness_temperature(climate_out["spectrum_output"], plot=False)),
                ("brightness_temperature(spectrum_output)", lambda: jpi.brightness_temperature(climate_out["spectrum_output"])),
            ]:
                try:
                    res = call()
                    print(call_name, "SUCCESS")
                    if isinstance(res, (tuple, list)):
                        print("  tuple length:", len(res))
                        for i, item in enumerate(res):
                            print(f"  item {i}:", arr_summary(item))
                    else:
                        print("  result:", arr_summary(res))
                    break
                except Exception as exc:
                    print(call_name, "FAILED:", repr(exc))

    except Exception as exc:
        print("Could not import/use picaso.justplotit:", repr(exc))

    print("\nDONE")


if __name__ == "__main__":
    main()
