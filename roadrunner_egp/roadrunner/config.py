"""
roadrunner.config
~~~~~~~~~~~~~~~~
All configuration constants, environment setup, and parameter grids for
the Roman CGI reflected-light analysis pipeline.
"""

import os
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Environment — set BEFORE any PICASO import
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ROOT = PROJECT_ROOT.parent
TIMESTEP_ROOT = Path(
    os.environ.get("TIMESTEP_ROOT", "/Users/xin/Documents/Documents/College/timestep")
).expanduser()
SCIENCE_INPUTS_DIR = Path(
    os.environ.get("ROADRUNNER_SCIENCE_INPUTS", MIGRATION_ROOT / "science_inputs")
).expanduser()

PICASO4_REFDATA = MIGRATION_ROOT / "picaso4_reference"
PICASO4_PYSYN_CDBS = PICASO4_REFDATA / "stellar_grids"
TIMESTEP_REFDATA = TIMESTEP_ROOT / "picaso" / "reference"
TIMESTEP_PYSYN_CDBS = TIMESTEP_REFDATA / "grp" / "redcat" / "trds"

if "picaso_refdata" not in os.environ:
    os.environ["picaso_refdata"] = str(
        PICASO4_REFDATA if PICASO4_REFDATA.exists() else TIMESTEP_REFDATA
    )
if "PYSYN_CDBS" not in os.environ:
    os.environ["PYSYN_CDBS"] = str(
        PICASO4_PYSYN_CDBS if PICASO4_PYSYN_CDBS.exists() else TIMESTEP_PYSYN_CDBS
    )

# Threading
_nthreads = str(max(1, (os.cpu_count() or 2) - 1))
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "MKL_NUM_THREADS", "NUMEXPR_MAX_THREADS"):
    os.environ.setdefault(_var, _nthreads)

# ---------------------------------------------------------------------------
# Stellar defaults
# ---------------------------------------------------------------------------
T_STAR_K: float = 5778.0
R_STAR_Rsun: float = 1.0

# ---------------------------------------------------------------------------
# Parameter grids
# ---------------------------------------------------------------------------
TEFFS_K        = [400, 500, 800, 1000, 1200, 1500]
LOGGS_CGS      = [3.0, 3.5, 4.0]
R_PLANETS_Rj   = [1.0, 1.2]
SEMI_MAJOR_AU  = [5.0, 10.0, 20.0]
PHASE_DEG      = [0.0]  # single phase angle have to modify this for dif phase angle

# ---------------------------------------------------------------------------
# Roman CGI band definitions  (wavelength in µm)
# ---------------------------------------------------------------------------
CGI_BANDS = {
    "CGI-1": (0.546, 0.604),
    "CGI-2": (0.610, 0.710),
    "CGI-3": (0.675, 0.785),
    "CGI-4": (0.783, 0.867),
}

# ---------------------------------------------------------------------------
# Radiative-transfer settings
# ---------------------------------------------------------------------------
REFLECT_NUM_GANGLE = 4
REFLECT_NUM_TANGLE = 4
THERMAL_NUM_GANGLE = 8
THERMAL_NUM_TANGLE = 1
# PICASO's climate tutorial recommends 51-91 pressure levels. Use the upper
# end of that range for the converged Aurora climate grid.
ATM_NLAYERS = 91

# ---------------------------------------------------------------------------
# Generated-PICASO atmosphere defaults
# ---------------------------------------------------------------------------
ATMOSPHERE_SOURCE = os.environ.get("ROADRUNNER_ATMOSPHERE_SOURCE", "slgrid")
THERMAL_SOURCE = os.environ.get("ROADRUNNER_THERMAL_SOURCE", "egp")

