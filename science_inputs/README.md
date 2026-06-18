# Science Inputs

This folder holds the local RoadRunner/EGP input data used by the PICASO4 migration notebooks.

## Layout

- `egp/irflux/`: EGP/RoadRunner thermal IR flux spectra and run logs.
- `slgrid/climate/`: SLGRID PT atmosphere profiles copied from `timestep/2_9_2026/SLGRID Climate Files`.
- `slgrid/clouds/`: SLGRID cloud profiles copied from `timestep/2_9_2026/SLGRID Cloud Files`.

Use `env/activate_roadrunner_picaso4.sh` to point notebooks and scripts at this local copy.

## Naming Convention

Most science files use this shared prefix:

```text
SLGRID_T{temperature}_g{gravity}_m{metallicity}_CO{co}_{case}
```

Token meanings:

- `T{temperature}`: equilibrium/effective grid temperature in K.
- `g{gravity}`: EGP gravity code. Match it with separators, e.g. `_g31_`, so `g31` does not accidentally match `g316`.
- `m{metallicity}`: metallicity token such as `m-050`, `m+000`, `m+050`, or `m+100`.
- `CO{co}`: C/O token such as `CO050`, `CO100`, or `CO200`.
- `{case}`:
  - `NC`: no-cloud case; physically this is the zero cloud-fraction case.
  - `fsed{value}`: non-frac cloudy case, e.g. `fsed0.3`, `fsed1`, `fsed3`, `fsed6`, `fsed8`.
  - `fsed{value}_frac{percent}`: partial-cloud case, with `frac10`, `frac25`, `frac50`, or `frac75`.

Canonical suffixes:

```text
SLGRID_T{T}_g{g}_m{m}_CO{co}_NC_full.pt
SLGRID_T{T}_g{g}_m{m}_CO{co}_fsed{fsed}_full.pt
SLGRID_T{T}_g{g}_m{m}_CO{co}_fsed{fsed}_frac{frac}_full.pt

SLGRID_T{T}_g{g}_m{m}_CO{co}_fsed{fsed}_picaso.cld
SLGRID_T{T}_g{g}_m{m}_CO{co}_fsed{fsed}_frac{frac}_picaso.cld

SLGRID_T{T}_g{g}_m{m}_CO{co}_NC_IRflux.txt
SLGRID_T{T}_g{g}_m{m}_CO{co}_fsed{fsed}_IRflux.txt
SLGRID_T{T}_g{g}_m{m}_CO{co}_fsed{fsed}_frac{frac}_IRflux.txt
```

Run logs usually mirror the IRflux stem with `.log`:

```text
SLGRID_T{T}_g{g}_m{m}_CO{co}_{case}.log
```

## Pairing Rules

For Route C reflected-light runs, pair PT and cloud files by the same stem:

```text
PT:    {stem}_full.pt
Cloud: {stem}_picaso.cld
```

Examples:

```text
SLGRID_T1000_g31_m+000_CO100_fsed8_full.pt
SLGRID_T1000_g31_m+000_CO100_fsed8_picaso.cld

SLGRID_T1000_g31_m+000_CO100_fsed8_frac25_full.pt
SLGRID_T1000_g31_m+000_CO100_fsed8_frac25_picaso.cld
```

Important details:

- `NC` means zero cloud fraction. It appears as PT and IRflux, but there is no `NC_picaso.cld` cloud file.
- A non-frac run should use only `fsed{value}_full.pt`, `fsed{value}_picaso.cld`, and `fsed{value}_IRflux.txt`.
- A partial-cloud run should use the same `frac` token across PT, cloud, and IRflux.
- Finder duplicate-copy files can contain ` 2` before the extension, such as `_full 2.pt`, `_picaso 2.cld`, or `_IRflux 2.txt`; workflow code should ignore these unless intentionally auditing duplicates.
- For the local `T500/g31/m+000/CO100` fsed sweep, the EGP IRflux directory has non-frac `NC`, `fsed0.3`, `fsed1`, `fsed3`, `fsed6`, and `fsed8`, but the exact non-frac SLGRID PT/cloud pair is present only for `fsed3`. The T500 sweep notebook therefore holds the SLGRID atmosphere fixed at non-frac `fsed3` while sweeping the EGP thermal fsed files.

## Current Inventory

Inventory checked on 2026-06-12:

- SLGRID PT files: `11,602`
- SLGRID cloud files: `12,590`
- Exact-suffix EGP/RoadRunner IRflux spectra: `12,248`
- EGP/RoadRunner `.log` files: `8,709`
- `egp/irflux/` size: about `5.7G`
- Total `science_inputs/` size: about `15G`

Observed axes:

- PT temperatures: `500`, `600`, `700`, `800`, `900`, `1000`, `1100`, `1200`, `1300`, `1400`, `1500`, `1600`, `1700`, `1800`, `2600`, `2800`, `3000`
- Cloud temperatures: `300`, `500`, `600`, `700`, `800`, `900`, `1000`, `1100`, `1200`, `1300`, `1400`, `1500`, `1600`, `1700`, `1800`
- IRflux temperatures: `300`, `500`, `600`, `700`, `800`, `900`, `1000`, `1100`, `1200`, `1300`, `1400`, `1500`, `1600`, `1700`, `1800`, `2600`, `2800`, `3000`
- Gravities: `31`, `100`, `126`, `316`, `1000`
- Metallicities: `m-050`, `m+000`, `m+050`, `m+100`
- C/O values: `CO050`, `CO100`, `CO200`
- Fsed values: `0.3`, `1`, `3`, `6`, `8`
- Frac values: `10`, `25`, `50`, `75`

## Known Exceptions

- `SLGRID_T1100_g126_m+000_CO100_NC_NoTiOVO_full.pt`, `SLGRID_T1100_g126_m+000_CO100_NC_NoTiOVO_IRflux.txt`, and `HD154345b_T203_g19_m+000_CO100_NC_NoTiOVO.log` are special `NoTiOVO` products outside the canonical pattern.
- `~$GRID_T2600_g1000_m+000_CO100_NC_full.pt` looks like a temporary or lock-style file and should not be used as a science input.
- `output_15043916.log` through `output_15043919.log` are generic run logs, not SLGRID case logs.
- A few EGP logs use `holesF` or `holesT` in the case token; these are log-only diagnostics in the current copy.
