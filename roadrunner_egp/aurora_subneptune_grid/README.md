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
  nc/run_000000.nc …                              ← stage 2 (304–960,000 supported files)
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
| `aurora_subneptune_v1` | 960,000 | 40,000 | Supported science grid (gravity climates) |
| `aurora_subneptune_v0` | 276,480 | 46,080 | Legacy full-grid baseline |

### Sub-Neptune grid sets (non-Cahoy)

The two non-Cahoy grids currently used for development/testing are:

| Grid | Spectra | Climate groups | Role |
| --- | ---: | ---: | --- |
| `smoke_test_aurora_subneptune` | 6 | 2 | Minimal plumbing check before larger runs |
| `hpc_validation_aurora_subneptune` | 1,728 | 576 | Testing grid for HPC timing, stability, and QC |

The nominal v1 axes define 1,080,000 spectra and 45,000 gravity-based climate
groups. Manifest generation omits `metallicity_xsolar = 100` with
`c_to_o_xsolar = 2.0` because PICASO 4 does not provide the required
`sonora_2121grid_feh2.0_co1.10.hdf5` correlated-k table. The supported final
production run is therefore 960,000 spectra in 40,000 climate groups.

Planned final production run is `aurora_subneptune_v1`:

| Parameter | Values |
| --- | --- |
| Host star Teff + radius | 3500/0.45, 4000/0.63, 5000/0.80, 6000/1.00, 7000/1.70 |
| Planet radius (R_earth) | 1.6, 2.0, 2.5, 3.0 |
| Surface gravity (m/s²) | 5, 10, 15, 25, 30 |
| Metallicity (x solar) | 1, 10, 100 |
| C/O (x solar) | 0.5, 1.0, 2.0 |
| Kzz (cm²/s) | 1e9, 1e11 |
| Virga candidate condensates | H2O, CH4, NH3 |
| Cloud fraction | 0, 0.5, 0.75, 0.9, 1 |
| fsed | 0.3, 1, 3, 6, 8 |
| Insolation (S_earth) | 0.35, 0.7, 1.0, 1.5 |
| Phase (deg) | 0, 30, 60, 90, 120, 150 |
| Internal temperature Tint | Fixed at 50 K |

Gravity is the climate planet axis. Radius and phase vary only in the spectral
stage, so each climate feeds 24 spectra. Planet mass is derived per spectrum as
`M = gR²/G` and stored in manifest/NetCDF metadata. `equilibrium_temperature_k`
is calculated independently and is not used as `Tint`.

Cahoy shortcut:

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh
```

Stage 2 waits on stage 1 (`--dependency=afterok`). Large grids (>1,000 tasks)
are submitted in batches automatically.

### Manual stage commands

```bash
source env/activate_aurora_picaso4_job.sh

# Generate manifest (adds climate_group_index and climate_group_key)
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

`run_grid_chunk.py` now defaults to `picaso_climate`: PICASO initializes the
P–T profile, performs radiative-convective climate convergence, and then runs
the spectra. This is scientifically correct for a one-off test, but it
re-runs climate for every phase. Slurm templates `run_aurora_subneptune_grid.slurm`
and `validation_aurora_subneptune_grid.slurm` are disabled — use the cached
two-stage `submit_two_stage_grid.sh` workflow for production.

The former `--use-picaso-climate` switch is now redundant and remains only for
command compatibility.

This follows PICASO's documented climate API:

- [`jdi.inputs(calculation="planet", climate=True)`](https://natashabatalha.github.io/picaso/picaso.html#picaso.justdoit.inputs)
  enables the iterative temperature-pressure calculation.
- The [PICASO exoplanet climate tutorial](https://natashabatalha.github.io/picaso/notebooks/climate/12b_Exoplanet.html)
  describes Guillot as an **initial P–T guess**, followed by
  `inputs_climate(...)` and `cl_run.climate(...)` to find the converged
  solution. It also recommends 51–91 pressure levels; Aurora now uses the
  upper end of that documented range: 91 pressure levels (90 layers).

### Legacy Guillot smoke only — do not use for science

The old fast path requires the explicit option
`--atmosphere-source picaso_guillot`. It still runs PICASO radiative transfer
for the spectrum, but uses the analytic Guillot P–T profile directly and does
**not** run PICASO radiative-convective climate convergence.

`aurora_cahoy_solar_smoke_v0` (48 cases) is retained only for fast plumbing
checks (~1 min/task) with that explicit legacy option. Do **not** use its
output for science. For science-quality Cahoy spectra, use
`aurora_cahoy2010_replication_v0` and the two-stage submit script above.

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
| Surface gravity | 5, 10, 15, 25, 30 m/s² | 5 |
| Metallicity | 1, 10, 100× solar | 3 |
| C/O | 0.5, 1.0, 2.0× solar | 3 |
| Kzz | 1e9, 1e11 cm²/s | 2 |
| Cloud fraction | 0, 0.5, 0.75, 0.9, 1 | 5 |
| fsed | 0.3, 1, 3, 6, 8 | 5 |
| Insolation | 0.35, 0.7, 1.0, 1.5 S⊕ | 4 |
| Phase | 0, 30, 60, 90, 120, 150° | 6 |

Nominal Cartesian product: **1,080,000** spectra = **45,000** climate groups ×
**4** radii × **6** phases. Omitting the unsupported 100× metallicity / 2× C/O
pair removes **5,000** climate groups and **120,000** spectra, leaving
**40,000** supported climate groups and **960,000** supported spectra. The
unsupported combination receives no manifest or cache indices.

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

Download the production Stage 1 cache from the `tdrobin/dhuang` group disk
using the resumable file-transfer helper:

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/download_climate_cache_from_hpc.sh
```

Stage 1 climate caches (`.npz` plus paired `_case.pkl`) use the cache-native
checks. For a complete brightness-aware rebuild, first extract one parameter
row per cached climate from the production manifest with
`scripts/extract_climate_parameters.py`, then run:

```bash
.venv-picaso4/bin/python \
  roadrunner_egp/aurora_subneptune_grid/scripts/rebuild_brightness_qc.py \
  --cache-dir roadrunner_egp/aurora_subneptune_grid/outputs/<model>/climate_cache \
  --parameter-csv /path/to/climate_parameters.csv \
  --workers 4
```

This preserves the source cache and creates resumable derived sidecars with
the full 196-point brightness-temperature curve. It reruns the P–T, adiabat,
flux-balance, convergence, and brightness-depth checks; writes before/after
survival and transition reports; and saves a four-panel diagnostic for every
final non-pass climate in `qc.brightness-staging`.

After checking `rebuild_validation.json` and representative plots, atomically
replace the older generated QC directory:

```bash
.venv-picaso4/bin/python \
  roadrunner_egp/aurora_subneptune_grid/scripts/rebuild_brightness_qc.py \
  --cache-dir roadrunner_egp/aurora_subneptune_grid/outputs/<model>/climate_cache \
  --parameter-csv /path/to/climate_parameters.csv \
  --replace-only --replace
```

For interactive inspection, open `notebooks/qc_climate_cache.ipynb`.

Final Stage 2 NetCDF products continue to use the post-run workflow:

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