PICASO_BOND_ALBEDO = float(os.environ.get("ROADRUNNER_PICASO_BOND_ALBEDO", "0.0"))
PICASO_CHEM_C_TO_O = float(os.environ.get("ROADRUNNER_PICASO_C_TO_O", "1.0"))
PICASO_CHEM_LOG_MH = float(os.environ.get("ROADRUNNER_PICASO_LOG_MH", "0.0"))
PICASO_KZZ_CGS = float(os.environ.get("ROADRUNNER_PICASO_KZZ_CGS", "1e9"))
PICASO_CLOUD_MODEL = os.environ.get("ROADRUNNER_PICASO_CLOUD_MODEL", "virga")
DEFAULT_PICASO_VIRGA_CONDENSATES = "H2O,CH4,NH3" #for subneptune, default condensates for virga model fixed jul 17
PICASO_VIRGA_CONDENSATES = os.environ.get(
    "ROADRUNNER_PICASO_VIRGA_CONDENSATES",
    DEFAULT_PICASO_VIRGA_CONDENSATES,
)
PICASO_VIRGA_FSED = float(os.environ.get("ROADRUNNER_PICASO_VIRGA_FSED", "3"))
PICASO_VIRGA_DIR = os.environ.get(
    "ROADRUNNER_PICASO_VIRGA_DIR",
    str(
        PICASO4_REFDATA / "virga" / "virga"
        if (PICASO4_REFDATA / "virga" / "virga").exists()
        else TIMESTEP_REFDATA / "virga"
    ),
)

# ---------------------------------------------------------------------------
# Threshold & wavelength grid
# ---------------------------------------------------------------------------
REFLECT_THRESHOLD = 0.10                        # 10 %
LAM_GRID          = np.linspace(0.3, 1.0, 1200) # µm

# ---------------------------------------------------------------------------
# SLGRID data paths
# ---------------------------------------------------------------------------
_LOCAL_SLGRID_BASE = SCIENCE_INPUTS_DIR / "slgrid"
_LOCAL_SLGRID_PT_DIR = _LOCAL_SLGRID_BASE / "climate"
_LOCAL_SLGRID_CLD_DIR = _LOCAL_SLGRID_BASE / "clouds"
_TIMESTEP_SLGRID_BASE = TIMESTEP_ROOT / "2_9_2026"

SLGRID_BASE = os.environ.get(
    "SLGRID_BASE_DIR",
    str(_LOCAL_SLGRID_BASE)
    if _LOCAL_SLGRID_PT_DIR.exists() and _LOCAL_SLGRID_CLD_DIR.exists()
    else str(_TIMESTEP_SLGRID_BASE),
)
_SLGRID_BASE_PATH = Path(SLGRID_BASE).expanduser()
_BASE_USES_CLEAN_NAMES = (
    (_SLGRID_BASE_PATH / "climate").exists()
    or (_SLGRID_BASE_PATH / "clouds").exists()
)
SLGRID_PT_DIR = os.environ.get(
    "SLGRID_PT_DIR",
    str(_SLGRID_BASE_PATH / "climate")
    if _BASE_USES_CLEAN_NAMES
    else str(_SLGRID_BASE_PATH / "SLGRID Climate Files"),
)
SLGRID_CLD_DIR = os.environ.get(
    "SLGRID_CLD_DIR",
    str(_SLGRID_BASE_PATH / "clouds")
    if _BASE_USES_CLEAN_NAMES
    else str(_SLGRID_BASE_PATH / "SLGRID Cloud Files"),
)
EGP_IRFLUX_DIR = os.environ.get(
    "EGP_IRFLUX_DIR",
    str(SCIENCE_INPUTS_DIR / "egp" / "irflux"),
)

# Per-Teff manual file assignments
SLGRID_FILES_BY_TEFF = {
    1000: {
        "pt":  "SLGRID_T1000_g31_m+000_CO100_fsed3_full.pt",
        "cld": "SLGRID_T1000_g31_m+000_CO100_fsed3_picaso.cld",
    },
    1500: {
        "pt":  "SLGRID_T1500_g31_m+000_CO100_fsed3_full.pt",
        "cld": "SLGRID_T1500_g31_m+000_CO100_fsed3_picaso.cld",
    },
    500: {
        "pt":  "SLGRID_T500_g31_m+000_CO100_fsed3_full.pt",
        "cld": "SLGRID_T500_g31_m+000_CO100_fsed3_picaso.cld",
    },
}

# Fallback: if a Teff is missing, use another Teff's files
FALLBACK_TEFF_MAP = {
}

# ---------------------------------------------------------------------------
# PICASO availability  (lazy — imported here so every module can check)
# ---------------------------------------------------------------------------
HAVE_PICASO = False
try:
    from picaso import justdoit as jdi   # noqa: F401
    from picaso import justplotit as jpi  # noqa: F401
    from picaso.fluxes import blackbody   # noqa: F401
    HAVE_PICASO = True
except Exception:
    jdi = None
    jpi = None
    blackbody = None
