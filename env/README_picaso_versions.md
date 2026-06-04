# PICASO Environment Snapshot

This file records the legacy PICASO 3.4 baseline and the current Aurora PICASO 4 setup. The PICASO 3.4 entries are kept only so the validation script can explain what Aurora was compared against.

Snapshot date: 2026-05-20

## Legacy Frozen Baseline

- Frozen conda environment: `picaso`
- Python executable: `/Users/xin/anaconda3/envs/picaso/bin/python`
- PICASO version: `3.4`
- PICASO import path: `/Users/xin/anaconda3/envs/picaso/lib/python3.10/site-packages/picaso/__init__.py`
- Old `picaso_refdata`: `/Users/xin/Documents/Documents/College/timestep/picaso/reference/`
- Old `PYSYN_CDBS`: `/Users/xin/Documents/Documents/College/timestep/picaso/reference/grp/redcat/trds`
- Old activation scripts:
  - `/Users/xin/anaconda3/envs/picaso/etc/conda/activate.d/env_vars.sh`
  - `/Users/xin/anaconda3/envs/picaso/etc/conda/deactivate.d/env_vars.sh`
- Base conda also has old PICASO hooks at `/Users/xin/anaconda3/etc/conda/activate.d/picaso_env.sh` and `/Users/xin/anaconda3/etc/conda/deactivate.d/picaso_env.sh`; these were left untouched.

Treat this setup as a frozen comparison baseline. Do not install PICASO 4 into `picaso`, and do not write PICASO 4 data into the old reference folder.

## Active Shell During Inspection

- Active shell environment: `base`
- Active Python: `/Users/xin/anaconda3/bin/python`
- During the original migration audit, the old `timestep` tree contained a local `picaso/` source checkout that could shadow installed packages.
- Aurora validation runs from a timestamped output directory using explicit env Python binaries and rejects imports from that old local source checkout.

## Snapshot Files

- `requirements_picaso_old_freeze.txt`: exact `pip freeze` from conda env `picaso`.
- `environment_picaso_old.yml`: `conda env export -n picaso`.

## New Isolated Setup

- New conda environment: `picaso4`
- New reference data folder: `/Users/xin/Documents/Documents/College/aurora/picaso4_reference`
- New `PYSYN_CDBS`: `/Users/xin/Documents/Documents/College/aurora/picaso4_reference/stellar_grids`
- Installed PICASO 4 optional data: `ck04models`, `phoenix`, default Virga Mieff files, and Virga aggregate Mieff files.
- Setup script: `env/create_picaso4_env.sh`
- Reference-data script: `env/setup_picaso4_reference_data.py`
- Activating `picaso4` overrides the old variables with the new reference paths. Deactivating `picaso4` runs its unset script, but returning to `base` can restore the old variables because of the frozen base conda hook above.

## PICASO-Using Project Files Found

Primary source files inspected during the migration audit included:

- `2_2026_nextstep/this_code_worked_debug_run.ipynb`
- `2_2026_nextstep/# %% [markdown].py`
- `2_2026_nextstep_timestep/run_picaso_once.py`
- `2_2026_nextstep_timestep/config.py`
- `2_9_2026/run_roadrunner.ipynb`
- `2_9_2026/run_roadrunner_phase_0.ipynb`
- `2_9_2026/run_roadrunner_egp_phase_angle_sweep.ipynb`
- `2_9_2026/egp_hybrid_phase0.py`
- `roadrunner_project/roadrunner/config.py`
- `roadrunner_project/roadrunner/runner.py`
- `roadrunner_project/roadrunner/bands.py`
- `NGU*/roman_cgi_target_runner.ipynb`
- `final_10_17/*roman*` and `rst/*roman*` notebooks

The full scan list is saved in `env/picaso_usage_files.txt`.
