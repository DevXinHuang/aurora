# Aurora

Aurora is the PICASO 4 / RoadRunner / EGP workflow for Roman CGI reflected-light and thermal-emission experiments.

The current runtime target is PICASO 4 in the `picaso4` conda environment. Mentions of PICASO 3.4 are legacy validation references only: they describe the frozen old baseline used to confirm that the PICASO 4 workflow reproduces the earlier science decisions.

## What Is In Git

- RoadRunner/EGP source code in `roadrunner_egp/`
- PICASO 4 environment and reference-data setup scripts in `env/`
- Validation scripts and notes in `validation/`
- Project/HPC notes and flow docs
- Cleaned notebooks with outputs cleared

## What Is Not In Git

Large local data is intentionally ignored:

- `picaso4_reference/`: PICASO reference data, opacities, stellar grids, and Virga data
- `science_inputs/`: SLGRID climate/cloud files and EGP IR flux files
- generated validation outputs, temporary files, and rendered previews

Keep those folders on local disk or HPC project storage, then use the activation scripts to point Aurora at them.

## Source Route Quick Reference

Use this table when choosing which atmosphere/thermal source route to run.

| Route | Correct name | Settings | Meaning | Best use |
| --- | --- | --- | --- | --- |
| A | Pure PICASO / full PICASO | `thermal_source="picaso"` and `atmosphere_source="picaso"` | PICASO-generated atmosphere plus PICASO reflected light plus PICASO thermal emission. | Fast, flexible parameter exploration without SLGRID files. |
| B | PICASO atmosphere + EGP thermal | `thermal_source="egp"` and `atmosphere_source="picaso"` | PICASO-generated atmosphere and PICASO reflected light, paired with the matching EGP `*_IRflux.txt` thermal spectrum. | Hybrid tests that use EGP thermal emission while avoiding SLGRID PT/cloud files. |
| C | SLGRID/EGP legacy hybrid | `thermal_source="egp"` and `atmosphere_source="slgrid"` | SLGRID PT/cloud atmosphere loaded into PICASO for reflected light, paired with EGP thermal emission. | Most physically consistent with the older Roman/RoadRunner workflow. |

`EGP only` is useful as a thermal-emission validation baseline, but it is not a complete reflected-light confusion route by itself because the reflected-light calculation still comes from PICASO.

## Setup

```bash
bash env/create_picaso4_env.sh
/Users/xin/anaconda3/envs/picaso4/bin/python env/setup_picaso4_reference_data.py
source env/activate_roadrunner_picaso4.sh
```

## Smoke Test

```bash
source env/activate_roadrunner_picaso4.sh
python - <<'PY'
from roadrunner.system import summarize_slgrid_inventory
from workflows.hybrid_reflected_picaso_thermal_egp import available_egp_temperatures

print(summarize_slgrid_inventory())
print(available_egp_temperatures("31"))
PY
```

## Validation

```bash
/Users/xin/anaconda3/envs/picaso4/bin/python validation/validate_picaso4_against_legacy.py
```

The validation script compares Aurora's isolated PICASO 4 results against the frozen PICASO 3.4 baseline and writes generated run products under `validation/outputs/`.
