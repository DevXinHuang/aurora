Sub-Neptune Grid Structure
==========================

Aurora computes reflected-light spectra for sub-Neptune planets across a
multi-dimensional parameter space spanning host star properties, planet
physical parameters, cloud properties, and orbital geometry.

Overview
--------

The supported production grid ``aurora_subneptune_v1`` contains **960,000
spectra** grouped into **40,000 climate groups**.  Its nominal Cartesian axes
define 1,080,000 spectra and 45,000 gravity-based climate groups, but the 100× solar
metallicity, 2× solar C/O chemistry pair is excluded because the required
PICASO 4 correlated-k opacity table is unavailable.  Smaller grids are
available for pipeline validation and HPC timing tests.  The earlier
``aurora_subneptune_v0`` grid remains available as a legacy baseline.

.. list-table:: Available Aurora grids
   :header-rows: 1
   :widths: 35 15 15 35

   * - Grid name
     - Spectra
     - Climate groups
     - Purpose
   * - ``smoke_test_aurora_subneptune``
     - 6
     - 2
     - Minimal plumbing check
   * - ``hpc_validation_aurora_subneptune``
     - 1,728
     - 576
     - HPC timing, stability, and QC
   * - ``aurora_cahoy2010_replication_v0``
     - 304
     - 16
     - 1-to-1 Cahoy et al. 2010 replication
   * - ``aurora_subneptune_v1``
     - 960,000
     - 40,000
     - Supported production science grid (current)
   * - ``aurora_subneptune_v0``
     - 276,480
     - 46,080
     - Legacy full-grid baseline

Two-Stage Workflow
------------------

Each spectrum is computed in two stages to avoid redundant climate calculations.
Planet radius and phase angle are spectrum-only parameters — the
pressure–temperature profile does not change with either. All manifest rows
that share gravity, star, cloud, chemistry, and orbit parameters belong to the
same *climate group* and share one cached solution. Each v1 climate feeds four
radii and six phase angles, for 24 spectra.

.. list-table:: Two-stage compute stages
   :header-rows: 1
   :widths: 15 30 20 35

   * - Stage
     - What runs
     - Array size
     - Typical cost
   * - **1 — Climate**
     - Converge PICASO climate once per ``climate_group_index``
     - ``N_climate``
     - Heavy (~15–45 min / group)
   * - **2 — Spectrum**
     - Load cached PT, compute reflected spectrum per manifest row
     - ``N_rows``
     - Light (~2–10 min / row)

Output file layout::

   outputs/<model_name>/
     climate_cache/climate_00.npz … climate_NN.npz   ← stage 1
     nc/run_000000.nc …                              ← stage 2

Parameter Axes (``aurora_subneptune_v1``)
-----------------------------------------

The full production grid uses **surface gravity as the climate planet axis**.
Planet radius varies in the spectral stage, and mass is derived per spectrum as
:math:`M = gR^2/G` for comparison with measured values.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Parameter
     - Values
   * - Host star T\ :sub:`eff` / R\ :sub:`star`
     - (3500 K, 0.45 R\ :sub:`☉`), (4000 K, 0.63 R\ :sub:`☉`), (5000 K, 0.80 R\ :sub:`☉`), (6000 K, 1.00 R\ :sub:`☉`), (7000 K, 1.70 R\ :sub:`☉`)
   * - Planet radius (R\ :sub:`⊕`)
     - 1.6, 2.0, 2.5, 3.0
   * - Surface gravity (m s\ :sup:`−2`)
     - 5, 10, 15, 25, 30
   * - Metallicity (× solar)
     - 1, 10, 100
   * - C/O ratio (× solar)
     - 0.5, 1.0, 2.0
   * - K\ :sub:`zz` (cm\ :sup:`2` s\ :sup:`−1`)
     - 10\ :sup:`9`, 10\ :sup:`11`
   * - Cloud fraction
     - 0 (cloud-free), 0.5, 0.75, 0.9, 1 (fully cloudy)
   * - f\ :sub:`sed`
     - 0.3, 1, 3, 6, 8
   * - Insolation (S\ :sub:`⊕`)
     - 0.35, 0.70, 1.00, 1.50
   * - Phase (deg)
     - 0, 30, 60, 90, 120, 150
   * - Internal temperature T\ :sub:`int`
     - Fixed at 50 K; equilibrium temperature is calculated separately

