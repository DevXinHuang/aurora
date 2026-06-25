Installation
============

Requirements
------------

Aurora targets **PICASO 4** running inside the ``picaso4`` conda environment.
The instructions below cover the HPC/local setup for the University of Arizona
HPC clusters.  Mentions of PICASO 3.4 in the codebase are legacy validation
references only.

.. note::

   Large reference data (opacities, stellar grids, Virga data) are **not**
   tracked in git.  They must be placed in ``picaso4_reference/`` on local disk
   or HPC project storage before running the full pipeline.

Environment Setup
-----------------

.. code-block:: bash

   # Activate the PICASO 4 environment (local)
   source env/activate_local_picaso4.sh

   # Activate the HPC job environment (used in SLURM scripts)
   source env/activate_aurora_picaso4_job.sh

After activating, optionally verify the reference data:

.. code-block:: bash

   python env/setup_picaso4_reference_data.py --check-only

Smoke Test
----------

Run a quick sanity check to confirm the pipeline loads correctly:

.. code-block:: bash

   source env/activate_roadrunner_picaso4.sh
   python - <<'PY'
   from roadrunner.system import summarize_slgrid_inventory
   from workflows.hybrid_reflected_picaso_thermal_egp import available_egp_temperatures

   print(summarize_slgrid_inventory())
   print(available_egp_temperatures("31"))
   PY

Validation
----------

Compare Aurora's PICASO 4 results against the frozen PICASO 3.4 baseline:

.. code-block:: bash

   source env/activate_local_picaso4.sh
   python validation/validate_picaso4_against_legacy.py

Results are written under ``validation/outputs/``.

What Is Not in Git
------------------

The following large data directories are intentionally ignored:

* ``picaso4_reference/`` — PICASO reference data, opacities, stellar grids,
  and Virga data
* ``science_inputs/`` — SLGRID climate/cloud files and EGP IR flux files
* Generated validation outputs, temporary files, and rendered previews

Keep those folders on local disk or HPC project storage, then use the
activation scripts to point Aurora at them.
