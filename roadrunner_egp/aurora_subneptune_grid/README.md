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
| Host star Teff + radius | 3000 K (0.20 R_sun), 3500 K (0.45 R_sun), 4000 K (0.63 R_sun), 5000 K (0.80 R_sun), 7000 K (1.70 R_sun) | 5 |
| Planet radius | 1.6, 2.0, 2.5, 3.0 R_earth | 4 |
| Surface gravity | 5, 10, 15, 25 m s-2 | 4 |
| Atmospheric metallicity | 1, 10, 100, 1000 x solar | 4 |
| C/O ratio | 0.5, 1.0, 2.0 x solar C/O | 3 |
| Kzz | 1e9, 1e11 cm2 s-1 | 2 |
| Cloud fraction | 0.0, 1.0 | 2 |
| Sedimentation efficiency fsed | 0.3, 1, 3, 6, 8 | 5 |
| Insolation | 0.35, 0.7, 1.0, 1.5 S_earth | 4 |
| Phase angle | 0, 30, 60, 90, 120, 150 deg | 6 |

The full Cartesian grid has 460,800 simulations.

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

```bash
# Submit HPC smoke test
sbatch roadrunner_egp/aurora_subneptune_grid/slurm/test_aurora_subneptune_grid.slurm

# Submit first 100 full-grid jobs
sbatch roadrunner_egp/aurora_subneptune_grid/slurm/run_aurora_subneptune_grid.slurm
```

The Slurm templates activate the `picaso4` conda environment, source the Aurora
runtime paths, and run one manifest row per array task. The full-grid template
starts with `#SBATCH --array=0-99`; change it to `0-460799` only after validation.

## Inspect And Inventory Outputs

```bash
python roadrunner_egp/aurora_subneptune_grid/scripts/inspect_output.py path/to/file.nc

python roadrunner_egp/aurora_subneptune_grid/scripts/combine_outputs.py \
  --output-root roadrunner_egp/aurora_subneptune_grid/outputs/smoke_test_aurora_subneptune \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_inventory.csv
```

## Output Naming

Every output filename includes `model_name`, physical parameter tags, and a
deterministic short SHA1 `run_id`. Existing files are skipped by default, so a
failed or interrupted array can be resubmitted safely. Passing `--overwrite` is
required to replace an existing NetCDF file.

Each NetCDF stores the spectrum plus JSON metadata attrs for planet, star, orbit,
cloud, grid, source manifest row, source notebook reference, and git commit.