The nominal Cartesian product is **1,080,000** spectra = **45,000** climate
groups × **4** radii × **6** phases.  PICASO 4 provides eight of the nine requested
metallicity/C/O correlated-k tables.  The unsupported pair is:

* metallicity = 100× solar and C/O = 2× solar, which maps to the unavailable
  ``sonora_2121grid_feh2.0_co1.10.hdf5`` table.

Omitting that pair before manifest indexing removes **5,000 climate groups**
and **120,000 spectra**. The supported production total is therefore **40,000
climate groups** and **960,000 spectra**; unsupported cases have no manifest,
cache, or output indices.

Cloud Parameters
----------------

Cloud properties are parameterized using Virga (Batalha & Rooney 2022):

**f**\ :sub:`sed` — *sedimentation efficiency*
   Controls how quickly cloud particles fall out.  A small f\ :sub:`sed`
   produces thick, vertically extended clouds with small particles; a large
   value produces thin clouds with large particles.

**K**\ :sub:`zz` — *eddy diffusion coefficient*
   Describes the strength of vertical mixing.  Larger values produce more
   vigorous mixing and sustain smaller particles at higher altitudes.
   See Mukherjee et al. (2022) for discussion of K\ :sub:`zz` parameterisation.

The two values K\ :sub:`zz` = 10\ :sup:`9` and 10\ :sup:`11` cm\ :sup:`2` s\ :sup:`−1`
bracket a wide range of mixing regimes in sub-Neptune atmospheres.

Fractional cloud fractions (0.5, 0.75, 0.9) use PICASO's native patchy-cloud
API (clear holes with ``fhole = 1 - cloud_fraction``).

Spectral Coverage
-----------------

Spectra are computed over the full PICASO reflected-light range (~0.3–2.5 μm),
capturing:

* **Rayleigh scattering slope** (< 0.5 μm)
* **Water vapour bands** (0.72, 0.82, 0.94, 1.14, 1.38, 1.87 μm)
* **Methane bands** (0.89, 1.0, 1.38, 1.67, 2.30 μm)
* **Ammonia features** (1.0, 1.5, 2.0 μm)
* **H**\ :sub:`2`\ **/He CIA continuum**

Diagnostics are further evaluated on HWO-relevant sub-ranges to assess
wavelength-coverage requirements for planet typing.

Submitting Grids on HPC
------------------------

.. code-block:: bash

   # Smoke test
   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh \
     "$(pwd)" smoke_test_aurora_subneptune

   # HPC validation
   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh \
     "$(pwd)" hpc_validation_aurora_subneptune

   # Cahoy 2010 replication
   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh

   # Full production grid
   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh \
     "$(pwd)" aurora_subneptune_v1

Stage 2 waits on stage 1 via ``--dependency=afterok``.  Large grids (> 1,000
tasks) are automatically submitted in batches.

Manual Stage Commands
---------------------

.. code-block:: bash

   source env/activate_aurora_picaso4_job.sh

   # Generate manifest with climate_group_index
   python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
     --config roadrunner_egp/aurora_subneptune_grid/params/hpc_validation.yaml \
     --out roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv

   # Stage 1 — converge one climate group
   python roadrunner_egp/aurora_subneptune_grid/scripts/run_climate_cache_chunk.py \
     --manifest roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv \
     --climate-group-index 0

   # Stage 2 — compute one spectrum from cached climate
   python roadrunner_egp/aurora_subneptune_grid/scripts/run_spectrum_from_cache_chunk.py \
     --manifest roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv \
     --array-index 0 \
     --model-name hpc_validation_aurora_subneptune
