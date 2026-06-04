# Science Inputs

This folder holds the full local RoadRunner/EGP input data needed by the PICASO4 migration notebooks.

## Layout

- `egp/irflux/`: copied EGP `*_IRflux.txt` spectra from the original timestep RoadRunner setup.
- `slgrid/climate/`: full copied SLGRID PT file directory from `timestep/2_9_2026/SLGRID Climate Files`.
- `slgrid/clouds/`: full copied SLGRID cloud file directory from `timestep/2_9_2026/SLGRID Cloud Files`.

Current local copy:

- SLGRID PT files: `11,603`
- SLGRID cloud files: `12,591`
- EGP IRflux files: `69`
- Total size: about `9.6G`

Use `env/activate_roadrunner_picaso4.sh` to force notebooks and scripts to this local copy.
