"""
ROADRUNNER — Roman Observational Albedo & Direct-imaging Retrieval
       for Unified Near-infrared & optical Noise & Emission Ratios
===================================================================

A modular pipeline for evaluating reflected and thermal contributions
in Roman CGI bands, using PICASO + Virga.

Quick start::

    from roadrunner import SystemParams, evaluate_case, run_grid_parallel

    case = SystemParams(teff_k=1000, logg_cgs=3.5, rj=1.0,
                        a_au=10.0, phase_deg=0.0)
    df = evaluate_case(case, do_plots=True)
"""

from .system import (                                         # noqa: F401
    SystemParams,
    available_slgrid_teffs,
    summarize_slgrid_inventory,
)
from .bands  import (                                        # noqa: F401
    BANDS,
    band_metrics,
    evaluate_case,
    normalize_band_names,
    select_bands,
    wavelength_grid_for_bands,
)
from .grid   import run_grid_parallel                         # noqa: F401
from .runner import (                                         # noqa: F401
    configure_picaso_atmosphere,
    normalize_atmosphere_source,
    run_picaso_once,
)
from .config import (                                         # noqa: F401
    CGI_BANDS, LAM_GRID, REFLECT_THRESHOLD,
    TEFFS_K, LOGGS_CGS, R_PLANETS_Rj, SEMI_MAJOR_AU, PHASE_DEG,
    HAVE_PICASO,
)
from .plotting import (                                       # noqa: F401
    plot_spectra_with_bb,
    plot_band_bars,
    plot_summary_histogram,
    plot_summary_heatmaps,
)

__version__ = "0.1.0"
