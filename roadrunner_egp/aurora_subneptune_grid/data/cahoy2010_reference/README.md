# Cahoy et al. 2010 reference albedo spectra

Official Roman/IPAC archive used to validate the Aurora Cahoy replication grid.

## Install on HPC

```bash
cd ~/Documents/aurora
bash roadrunner_egp/aurora_subneptune_grid/scripts/install_cahoy2010_reference.sh
```

This downloads `cahoy2010_spectra.tgz` (~3.8 MB) from
[roman.ipac.caltech.edu](https://roman.ipac.caltech.edu/data/sims/cahoy2010_spectra.tgz)
and extracts spectra to:

```text
Cahoy_et_al_2010_Albedo_Spectra/albedo_spectra/*.dat
```

## Or copy from your Mac

If you already have the archive in Downloads:

```bash
scp ~/Downloads/cahoy2010_spectra.tgz \
  hpc:~/Documents/aurora/roadrunner_egp/aurora_subneptune_grid/data/cahoy2010_reference/

ssh hpc 'bash ~/Documents/aurora/roadrunner_egp/aurora_subneptune_grid/scripts/install_cahoy2010_reference.sh --from-tarball'
```

## File format

Each `.dat` file has two columns (0.35–1.0 µm):

| column | quantity |
| --- | --- |
| 1 | wavelength (µm) |
| 2 | albedo |

Naming matches the Aurora manifest column `cahoy_reference_name`, e.g.
`Jupiter_1x_0.8AU_60deg.dat`.

At 0° phase Cahoy reports geometric albedo; at other phases, spherical albedo.
Aurora NetCDF stores PICASO `geometric_albedo` at the requested `phase_deg`.

Credit: Kerri Cahoy, Mark Marley, Jonathan Fortney (Cahoy et al. 2010, ApJ 724, 189).
