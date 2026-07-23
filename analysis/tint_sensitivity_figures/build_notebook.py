from __future__ import annotations

import argparse
import json
from pathlib import Path

import nbformat as nbf


def build(package: Path, output: Path) -> None:
    manifest = json.loads((package / "frozen_manifest.json").read_text(encoding="utf-8"))
    included = manifest["included_models"]
    mode = manifest["mode"].upper()
    thermal_count = len(manifest["corrected_thermal_indices"])
    notebook = nbf.v4.new_notebook()
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Python 3 (PICASO 4)",
        "language": "python",
        "name": "picaso4",
    }
    notebook["cells"] = [
        nbf.v4.new_markdown_cell(
            f"# Tint-sensitivity figure package\n\n"
            f"## tl;dr\n\n"
            f"This is the **{mode}** frozen analysis package with **{included}/36** included models. "
            f"Corrected thermal spectra are available for **{thermal_count}** models. Partial figures "
            "are diagnostic only; missing panels and non-converged curves are intentionally visible."
        ),
        nbf.v4.new_markdown_cell(
            "## Context & Methods\n\n"
            "The source cohort is fixed by `frozen_manifest.json`, including SHA-256 hashes. "
            "Tint is encoded by color (25/50/100 K), while dashed lines indicate climate non-convergence.\n\n"
            "### Key Assumptions\n\n"
            "The 1 mbar abundance is a standardized transmission-photosphere proxy, not a contribution-function-derived photosphere. "
            "The 20–50 ppm JWST band is illustrative rather than instrument/mode/target-specific."
        ),
        nbf.v4.new_markdown_cell("## Data\n\n### 1. Load the frozen manifest and summary tables"),
        nbf.v4.new_code_cell(
            "from pathlib import Path\n"
            "import json\n"
            "import pandas as pd\n"
            "from IPython.display import Image, display\n\n"
            f"package = Path({str(package)!r})\n"
            "manifest = json.loads((package / 'frozen_manifest.json').read_text())\n"
            "summary = pd.read_csv(package / 'tables/photospheric_abundances_1mbar.csv')\n"
            "h2o = pd.read_csv(package / 'tables/h2o_sanity_check.csv')\n"
            "wogan = pd.read_csv(package / 'tables/k2_18b_wogan_direction_check.csv')\n"
            "{key: manifest[key] for key in ['mode', 'expected_models', 'included_models', 'nonconverged_indices', 'corrected_thermal_indices']}"
        ),
        nbf.v4.new_markdown_cell("### 2. Confirm the 36-row writeup table"),
        nbf.v4.new_code_cell(
            "assert len(summary) == 36\n"
            "summary[['run_index','case_id','tint_k','cloud_id','metallicity_xsolar','status','climate_converged']].head(12)"
        ),
        nbf.v4.new_markdown_cell("## Results\n\n### 3. Inspect representative figures"),
        nbf.v4.new_code_cell(
            "for name in [\n"
            "    'pt_k2_18b_observed.png',\n"
            "    'spectra_transmission_k2_18b_observed.png',\n"
            "    'abundance_k2_18b_observed_cloud_free_100x.png',\n"
            "    'residual_transmission.png',\n"
            "    'case_metric_transmission.png',\n"
            "]:\n"
            "    display(Image(filename=str(package / 'figures' / name), width=950))"
        ),
        nbf.v4.new_markdown_cell("### 4. Evaluate chemistry sanity checks"),
        nbf.v4.new_code_cell("display(h2o)\ndisplay(wogan)"),
        nbf.v4.new_markdown_cell(
            "## Takeaways\n\n"
            "- Use `FIGURE_INDEX.md` to navigate all 31 figure designs and 62 exports.\n"
            "- Treat dashed curves and hatched bars as provisional.\n"
            "- Thermal panels remain blank until corrected unit-consistent model outputs are present.\n"
            "- Rebuild the final package only after its strict 36/36 convergence gate passes."
        ),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(notebook, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.package.resolve(), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
