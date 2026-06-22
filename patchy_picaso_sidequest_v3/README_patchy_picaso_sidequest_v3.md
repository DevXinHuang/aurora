# Patchy PICASO sidequest v3

This version does **not** use SLGRID. It uses the existing Aurora/Roadrunner PICASO runner.

Why two runs? The current Aurora manifest generator only allows real PICASO cloud fractions of `0.0` or `1.0`.
So a 50% patchy case is represented as:

```text
clear component:  cloud_fraction=0.0, cloud_model=none
cloudy component: cloud_fraction=1.0, cloud_model=virga, fsed=3
patchy output:    0.5 * clear + 0.5 * cloudy
```

## Install into repo

From repo root:

```bash
mkdir -p roadrunner_egp/aurora_subneptune_grid/params \
         roadrunner_egp/aurora_subneptune_grid/scripts \
         roadrunner_egp/aurora_subneptune_grid/manifests \
         roadrunner_egp/aurora_subneptune_grid/outputs/patchy_cloud

cp patchy_picaso_sidequest_v3/params/patchy_picaso_sidequest.yaml \
  roadrunner_egp/aurora_subneptune_grid/params/
cp patchy_picaso_sidequest_v3/scripts/combine_patchy_picaso_components.py \
  roadrunner_egp/aurora_subneptune_grid/scripts/
cp patchy_picaso_sidequest_v3/scripts/run_patchy_picaso_sidequest_local.sh \
  roadrunner_egp/aurora_subneptune_grid/scripts/
```

## Actually run locally

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/run_patchy_picaso_sidequest_local.sh
```

Expected final file:

```text
roadrunner_egp/aurora_subneptune_grid/outputs/patchy_cloud/PICASO_T1000_g100_m+000_CO100_fsed3_frac50.patchy_picaso.nc
```

Note: The original SLGRID deck has no planet radius and no reflected-light orbit because stellar flux is off.
This config uses a representative local Roadrunner reflected-light setup: `planet_radius_rearth=3.0`,
`insolation_searth=1.0`, and `phase_deg=60`. Change those if the mentor gives exact values.
