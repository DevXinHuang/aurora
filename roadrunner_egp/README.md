# RoadRunner + EGP Integration

This folder is the Aurora copy of the RoadRunner/EGP workflow from:

`/Users/xin/Documents/Documents/College/timestep`

It keeps the original `roadrunner` import name, but moves the workflow scripts into clearer names:

- `workflows/hybrid_reflected_picaso_thermal_egp.py`: PICASO reflected light plus EGP IRflux thermal emission.
- `workflows/phase_angle_sweep.py`: reflected-fraction sweep over phase angle.
- `workflows/compare_roadrunner_egp_thermal.py`: direct thermal comparison between RoadRunner/PICASO and EGP IRflux.
- `workflows/compare_james_picaso_thermal.py`: James-style PICASO thermal comparison against the hybrid grid.

The PICASO4 phase-60 notebook equivalent to the old timestep notebook is:

`notebooks/run_roadrunner_phase_60_egp_g31_hybrid_picaso4.ipynb`

It uses the `Python (picaso4)` kernel and forces all runtime paths to the local `aurora/science_inputs` and `aurora/picaso4_reference` folders.

## Profiles

Use Aurora inputs:

```bash
source env/activate_roadrunner_picaso4.sh
```

Use the original timestep inputs:

```bash
source env/activate_roadrunner_timestep.sh
```

The copied package reads these environment variables:

- `picaso_refdata`
- `PYSYN_CDBS`
- `SLGRID_PT_DIR`
- `SLGRID_CLD_DIR`
- `EGP_IRFLUX_DIR`
- `ROADRUNNER_SCIENCE_INPUTS`

## Python Smoke Test

```bash
source env/activate_roadrunner_picaso4.sh
python - <<'PY'
from roadrunner.system import summarize_slgrid_inventory
from workflows.hybrid_reflected_picaso_thermal_egp import available_egp_temperatures

print(summarize_slgrid_inventory())
print(available_egp_temperatures("31"))
PY
```

## Choosing EGP vs Full PICASO

The workflow now has two separate switches:

- `thermal_source="egp"`: use the matching EGP `*_IRflux.txt` file for thermal emission.
- `thermal_source="picaso"`: run thermal emission directly through PICASO.
- `atmosphere_source="slgrid"`: read the SLGRID PT/cloud files.
- `atmosphere_source="picaso"`: do not use SLGRID; build a Guillot PT profile, Visscher chemistry, and Virga clouds inside PICASO.

Example full-PICASO run:

```python
from workflows.hybrid_reflected_picaso_thermal_egp import SystemParams, evaluate_hybrid_case

case = SystemParams(teff_k=1000, logg_cgs=3.5, rj=1.0, a_au=10.0, phase_deg=60.0)
df = evaluate_hybrid_case(
    case,
    thermal_source="picaso",
    atmosphere_source="picaso",
    cloud_model="virga",
)
```

Example EGP-thermal-file run with generated PICASO atmosphere for reflected light:

```python
df = evaluate_hybrid_case(
    case,
    thermal_source="egp",
    atmosphere_source="picaso",
)
```
