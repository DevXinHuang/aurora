# Aurora Sub-Neptune PICASO Grid Runner

Production grid runner for Aurora Path A: sub-Neptune reflected-light spectra with
PICASO 4 climate atmospheres and Virga clouds. Each completed spectrum is one
restartable NetCDF file under `outputs/<model_name>/nc/`.

## Recommended workflow: climate first, then spectra

**Do not** run full `picaso_climate` inside every array task if the manifest sweeps
phase angle. Phase is viewing geometry only — the pressure–temperature profile does
not change with phase.

| Stage | What runs | Array size | Typical cost |
| --- | --- | --- | --- |
| **1 — Climate** | Converge PICASO climate once per `climate_group_index` | `N_climate` | Heavy (~15–45 min / group) |
| **2 — Spectrum** | Load cached PT, compute reflected spectrum per manifest row | `N_rows` | Light (~2–10 min / row) |

Every manifest produced by `make_manifest.py` (or `make_cahoy2010_manifest.py`)
includes a `climate_group_index` column. Rows that share the same planet, star,
cloud, chemistry, and orbit — but differ in `phase_deg` — share one climate group.

```text
outputs/<model_name>/
  climate_cache/climate_00.npz … climate_NN.npz   ← stage 1
  nc/run_000000.nc …                              ← stage 2 (304–1,080,000 files)
```

### Submit any grid (smoke → validation → full)

From the repo root:

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh \
  "$(pwd)" <model_name>
```

| `model_name` | Spectrum rows | Climate groups | Purpose |
| --- | ---: | ---: | --- |
| `smoke_test_aurora_subneptune` | 6 | 2 | Plumbing |
| `hpc_validation_aurora_subneptune` | 1,728 | 576 | HPC timing / QC |
| `aurora_cahoy2010_replication_v0` | 304 | 16 | Cahoy et al. 2010 1:1 |
| `aurora_subneptune_v1` | 1,080,000 | 180,000 | Full science grid (Zarah updates) |
| `aurora_subneptune_v0` | 276,480 | 46,080 | Legacy full-grid baseline |

### Sub-Neptune grid sets (non-Cahoy)

The two non-Cahoy grids currently used for development/testing are:

| Grid | Spectra | Climate groups | Role |
| --- | ---: | ---: | --- |
| `smoke_test_aurora_subneptune` | 6 | 2 | Minimal plumbing check before larger runs |
| `hpc_validation_aurora_subneptune` | 1,728 | 576 | Testing grid for HPC timing, stability, and QC |

Planned final production run is `aurora_subneptune_v1`:

| Parameter | Values |
| --- | --- |
| Host star Teff + radius | 3500/0.45, 4000/0.63, 5000/0.80, 6000/1.00, 7000/1.70 |
| Planet radius (R_earth) | 1.6, 2.0, 2.5, 3.0 |
| Planet mass (M_earth) | 2.037, 4.073, 6.110, 10.183, 12.220 |
| Metallicity (x solar) | 1, 10, 100 |
| C/O (x solar) | 0.5, 1.0, 2.0 |
| Kzz (cm²/s) | 1e9, 1e11 |
| Cloud fraction | 0, 0.5, 0.75, 0.9, 1 |
| fsed | 0.3, 1, 3, 6, 8 |
| Insolation (S_earth) | 0.35, 0.7, 1.0, 1.5 |
| Phase (deg) | 0, 30, 60, 90, 120, 150 |

Gravity note: `gravity_ms2` is computed per row from mass and radius
(`g = GM/R²`) for PICASO. Mass values match legacy `g = 5–30 m/s²` at
`R = 2 R⊕` and are stored in manifest/NetCDF for comparison to measured values.

Cahoy shortcut:

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh
```

Stage 2 waits on stage 1 (`--dependency=afterok`). Large grids (>1,000 tasks)
are submitted in batches automatically.

### Manual stage commands

```bash
source env/activate_aurora_picaso4_job.sh

# Generate manifest (adds climate_group_index)
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/hpc_validation.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv

# Stage 1 — one climate group locally
python roadrunner_egp/aurora_subneptune_grid/scripts/run_climate_cache_chunk.py \
  --manifest roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv \
  --climate-group-index 0

# Stage 2 — one spectrum row
python roadrunner_egp/aurora_subneptune_grid/scripts/run_spectrum_from_cache_chunk.py \
  --manifest roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv \
  --array-index 0 \
  --model-name hpc_validation_aurora_subneptune
```

### Legacy single-stage (not recommended)

`run_grid_chunk.py --use-picaso-climate` still works for one-off tests but
re-runs climate for every phase. Slurm templates `run_aurora_subneptune_grid.slurm`
and `validation_aurora_subneptune_grid.slurm` are disabled — use
`submit_two_stage_grid.sh` instead.

