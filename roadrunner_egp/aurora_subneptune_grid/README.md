# Aurora Sub-Neptune PICASO Grid Runner

This directory contains the first Aurora sub-Neptune reflected-light grid runner.
It turns the Path A notebook workflow into normal Python modules and scripts so
the grid can run reproducibly on a workstation or as Slurm array jobs.

The science question is whether sub-Neptunes near the Fulton radius valley can
masquerade as terrestrial worlds in reflected-light spectra. Each manifest row
is one PICASO model, and each completed model writes one restartable NetCDF file.

## Why Scripts

The source notebook remains the reference for the first Path A experiment, but
the production workflow does not execute notebooks. Scripts provide stable CLI
arguments, deterministic filenames, resumable skip behavior, and clean Slurm
array indexing.

## Parameter Space

| Parameter | Values | Steps |
| --- | --- | ---: |
| Host star Teff + radius | 3500 K (0.45 R_sun), 4000 K (0.63 R_sun), 5000 K (0.80 R_sun), 7000 K (1.70 R_sun) | 4 |
| Planet radius | 1.6, 2.0, 2.5, 3.0 R_earth | 4 |
| Surface gravity | 5, 10, 15, 25 m s-2 | 4 |
| Atmospheric metallicity | 1, 10, 100 x solar | 3 |
| C/O ratio | 0.5, 1.0, 2.0 x solar C/O | 3 |
| Kzz | 1e9, 1e11 cm2 s-1 | 2 |
| Cloud fraction | 0.0, 1.0 | 2 |
| Sedimentation efficiency fsed | 0.3, 1, 3, 6, 8 | 5 |
| Insolation | 0.35, 0.7, 1.0, 1.5 S_earth | 4 |
| Phase angle | 0, 30, 60, 90, 120, 150 deg | 6 |

The full Cartesian grid has 276,480 simulations.

## Local Smoke Tests

```bash
# Dry-run smoke test on Mac
python roadrunner_egp/aurora_subneptune_grid/scripts/smoke_test.py --dry-run

# Real smoke test on Mac, if the PICASO environment works
python roadrunner_egp/aurora_subneptune_grid/scripts/smoke_test.py --real
```

The dry run writes toy spectra, but it uses the real manifest, naming, xarray,
atomic write, and reopen-verification plumbing.

## Manifest And Local Row Runs

```bash
# Generate full manifest
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/aurora_subneptune_v0.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/aurora_subneptune_v0_manifest.csv

# Run one row locally in dry-run mode
python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest roadrunner_egp/aurora_subneptune_grid/manifests/aurora_subneptune_v0_manifest.csv \
  --array-index 0 \
  --model-name aurora_subneptune_v0 \
  --dry-run
```

## HPC

### Step 1: Smoke test (6 jobs, ~30 min)

```bash
# Pre-generate the smoke manifest
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/smoke_test.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_manifest.csv

# Submit
sbatch roadrunner_egp/aurora_subneptune_grid/slurm/test_aurora_subneptune_grid.slurm
```

### Step 2: Validation run (1,728 jobs, ~4 hr each)

A representative subset of the full grid that covers endpoints of every
parameter axis. Use this to validate timing, memory, and output correctness
before committing to the full 276,480-row grid.

```bash
# Pre-generate the validation manifest
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/hpc_validation.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv

# Submit all 1,728 jobs
sbatch roadrunner_egp/aurora_subneptune_grid/slurm/validation_aurora_subneptune_grid.slurm
```

### Step 3: Full grid (276,480 jobs, batched)

Slurm's `MaxArraySize` typically caps arrays at ~1,000 tasks. Check your
cluster's limit, then submit in batches:

```bash
# Check your limit
scontrol show config | grep MaxArraySize

# Pre-generate the full manifest (only once)
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/aurora_subneptune_v0.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/aurora_subneptune_v0_manifest.csv

# Submit in batches of 1,000 with max 100 running concurrently
for start in $(seq 0 1000 276479); do
  end=$((start + 999))
  [ $end -gt 276479 ] && end=276479
  sbatch --array=${start}-${end}%100 \
    roadrunner_egp/aurora_subneptune_grid/slurm/run_aurora_subneptune_grid.slurm
done
```

