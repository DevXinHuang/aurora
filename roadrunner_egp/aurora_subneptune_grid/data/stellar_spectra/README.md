Put the solar spectrum file here:

  SOLARSPECTRUM.DAT

Expected format:
  column 1 = wavelength in Angstrom
  column 2 = flux in erg/s/cm^2/Angstrom

Used by the Cahoy et al. 2010 replication grid
(`aurora_cahoy2010_replication_v0`). Submit that model with:

```bash
bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh
```

That run converges 16 PICASO climates (planet type × separation), then
computes 304 reflected spectra (19 phases per climate group).
