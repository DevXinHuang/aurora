# Aurora HPC Meeting Prep

## One-Sentence Goal

Move Aurora, the PICASO 4/RoadRunner workflow, from this local Mac folder to the university HPC so the same validation and science runs can be reproduced with managed compute, storage, and environment setup.

## Current Project Shape

- Local folder size: about 19 GB.
- Code/docs/scripts are small and GitHub-friendly.
- Large data payloads:
  - `science_inputs/`: about 9.6 GB; SLGRID climate/cloud files and EGP IR flux files.
  - `picaso4_reference/`: about 9.8 GB; PICASO reference data/opacities/stellar grids.
- Environment:
  - Legacy validation baseline: PICASO 3.4 in conda env `picaso`.
  - Current Aurora env: PICASO 4.0.1 in conda env `picaso4`, Python 3.11.
- Validation status: close enough for Aurora validation; zero Roman-band decision flips in the current validation run.

## GitHub Recommendation

Use GitHub for code, notebooks, docs, environment scripts, and validation scripts.

Do not push the whole folder as-is. Keep large reference/science data out of GitHub and store it on HPC project storage or scratch. A `.gitignore` rule now excludes `picaso4_reference/`, `science_inputs/` data, generated outputs, and caches.

Best setup:

- Private GitHub repo for code and docs.
- HPC project directory for large data.
- A setup doc/script that tells users where to place or symlink:
  - `picaso4_reference`
  - `science_inputs`
- Optional later: Git LFS or DVC only if IT approves and quotas are clear.

## What To Ask IT/HPC

1. What scheduler should this use? Slurm/Sbatch?
2. Can I use conda/mamba on the cluster, or should I build a container?
3. Is outbound internet available on login/compute nodes for `pip install picaso`, or do packages need to be installed another way?
4. Where should the 20 GB reference/input data live: project storage, shared storage, or scratch?
5. What are the storage quota and file-count limits? This workflow has many SLGRID files.
6. What is the preferred data transfer method: Globus, `rsync`, `scp`, or something else?
7. Should long parameter sweeps run as Slurm job arrays?
8. What memory/time limits should I request for a first smoke test?
9. Are Jupyter notebooks supported on HPC, or should notebooks be converted to Python scripts?
10. Can environment variables be set in job scripts?
    - `picaso_refdata`
    - `PYSYN_CDBS`
    - `SLGRID_PT_DIR`
    - `SLGRID_CLD_DIR`
    - `EGP_IRFLUX_DIR`
    - `ROADRUNNER_SCIENCE_INPUTS`

## Concrete Meeting Ask

Ask for:

- An HPC account/project allocation.
- At least 30-50 GB persistent project storage for reference/input data plus outputs.
- Guidance on conda vs container.
- A small test queue/job allocation to run the existing validation script.
- Recommended path layout for project data and generated outputs.

## First HPC Milestone

Run this successfully on HPC:

```bash
source env/activate_roadrunner_picaso4.sh
python validation/validate_picaso4_against_legacy.py
```

Then convert the main RoadRunner workflows into Slurm batch scripts or job arrays.
