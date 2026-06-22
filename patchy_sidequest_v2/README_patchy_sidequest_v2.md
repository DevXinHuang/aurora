# Aurora patchy-cloud sidequest v2

This is a single mentor SLGRID patchy-cloud case wrapped for the Aurora NetCDF workflow.

The uploaded `run_SLGRID_T1000_g100_m+000_CO100_fsed3_frac50.scr` is an **SLGRID input deck**, not a Slurm script.

Key settings:

- `Tint = 1000 K`
- `g = 100 m/s^2 = 10,000 cm/s^2`, so `logg_cgs = 4.0`
- `metallicity = +0.0 dex = 1x solar`
- `C/O = 1.00` from the `CO100` file naming
- `do_clouds = true`
- `do_holes = true`
- `fhole = 0.5`, so `cloud_fraction = 0.5`
- `fsed = 3`
- `Kzz_min = 1e4 cm^2/s`
- condensibles: `MgSiO3;Mg2SiO4;Na2S;KCl;MnS;ZnS`

## Copy into repo

From the Aurora repo root:

```bash
mkdir -p roadrunner_egp/aurora_subneptune_grid/params/patchy_cloud \
         roadrunner_egp/aurora_subneptune_grid/manifests \
         roadrunner_egp/aurora_subneptune_grid/slurm \
         roadrunner_egp/aurora_subneptune_grid/scripts \
         roadrunner_egp/aurora_subneptune_grid/outputs/patchy_cloud

cp run_SLGRID_T1000_g100_m+000_CO100_fsed3_frac50.scr \
  roadrunner_egp/aurora_subneptune_grid/params/patchy_cloud/
cp patchy_case_manifest.csv roadrunner_egp/aurora_subneptune_grid/manifests/
cp slgrid_patchy_to_netcdf.py roadrunner_egp/aurora_subneptune_grid/scripts/
cp test_patchy_case_local.sh roadrunner_egp/aurora_subneptune_grid/scripts/
cp run_patchy_case_hpc.slurm roadrunner_egp/aurora_subneptune_grid/slurm/
```

## Local smoke test

This only tests parsing + NetCDF writing. It does not run the mentor executable.

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/test_patchy_case_local.sh
```

Expected output file:

```text
roadrunner_egp/aurora_subneptune_grid/outputs/patchy_cloud/SLGRID_T1000_g100_m+000_CO100_fsed3_frac50.local_smoke.nc
```

## Find the mentor executable

Use one of these on HPC if you do not know the path yet:

```bash
find ~/ -type f \( -name '*slgrid*' -o -name '*.x' -o -name '*.exe' \) 2>/dev/null | head -50
which slgrid || true
```

## Submit after local test passes

```bash
sbatch --export=ALL,SLGRID_EXE=/absolute/path/to/slgrid/executable \
  roadrunner_egp/aurora_subneptune_grid/slurm/run_patchy_case_hpc.slurm
```

Expected final output:

```text
roadrunner_egp/aurora_subneptune_grid/outputs/patchy_cloud/SLGRID_T1000_g100_m+000_CO100_fsed3_frac50.nc
```
