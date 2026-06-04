# Aurora Notes

Last validation run: `20260528_roadrunner_egp_flow`

## What Changed

- Legacy baseline environment remains frozen: conda env `picaso`, PICASO `3.4`, refdata `/Users/xin/Documents/Documents/College/timestep/picaso/reference`.
- Current Aurora environment: conda env `picaso4`, PICASO `4.0.1`, refdata `/Users/xin/Documents/Documents/College/aurora/picaso4_reference`.
- PICASO 4 optional data installed: `ck04models`, `phoenix`, default Virga Mieff files, and Virga aggregate Mieff files.
- Validation science inputs are read from local `/Users/xin/Documents/Documents/College/aurora/science_inputs`, copied from frozen `/Users/xin/Documents/Documents/College/timestep`; validation outputs stay in this Aurora folder.
- New validation outputs are written only under `validation/outputs/<run_id>/`.
- Base conda still restores the old PICASO variables through its existing activation hook; this was left untouched to preserve production behavior.

## Commands

```bash
bash env/create_picaso4_env.sh
/Users/xin/anaconda3/envs/picaso4/bin/python env/setup_picaso4_reference_data.py
/Users/xin/anaconda3/envs/picaso4/bin/python validation/validate_picaso4_against_legacy.py
```

## Validation Cases

- Cool vulnerable case: `Teff=500 K`, `a=5 AU`, `phase=60 deg`, `logg=3.5`, `radius=1 Rj`, Sun-like star.
- Warm comparison case: `Teff=1000 K`, `a=5 AU`, `phase=60 deg`, `logg=3.5`, `radius=1 Rj`, Sun-like star.
- Roman CGI bands: `CGI-1=0.546-0.604 um`, `CGI-2=0.610-0.710 um`, `CGI-3=0.675-0.785 um`, `CGI-4=0.783-0.867 um`.
- Reflection threshold: `f_reflect >= 0.10`, where `f_reflect = F_reflected / (F_reflected + F_thermal)`.

## Current Result

- Status: **close enough for Aurora validation**
- Comparison: `compared`
- Max absolute `f_reflect` difference: `2.220446049250313e-16`
- Decision flips: `0`
- Comparison CSV: `/Users/xin/Documents/Documents/College/aurora/validation/outputs/20260528_roadrunner_egp_flow/band_integrated_comparison.csv`

## API / Output Differences

See `/Users/xin/Documents/Documents/College/aurora/validation/outputs/20260528_roadrunner_egp_flow/validation_summary.txt` and `report_old.json` / `report_picaso4.json` for full output-key diagnostics. Expected keys checked: `fpfs_reflected`, `fpfs_thermal`, `thermal`, and `albedo`.
