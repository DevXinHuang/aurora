Implement native PICASO climate patchy clouds in the Aurora/Roadrunner sub-Neptune grid. Do not use the previous post-hoc clear/cloudy linear-combination script.

Current branch context:
- `run_grid_chunk.py` already has `--atmosphere-source picaso_climate` and `--use-picaso-climate`.
- `roadrunner.runner.run_picaso_climate_model_once()` already creates `jdi.inputs(calculation="planet", climate=True)`, calls `inputs_climate(...)`, then `cl_run.climate(...)`, applies the converged climate PT profile, and computes reflected spectra.
- Current `cloud_model_for_fraction()` rejects fractional cloud fractions; fix that.

Required behavior:
1. Allow `cloud_fraction` values in `[0, 1]` in manifests.
   - `0.0` -> `cloud_model="none"`
   - `0.0 < cloud_fraction <= 1.0` -> `cloud_model="virga"`
   - Do not reject `0.5`.
2. Add `cloud_fraction` to `SystemParams` and pass it from `aurora_grid/picaso_runner.py` when building `SystemParams`.
3. In the PICASO climate path only, use PICASO's native patchy/cloud-coverage functionality for `cloud_fraction < 1.0`.
   - First run `scripts/probe_picaso_patchy_api.py` to inspect the installed PICASO API.
   - Implement against the real available API found there, not against a guessed name.
   - Likely locations to inspect are `inputs_climate(...)`, `climate(...)`, and methods/attributes containing `patch`, `cloud`, `frac`, or `cover`.
   - Store metadata indicating the exact PICASO parameter/method used, e.g. `native_patchy_cloud_api="inputs_climate.cloud_fraction"`.
4. For this production mode, no silent fallback to Jupiter cloud files is allowed when `cloud_fraction > 0` and `cloud_model="virga"`.
   - If Virga or native patchy fails, raise a RuntimeError so the job fails loudly.
5. Preserve the existing Aurora NetCDF schema and output variables.
   - The output `.nc` must still include `reflected_planet_star_flux_ratio`, `geometric_albedo`, `pressure_bar`, `temperature_k`, `mole_fraction`, `cloud_optical_depth`, `single_scattering_albedo`, and `asymmetry_factor`.
   - Add attrs/metadata for `cloud_fraction=0.5`, `cloud_hole_fraction=0.5`, `atmosphere_source=picaso_climate`, and `run_type=native_picaso_climate_patchy_cloud`.
6. Add or update tests:
   - `cloud_model_for_fraction(0.5) == "virga"`
   - manifest generation accepts `cloud_fraction: [0.5]`
   - dry/mock native patchy metadata is preserved in NetCDF.
7. After implementation, run:
   ```bash
   PYTHONPATH=roadrunner_egp/aurora_subneptune_grid/src:roadrunner_egp pytest roadrunner_egp/aurora_subneptune_grid/tests -q
   bash roadrunner_egp/aurora_subneptune_grid/scripts/run_patchy_picaso_climate_native_local.sh
   ```

Important science parameters for the first native patchy test:
- Tint/picaso_tint_fixed_k = 1000 K
- gravity = 100 m/s^2
- metallicity = 1x solar
- C/O = 1.0x solar
- fsed = 3
- cloud_fraction = 0.5
- cloud_hole_fraction = 0.5
- Kzz = 1e9 cm2/s, not 1e4, so Virga should have a physical chance to converge.
