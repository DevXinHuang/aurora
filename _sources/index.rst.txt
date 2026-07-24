Aurora
======

Aurora is a forward-model grid of sub-Neptune reflected-light spectra generated
with `PICASO <https://natashabatalha.github.io/picaso>`_ and
`Virga <https://natashabatalha.github.io/virga>`_ for directly imaging and
spectrally characterizing exoplanets near the radius valley with future missions
such as the `Habitable Worlds Observatory (HWO) <https://science.nasa.gov/astrophysics/programs/habitable-worlds-observatory>`_.

Aurora is developed in Ty Robinson's HabLab at the University of Arizona
as part of an investigation into whether sub-Neptunes can masquerade as
terrestrial worlds in low-resolution reflected-light spectroscopy.

.. important::

   This project is under active development.  Grid results will be released
   publicly once the full ``aurora_subneptune_v1`` run completes on HPC.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Overview

   science
   installation

.. toctree::
   :maxdepth: 2
   :caption: The Sub-Neptune Grid

   grid_structure
   progress_graph
   source_routes

.. toctree::
   :maxdepth: 2
   :caption: Model Case Studies

   cahoy2010_replication
   subneptune_models

Changelog
---------

0.1.0 (2026-06)
   - Initial Aurora sub-Neptune PICASO grid runner and two-stage HPC workflow.
   - Cahoy et al. 2010 replication grid (304 spectra, 16 climate groups).
   - Smoke-test and HPC-validation grids for pipeline QC.
