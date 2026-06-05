# RoadRunner/EGP Flow

Aurora now has one clean path for the copied RoadRunner/EGP setup:

```text
aurora/
  science_inputs/
    egp/irflux/
    slgrid/climate/
    slgrid/clouds/
  roadrunner_egp/
    notebooks/
    roadrunner/
    workflows/
    results/
```

For the source-selection flowchart, see:

`ROADRUNNER_SOURCE_FLOWCHART.md`

## Clean Route Summary

| Route | Correct name | Settings | Meaning | Best use |
| --- | --- | --- | --- | --- |
| A | Pure PICASO / full PICASO | `thermal_source="picaso"` and `atmosphere_source="picaso"` | PICASO-generated atmosphere plus PICASO reflected light plus PICASO thermal emission. | Fast, flexible parameter exploration. |
| B | PICASO atmosphere + EGP thermal | `thermal_source="egp"` and `atmosphere_source="picaso"` | PICASO-generated atmosphere and PICASO reflected light, paired with the matching EGP `*_IRflux.txt` thermal spectrum. | Hybrid tests that use EGP thermal emission while avoiding SLGRID PT/cloud files. |
| C | SLGRID/EGP legacy hybrid | `thermal_source="egp"` and `atmosphere_source="slgrid"` | SLGRID PT/cloud atmosphere loaded into PICASO for reflected light, paired with EGP thermal emission. | Most physically consistent with the older Roman/RoadRunner workflow. |

Naming note: `EGP only` should mean the standalone EGP thermal baseline. It is useful for validation or legacy thermal comparison, but it is not a complete reflected-light confusion route by itself.

## Use PICASO4

```bash
cd /Users/xin/Documents/Documents/College/aurora
source env/activate_roadrunner_picaso4.sh
python - <<'PY'
from workflows.hybrid_reflected_picaso_thermal_egp import available_hybrid_temperatures

print(available_hybrid_temperatures("31"))
PY
```

This uses:

- PICASO4 reference data: `picaso4_reference/`
- copied EGP IRflux files: `science_inputs/egp/irflux/`
- full copied SLGRID grid: `science_inputs/slgrid/`

RoadRunner can now choose its sources explicitly:

```python
from workflows.hybrid_reflected_picaso_thermal_egp import SystemParams, evaluate_hybrid_case

case = SystemParams(teff_k=1000, logg_cgs=3.5, rj=1.0, a_au=10.0, phase_deg=60.0)

# Full PICASO: no SLGRID PT/cloud files.
df_picaso = evaluate_hybrid_case(
    case,
    thermal_source="picaso",
    atmosphere_source="picaso",
    cloud_model="virga",
)

# EGP thermal file, but generated PICASO atmosphere for reflected light.
df_egp = evaluate_hybrid_case(
    case,
    thermal_source="egp",
    atmosphere_source="picaso",
)
```

## Notebook

Open this notebook with the `Python (picaso4)` kernel:

`roadrunner_egp/notebooks/run_roadrunner_phase_60_egp_g31_hybrid_picaso4.ipynb`

It is the PICASO4-local version of:

`/Users/xin/Documents/Documents/College/timestep/2_9_2026/run_roadrunner_phase_60_egp_g31_hybrid.ipynb`

The notebook loads the existing phase-60 hybrid CSV from `roadrunner_egp/results/` by default. Set `LOAD_EXISTING_CSV = False` inside the notebook to recompute the full grid using PICASO4.

## Use Original timestep

```bash
cd /Users/xin/Documents/Documents/College/aurora
source env/activate_roadrunner_timestep.sh
```

This points Python and the data variables back to:

`/Users/xin/Documents/Documents/College/timestep`

The full SLGRID cloud grid is now also copied locally, so this profile is only needed when you intentionally want to compare against the original timestep tree.

## Names

Old workflow names from `timestep/2_9_2026` were copied into clearer module names:

- `egp_hybrid_phase0.py` -> `hybrid_reflected_picaso_thermal_egp.py`
- `egp_phase_angle_sweep.py` -> `phase_angle_sweep.py`
- `egp_thermal_comparison.py` -> `compare_roadrunner_egp_thermal.py`
- `james_egp_picaso_phase60.py` -> `compare_james_picaso_thermal.py`

The original `roadrunner` package import is preserved so notebook code can still use:

```python
from roadrunner import SystemParams, evaluate_case, run_grid_parallel
```
