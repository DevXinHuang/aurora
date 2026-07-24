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
source env/activate_local_picaso4.sh

# Optional, after manually placing the large data files in picaso4_reference/:
python env/setup_picaso4_reference_data.py --check-only
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
source env/activate_local_picaso4.sh
python validation/validate_picaso4_against_legacy.py
```

The validation script compares Aurora's isolated PICASO 4 results against the frozen PICASO 3.4 baseline and writes generated run products under `validation/outputs/`.

## PICASO grid runs (HPC)

Large reflected-light grids use a **two-stage** workflow: converge climate once per
unique gravity/atmosphere/orbit (`climate_group_index`), then compute spectra for
every requested radius and phase.

```bash
# Example: Cahoy 2010 replication (304 spectra, 16 climates)
bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh

# Example: supported v1 grid (960,000 spectra, 40,000 climates)
bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh \
  "$(pwd)" aurora_subneptune_v1
```

### Sub-Neptune grids (non-Cahoy)

| Grid | Spectra | Climate groups | Role |
| --- | ---: | ---: | --- |
| `smoke_test_aurora_subneptune` | 6 | 2 | Minimal plumbing check |
| `hpc_validation_aurora_subneptune` | 1,728 | 576 | Testing grid for HPC timing, stability, and QC |
| `aurora_subneptune_v1` | 960,000 | 40,000 | Supported production science grid (gravity climates) |
| `aurora_subneptune_v0` | 276,480 | 46,080 | Legacy full-grid baseline |

The nominal Cartesian axes for `aurora_subneptune_v1` contain 1,080,000 spectra
and 45,000 gravity-based climate groups. Manifest generation omits the
unsupported PICASO 4 correlated-k pair `metallicity_xsolar = 100` with
`c_to_o_xsolar = 2.0` because `sonora_2121grid_feh2.0_co1.10.hdf5` is
unavailable. The runnable grid therefore contains **960,000 spectra in 40,000
climate groups**, with four radii and six phases generated from every climate.

Planned full `aurora_subneptune_v1` parameter axes:

- Stars (`teff_k`, `radius_rsun`): `(3500,0.45)`, `(4000,0.63)`, `(5000,0.80)`, `(6000,1.00)`, `(7000,1.70)`
- `planet_radius_rearth`: `1.6, 2.0, 2.5, 3.0`
- `gravity_ms2`: `5, 10, 15, 25, 30`
- `metallicity_xsolar`: `1, 10, 100`
- `c_to_o_xsolar`: `0.5, 1.0, 2.0`
- `kzz_cm2_s`: `1e9, 1e11`
- `cloud_fraction`: `0, 0.5, 0.75, 0.9, 1`; `fsed`: `0.3, 1, 3, 6, 8`
- `insolation_searth`: `0.35, 0.7, 1.0, 1.5`; `phase_deg`: `0, 30, 60, 90, 120, 150`
- `Tint` is fixed at `50 K`; `equilibrium_temperature_k` is still calculated
  independently from stellar irradiation and stored as metadata.
- Planet mass is derived per spectrum as `M = gR²/G`; it is metadata, not a
  climate axis. Radius and phase are spectrum-only axes.

## Tint-sensitivity analysis

The 36-run Tint experiment has a portable analysis pipeline under
`src/aurora_grid/tint`. Transferred NetCDF files are discovered by their
embedded `run_id`; their filenames and transfer directory do not need to match
the HPC paths recorded at model runtime.

Run preflight before generating publication outputs:

```bash
export PYTHONPATH="$PWD/src:$PWD/roadrunner_egp${PYTHONPATH:+:$PYTHONPATH}"

python -m aurora_grid.tint \
  --config params/tint_sensitivity_36.yaml \
  preflight \
  --input-dir /path/to/36_netcdfs \
  --output results/tint_sensitivity_preflight

python -m aurora_grid.tint \
  --config params/tint_sensitivity_36.yaml \
  figures \
  --input-dir /path/to/36_netcdfs \
  --mode final \
  --output results/tint_sensitivity_final
```

`final` mode requires all 36 schema-v1.3 files, climate convergence, and all
12 Tint=25/100 endpoint pairs. `partial` mode accepts missing or nonconverged
models for diagnostics and watermarks every figure. The interactive wrapper is
`analysis/tint_sensitivity_figures/tint_sensitivity_framework.ipynb`.

See [roadrunner_egp/aurora_subneptune_grid/README.md](roadrunner_egp/aurora_subneptune_grid/README.md)
and [HPC_INSTALL.md](HPC_INSTALL.md) for details.