Guillot fast path (`picaso_guillot`, no climate convergence) remains available via
`run_grid_chunk.py` without caching for quick smoke tests.

### Guillot smoke (not full climate)

`aurora_cahoy_solar_smoke_v0` (48 cases) uses `picaso_guillot` for fast plumbing
checks (~1 min/task). It does **not** converge PICASO climate. For science-quality
Cahoy spectra, use `aurora_cahoy2010_replication_v0` and the two-stage submit
script above.

### Obsolete configs

| Config | Why not to use |
| --- | --- |
| `aurora_cahoy_solar_climate_v0` | 768 single-stage runs; superseded by `aurora_cahoy2010_replication_v0` |
| `run_aurora_subneptune_grid.slurm` | Re-runs climate per phase |
| `run_weekend_grid_800.slurm` | Legacy weekend shard, not the production grid |

---

## Science goal

Whether sub-Neptunes near the Fulton radius valley can masquerade as terrestrial
worlds in reflected-light spectra (HWO).

## Parameter space (full grid)

| Parameter | Values | Steps |
| --- | --- | ---: |
| Host star Teff + radius | 3500, 4000, 5000, 6000, 7000 K | 5 |
| Planet radius | 1.6, 2.0, 2.5, 3.0 R_earth | 4 |
| Planet mass | 2.037, 4.073, 6.110, 10.183, 12.220 M_earth | 5 |
| Metallicity | 1, 10, 100× solar | 3 |
| C/O | 0.5, 1.0, 2.0× solar | 3 |
| Kzz | 1e9, 1e11 cm²/s | 2 |
| Cloud fraction | 0, 0.5, 0.75, 0.9, 1 | 5 |
| fsed | 0.3, 1, 3, 6, 8 | 5 |
| Insolation | 0.35, 0.7, 1.0, 1.5 S⊕ | 4 |
| Phase | 0, 30, 60, 90, 120, 150° | 6 |

Full Cartesian product: **1,080,000** spectra = **180,000** climate groups × **6** phases.

## Environment

```bash
source env/activate_aurora_picaso4_job.sh
```

| | Mac | HPC |
| --- | --- | --- |
| Python | `.venv-picaso4` | `micromamba` env `picaso4` |
| Paths | `activate_roadrunner_picaso4.sh` | same |
| Grid extras | `activate_aurora_grid_runtime.sh` | same |

## Cahoy et al. 2010 replication

Config: `params/aurora_cahoy2010_replication_v0.yaml`  
Manifest: `scripts/make_cahoy2010_manifest.py` (304 rows, 16 climates)

- 4 planet types (Jupiter 1×/3×, Neptune 10×/30×)
- 4 separations (0.8, 2, 5, 10 AU) with Cahoy Table 1 clouds
- 19 phases (0°–180° every 10°)
- Solar spectrum: `data/stellar_spectra/SOLARSPECTRUM.DAT`
- Each row has `cahoy_reference_name` (e.g. `Neptune_10x_2AU_60deg.dat`)

## Customizing YAML configs

Edit lists under `params/*.yaml`, regenerate manifest, re-submit:

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config <your.yaml> --out <manifest.csv>
# Prints total_rows and climate_groups
```

## Post-run QC

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/run_postrun_qc.py \
  --output-root roadrunner_egp/aurora_subneptune_grid/outputs/<model>/nc \
  --grid-manifest roadrunner_egp/aurora_subneptune_grid/manifests/<model>_manifest.csv
```

## Cahoy 2010 validation (after replication run)

Install reference spectra once:

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/install_cahoy2010_reference.sh
```

Batch compare all finished NetCDF files:

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/run_cahoy2010_compare.py --plot
```

Or open the notebook:

`roadrunner_egp/aurora_subneptune_grid/notebooks/compare_cahoy2010_spectra.ipynb`

Outputs land in `outputs/aurora_cahoy2010_replication_v0/cahoy_compare/`.

## Tests

```bash
PYTHONPATH=roadrunner_egp/aurora_subneptune_grid/src:roadrunner_egp \
  pytest roadrunner_egp/aurora_subneptune_grid/tests
```

## Key scripts

| Script | Role |
| --- | --- |
| `make_manifest.py` | Cartesian manifest + `climate_group_index` |
| `make_cahoy2010_manifest.py` | Cahoy 304-row manifest |
| `run_climate_cache_chunk.py` | Stage 1 |
| `run_spectrum_from_cache_chunk.py` | Stage 2 |
| `submit_two_stage_grid.sh` | Submit both Slurm stages |
| `run_grid_chunk.py` | Legacy single-row (Guillot or full climate) |