The Slurm templates activate the `picaso4` conda environment, source the Aurora
runtime paths, and run one manifest row per array task. Failed or interrupted
arrays can be resubmitted safely — existing output files are skipped.

## Customizing The Parameter Space

The parameter grid is defined entirely in a YAML config file under `params/`.
The grid is the **Cartesian product** of every list — total simulations equals
the product of all list lengths.

### Where to change things

Edit the YAML config file. Each parameter is a simple list:

```yaml
# To add or remove values, just edit the list:
planet_radius_rearth: [1.6, 2.0, 2.5, 3.0]   # 4 values
gravity_ms2: [5, 10, 15, 25]                   # 4 values
metallicity_xsolar: [1, 10, 100]               # 3 values
c_to_o_xsolar: [0.5, 1.0, 2.0]                # 3 values
kzz_cm2_s: [1.0e9, 1.0e11]                    # 2 values
cloud_fraction: [0.0, 1.0]                     # 2 values
fsed: [0.3, 1, 3, 6, 8]                       # 5 values
insolation_searth: [0.35, 0.7, 1.0, 1.5]      # 4 values
phase_deg: [0, 30, 60, 90, 120, 150]           # 6 values

# Stars are a list of {teff_k, radius_rsun} pairs:
stars:
  - teff_k: 3500
    radius_rsun: 0.45
  - teff_k: 5000
    radius_rsun: 0.80
```

### How to verify after editing

```bash
# Regenerate the manifest and check the count
python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config <your_config.yaml> \
  --out <your_manifest.csv>

# Output tells you: total_rows, duplicate checks, first 5 rows
```

### Then update the Slurm script

Change `#SBATCH --array=0-N` where N = total_rows − 1, and make sure
`--model-name` matches the `model_name` in your YAML.

### Available configs

| Config | Rows | Purpose |
| --- | ---: | --- |
| `params/smoke_test.yaml` | 6 | Quick plumbing check |
| `params/hpc_validation.yaml` | 1,728 | Representative HPC validation |
| `params/aurora_subneptune_v0.yaml` | 276,480 | Full science grid |

## Inspect And Inventory Outputs

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/inspect_output.py path/to/file.nc

python roadrunner_egp/aurora_subneptune_grid/scripts/combine_outputs.py \
  --output-root roadrunner_egp/aurora_subneptune_grid/outputs/smoke_test_aurora_subneptune \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_inventory.csv
```

## Post-Run QC And Triage

Each per-run NetCDF uses the `aurora_subneptune_netcdf` schema. After jobs
finish, run post-run QC to validate files, write CSV reports, and generate the
diagnostic plots used for review:

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/run_postrun_qc.py \
  --output-root roadrunner_egp/aurora_subneptune_grid/outputs/smoke_test_aurora_subneptune/nc \
  --grid-manifest roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_manifest.csv
```

This writes `qc_summary.csv`, `qc_flags.csv`, diagnostic PNGs, and a rerun
manifest when `--grid-manifest` is supplied. To review plots in the browser:

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/run_postrun_qc.py \
  --output-root roadrunner_egp/aurora_subneptune_grid/outputs/smoke_test_aurora_subneptune/nc \
  --grid-manifest roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_manifest.csv \
  --serve
```

To build a spectra-only Zarr collection after all jobs finish:

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/collect_picaso_model_store.py \
  --output-root roadrunner_egp/aurora_subneptune_grid/outputs/smoke_test_aurora_subneptune \
  --overwrite
```

Developer tests can be run from the repository root with:

```bash
PYTHONPATH=roadrunner_egp/aurora_subneptune_grid/src:roadrunner_egp \
  pytest roadrunner_egp/aurora_subneptune_grid/tests
```

## Output Naming

Every output filename includes `model_name`, physical parameter tags, and a
deterministic short SHA1 `run_id`. Existing files are skipped by default, so a
failed or interrupted array can be resubmitted safely. Passing `--overwrite` is
required to replace an existing NetCDF file.

Each NetCDF stores the spectrum plus JSON metadata attrs for planet, star, orbit,
cloud, grid, source manifest row, source notebook reference, and git commit.
When PICASO's model-preservation xarray path is available, the file also stores
the reusable PICASO pressure, temperature, chemistry, and cloud fields.
