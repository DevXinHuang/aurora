# Climate parameter-space coverage snapshot

Snapshot: 2026-07-16T15:48:18Z

- Overall validated climate coverage: **27,595 / 180,000 (15.33%)**.
- File inventory: **27,627 NPZ** and **27,627 PKL**, with **27,627 matched pairs**.
- NPZ validation: **27,595 usable**, **32 with a validation or convergence issue**.
- The usable index frontier is **0–31,719**, with **4,125 missing climates inside that range**.
- Stellar coverage is currently concentrated at the first anchor: **27,595 / 36,000 (76.65%)** for 3500 K / 0.45 R_sun.

Discrete parameter values reached (at least one validated climate):

- Stellar anchor: 1/5
- Planet radius: 4/4
- Planet mass: 5/5
- Metallicity: 3/3
- C/O: 3/3
- Kzz: 2/2
- Cloud fraction: 5/5
- f_sed: 5/5
- Insolation: 4/4

Interpretation: the run has reached every configured value on eight of the nine climate axes, but it has not yet reached the other four stellar anchors. Reaching a value does not mean all cross-combinations at that value are complete.

Phase angle is not a climate axis in this count: all six phases reuse each converged pressure–temperature profile. Gravity is derived from planet mass and radius in this configuration.

PKL files were checked for filename/index pairing and nonzero size only; they were not unpickled during this coverage audit.
