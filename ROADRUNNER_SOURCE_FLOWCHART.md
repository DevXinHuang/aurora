# RoadRunner Source Flowchart

This is the simplified version. Instead of showing every possible branch at once, choose one practical path first.

```mermaid
flowchart TD
    A["Start:<br/>SystemParams<br/>Teff, logg, Rp, a, phase"] --> B{"Pick one run type"}

    B -->|"Best for new no-SLGRID runs"| C["Path A<br/>Full PICASO"]
    B -->|"Use EGP thermal file<br/>but no SLGRID atmosphere"| D["Path B<br/>PICASO atmosphere + EGP thermal"]
    B -->|"Old/original setup"| E["Path C<br/>SLGRID atmosphere + EGP thermal"]

    C --> C1["Settings:<br/>thermal_source = picaso<br/>atmosphere_source = picaso"]
    C1 --> C2["PICASO generates atmosphere:<br/>Guillot PT + chemistry + clouds"]
    C2 --> C3["PICASO reflected light<br/>uses requested phase angle"]
    C2 --> C4["PICASO thermal<br/>fixed at phase = 0"]
    C3 --> Z["Band metrics:<br/>f_reflect, fluxes, decision"]
    C4 --> Z

    D --> D1["Settings:<br/>thermal_source = egp<br/>atmosphere_source = picaso"]
    D1 --> D2["PICASO generates atmosphere:<br/>Guillot PT + chemistry + clouds"]
    D2 --> D3["PICASO reflected light<br/>uses requested phase angle"]
    D1 --> D4["Load EGP IRflux file<br/>for thermal"]
    D3 --> Z
    D4 --> Z

    E --> E1["Settings:<br/>thermal_source = egp<br/>atmosphere_source = slgrid"]
    E1 --> E2["Read matching SLGRID<br/>PT + cloud files"]
    E2 --> E3["PICASO reflected light<br/>uses requested phase angle"]
    E1 --> E4["Load EGP IRflux file<br/>for thermal"]
    E3 --> Z
    E4 --> Z
```

## Which Path Should I Use?

Use Path A if you want PICASO to handle everything and avoid SLGRID PT/cloud files:

```python
df = evaluate_hybrid_case(
    case,
    thermal_source="picaso",
    atmosphere_source="picaso",
    cloud_model="virga",
)
```

Use Path B if you trust/want the EGP thermal file, but still want no SLGRID atmosphere files:

```python
df = evaluate_hybrid_case(
    case,
    thermal_source="egp",
    atmosphere_source="picaso",
    cloud_model="virga",
)
```

Use Path C for the original comparison workflow:

```python
df = evaluate_hybrid_case(
    case,
    thermal_source="egp",
    atmosphere_source="slgrid",
)
```

## What Happens Inside PICASO Atmosphere?

This only happens when `atmosphere_source="picaso"`.

```mermaid
flowchart TD
    A["atmosphere_source = picaso"] --> B["Compute Teq<br/>from star + orbit"]
    B --> C["Build Guillot PT profile<br/>case.guillot_pt(...)"]
    C --> D["Add equilibrium chemistry<br/>case.chemeq_visscher(...)"]
    D --> E{"cloud_model"}
    E -->|"virga"| F["Virga clouds<br/>fsed = 3 by default"]
    E -->|"jupiter"| G["Jupiter cloud fallback"]
    E -->|"none"| H["Cloud-free"]
    F --> I["Atmosphere ready for PICASO spectrum"]
    G --> I
    H --> I
```

## Meaning Of The Switches

`thermal_source="egp"` uses the copied EGP `*_IRflux.txt` file for thermal emission.

`thermal_source="picaso"` uses PICASO for both reflected light and thermal emission.

`atmosphere_source="slgrid"` reads the precomputed SLGRID PT and cloud files.

`atmosphere_source="picaso"` builds the PT profile, chemistry, and clouds inside PICASO, so it does not use the SLGRID PT/cloud files.
