# Aurora HPC Install Guide

This guide records how to install Aurora on the University of Arizona HPC and how the large ignored data folders were moved from the local Mac to HPC storage.

Aurora's code is stored in GitHub. The large reference/input folders are intentionally not stored in GitHub.

## 1. Clone Aurora On HPC

In the HPC terminal:

```bash
cd ~/Documents
git clone https://github.com/DevXinHuang/aurora.git
cd aurora
```

## 2. Start An Interactive Compute Session

On the login node, the prompt may look like this:

```text
danielxinhuang@wentletrap
```

The `module` command may not work there. Start an interactive compute session first:

```bash
interactive
```

If you know your HPC group/account, use it:

```bash
interactive -a YOUR_GROUP_NAME
```

To check available allocations/groups:

```bash
va
groups
id -Gn
```

Wait until the job is allocated and the prompt changes to a compute node, for example:

```text
danielxinhuang@r6u19n1
```

## 3. Load Micromamba

On the compute node:

```bash
module avail micromamba
module load micromamba
micromamba --version
```

Expected result:

```text
2.0.2
```

## 4. Create The PICASO4 Environment

From the Aurora repo:

```bash
cd ~/Documents/aurora
micromamba create -n picaso4 python=3.11 -y
```

Initialize the shell for micromamba activation:

```bash
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
```

Install PICASO and common runtime packages:

```bash
python -m pip install --upgrade pip
python -m pip install picaso jupyter ipykernel pandas numpy scipy matplotlib astropy numba
python -m ipykernel install --user --name picaso4 --display-name "Python (picaso4)"
```

Check that Python is coming from the `picaso4` environment:

```bash
which python
python --version
```

Test the PICASO import:

```bash
python - <<'PY'
import picaso
print("PICASO OK:", picaso.__file__)
PY
```

## 5. Large Folders Not Stored In GitHub

These folders are required for Aurora runs, but they are ignored by Git:

```text
picaso4_reference/
science_inputs/
```

Expected local sizes:

```text
picaso4_reference/  about 9.8G
science_inputs/     about 9.6G
```

`science_inputs/` contains:

```text
science_inputs/slgrid/climate/
science_inputs/slgrid/clouds/
science_inputs/egp/irflux/
```

`picaso4_reference/` contains PICASO reference data, opacities, stellar grids, and Virga data.

## 6. Clean Any Partial Bad Copy On HPC

If a previous transfer only copied part of the ignored data, clean it on HPC before retrying:

```bash
cd ~/Documents/aurora
rm -rf science_inputs/egp science_inputs/slgrid picaso4_reference
mkdir -p science_inputs
git checkout -- science_inputs/README.md
```

## 7. Copy `science_inputs/` From The Mac To HPC

Run this from a local Mac terminal, not from the HPC terminal.

If the prompt says `@wentletrap`, `@gatekeeper`, or `@r6u19n1`, that terminal is inside HPC. Open a new Mac terminal instead.

```bash
rsync -avh --progress --partial --delete \
  /Users/xin/Documents/Documents/College/aurora/science_inputs/ \
  danielxinhuang@filexfer.hpc.arizona.edu:~/Documents/aurora/science_inputs/
```

The first connection may ask:

```text
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type:

```text
yes
```

If the transfer stops, rerun the same `rsync` command. The `--partial` flag lets it resume.

## 8. Copy `picaso4_reference/` From The Mac To HPC

Run this from a local Mac terminal:

```bash
rsync -avh --progress --partial --delete \
  /Users/xin/Documents/Documents/College/aurora/picaso4_reference/ \
  danielxinhuang@filexfer.hpc.arizona.edu:~/Documents/aurora/picaso4_reference/
```

This folder can also be regenerated on HPC with:

```bash
cd ~/Documents/aurora
micromamba activate picaso4
python env/setup_picaso4_reference_data.py
```

Copying it with `rsync` is useful when the local Mac copy is already complete and verified.

## 9. Verify The Copied Data On HPC

On the HPC compute node:

```bash
cd ~/Documents/aurora
du -sh science_inputs picaso4_reference
find science_inputs/slgrid/climate -type f | wc -l
find science_inputs/slgrid/clouds -type f | wc -l
find science_inputs/egp/irflux -type f | wc -l
```

Expected approximate results:

```text
science_inputs      about 9.6G
picaso4_reference   about 9.8G
climate files       11603
cloud files         12591
EGP IRflux files    69
```

## 10. Activate Aurora Runtime Paths

On HPC:

```bash
cd ~/Documents/aurora
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_roadrunner_picaso4.sh
```

This sets:

```text
picaso_refdata
PYSYN_CDBS
SLGRID_PT_DIR
SLGRID_CLD_DIR
EGP_IRFLUX_DIR
ROADRUNNER_SCIENCE_INPUTS
```

## 11. Run A Smoke Test

```bash
python - <<'PY'
import picaso
print("PICASO:", picaso.__file__)

from roadrunner.system import summarize_slgrid_inventory
print(summarize_slgrid_inventory())
PY
```

If this sees the SLGRID and EGP files, the HPC migration is ready for science runs.

## 12. Optional Validation

Aurora includes a legacy comparison script:

```bash
python validation/validate_picaso4_against_legacy.py
```

This script compares PICASO4 against the old frozen PICASO 3.4 baseline. On HPC, the old local Mac baseline may not exist, so this script may need adjustment before it can fully run there. The first required HPC check is that PICASO4 imports and RoadRunner sees the copied `science_inputs/` data.
