Source Routes
=============

Aurora supports three atmosphere and thermal-emission source routes,
controlled by the ``thermal_source`` and ``atmosphere_source`` settings
in each run configuration.

Route Reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 8 25 30 37

   * - Route
     - Correct name
     - Settings
     - Meaning
   * - **A**
     - Pure PICASO / full PICASO
     - ``thermal_source="picaso"``
       ``atmosphere_source="picaso"``
     - PICASO-generated atmosphere + PICASO reflected light + PICASO thermal
       emission.  Fast, flexible parameter exploration without SLGRID files.
   * - **B**
     - PICASO atmosphere + EGP thermal
     - ``thermal_source="egp"``
       ``atmosphere_source="picaso"``
     - PICASO-generated atmosphere and PICASO reflected light, paired with the
       matching EGP ``*_IRflux.txt`` thermal spectrum.  Hybrid tests using EGP
       thermal emission while avoiding SLGRID PT/cloud files.
   * - **C**
     - SLGRID/EGP legacy hybrid
     - ``thermal_source="egp"``
       ``atmosphere_source="slgrid"``
     - SLGRID PT/cloud atmosphere loaded into PICASO for reflected light, paired
       with EGP thermal emission.  Most physically consistent with the older
       Roman/RoadRunner workflow.

.. note::

   *EGP only* is useful as a thermal-emission validation baseline, but it is
   not a complete reflected-light confusion route by itself because the
   reflected-light calculation still comes from PICASO.

The Aurora sub-Neptune production grid uses **Route A** exclusively.  Routes B
and C are supported in the RoadRunner/EGP hybrid workflows for legacy
comparisons and validation.

Choosing a Route
----------------

Use this decision tree to pick the right route:

* **No SLGRID files available → Route A.** Run pure PICASO for both the
  atmosphere and the thermal emission.  This is the recommended default for
  new science grids.
* **SLGRID atmosphere + EGP thermal → Route C.** Most physically consistent
  with the older Roman CGI workflow; useful when you need to compare directly
  with earlier EGP-based results.
* **PICASO atmosphere + EGP thermal → Route B.** Hybrid mode when you want
  EGP thermal emission but do not have SLGRID files, or when SLGRID files
  would introduce additional uncertainty.

Configuration
-------------

Route is set per run in the workflow configuration file or directly in the
Python API:

.. code-block:: python

   from workflows.pure_picaso import run_pure_picaso_spectrum

   result = run_pure_picaso_spectrum(
       planet_params=...,
       star_params=...,
       cloud_params=...,
       thermal_source="picaso",
       atmosphere_source="picaso",
   )
