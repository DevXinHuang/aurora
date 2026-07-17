# Representative reflected-light spectra

Three reflected-plus-thermal spectra were constructed from existing converged NPZ/PKL climate-cache pairs for a controlled comparison at fixed bulk and orbital parameters.

Fixed parameters:

- Host: 3500 K, 0.45 R_sun
- Planet: 2.5 R_earth, 10.183 M_earth
- Insolation: 1.5 S_earth
- C/O: 1x solar
- Kzz: 1e9 cm2/s
- Phase: 0 degrees
- Full configured wavelength grid: 0.30-15 microns at R = 1500

Selected cases:

- **Clear, 1× solar metallicity** — climate group 23611; Reference atmosphere; isolates the baseline molecular spectrum without clouds.
- **Fully cloudy, 1× solar metallicity** — climate group 23691; Cloud comparison at fixed composition; shows continuum brightening and muted gas bands.
- **Clear, 100× solar metallicity** — climate group 24811; Composition comparison without clouds; shows the effect of enhanced heavy elements.

All three NetCDF files passed the Aurora schema checks and contained finite, nonzero reflected spectra.
