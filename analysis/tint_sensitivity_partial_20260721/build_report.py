from __future__ import annotations

import csv
import json
from pathlib import Path


OUT = Path(__file__).resolve().parent
GENERATED_AT = "2026-07-21T17:21:30Z"


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: str) -> float:
    return float(value)


coverage_raw = read_csv("coverage.csv")
case_raw = {row["case_id"]: row for row in read_csv("case_summary.csv")}
models_raw = read_csv("model_summary.csv")
tint_raw = read_csv("tint_sensitivity.csv")
failure_raw = read_csv("failure_summary.csv")

case_labels = {
    "k2_18b_observed": "K2-18 b observed (255 K)",
    "gj_1214b_low": "GJ 1214 b low (255 K)",
    "gj_1214b_observed": "GJ 1214 b observed (500 K)",
}

coverage = []
for row in coverage_raw:
    summary = case_raw[row["case_id"]]
    coverage.append(
        {
            "case": case_labels[row["case_id"]],
            "valid_models": int(row["valid_models"]),
            "expected_models": int(row["expected_models"]),
            "coverage_rate": number(row["coverage_rate"]),
            "converged_models": int(row["converged_models"]),
            "nonconverged_models": int(row["nonconverged_models"]),
            "median_transmission_modulation_ppm": number(
                summary["median_transmission_modulation_ppm"]
            ),
            "transmission_modulation_min_ppm": number(
                summary["minimum_transmission_modulation_ppm"]
            ),
            "transmission_modulation_max_ppm": number(
                summary["maximum_transmission_modulation_ppm"]
            ),
            "median_temperature_1bar_k": number(summary["median_temperature_1bar_k"]),
        }
    )

tint_pairs = []
for row in tint_raw:
    converged = row["both_endpoints_converged"] == "True"
    if not converged:
        continue
    tint_pairs.append(
        {
            "pair": row["pair_label"].replace("gj 1214b", "GJ 1214 b").replace(
                "k2 18b", "K2-18 b"
            ),
            "case": case_labels[row["case_id"]],
            "cloud": row["cloud"],
            "metallicity_xsolar": number(row["metallicity_xsolar"]),
            "rms_transmission_change_ppm": number(row["rms_transmission_change_ppm"]),
            "maximum_transmission_change_ppm": number(
                row["maximum_transmission_change_ppm"]
            ),
            "temperature_1bar_change_k": number(row["temperature_1bar_change_k"]),
            "both_endpoints_converged": True,
        }
    )

failure_details = {
    "Quench point below pressure grid": {
        "severity": "High",
        "cause": "The default Guillot grid ended at 31.6 bar, above the hot-case CO–CH4–H2O quench crossing.",
        "remediation": "Use Tint-dependent deep grids (10^6, 10^5, 10^4 bar for 25, 50, 100 K) and rerun hot models.",
    },
    "Planet radius unavailable to transmission": {
        "severity": "High",
        "cause": "PICASO's gravity-only setup branch discarded the supplied radius, leaving transit depth non-finite.",
        "remediation": "Initialize with mass plus radius, then overwrite gravity with the exact coupled-case value.",
    },
    "Virga particle root below physical floor": {
        "severity": "High",
        "cause": "At one 100x-metallicity cloudy layer, the settling-speed root fell below Virga's 0.1-nm particle floor at fixed Kzz.",
        "remediation": "Clamp only that endpoint to Virga's documented minimum radius, record the clamp count, and rerun affected cloudy models.",
    },
    "Returned profile omitted kz": {
        "severity": "Medium",
        "cause": "PICASO retained constant Kzz internally but omitted kz from the returned ptchem_df.",
        "remediation": "Verify the internal constant_kzz array and reattach 1e10 cm2/s to the saved final profile.",
    },
}
failures = []
for row in failure_raw:
    detail = failure_details[row["category"]]
    failures.append(
        {
            "stage": row["stage"],
            "failure_category": row["category"],
            "severity": detail["severity"],
            "failed_attempt_logs": int(row["failed_attempt_logs"]),
            "unique_run_indices": int(row["unique_run_indices"]),
            "root_cause": detail["cause"],
            "remediation": detail["remediation"],
        }
    )

models = []
nonconverged = []
for row in models_raw:
    model = {
        "run_index": int(row["run_index"]),
        "case": case_labels[row["case_id"]],
        "tint_k": number(row["tint_k"]),
        "cloud": row["cloud"],
        "metallicity_xsolar": number(row["metallicity_xsolar"]),
        "climate_converged": row["climate_converged"] == "True",
        "transmission_modulation_ppm": number(row["transmission_modulation_ppm"]),
        "visible_albedo_median": number(row["visible_albedo_median"]),
        "temperature_1bar_k": number(row["temperature_1bar_k"]),
        "max_quench_difference_dex": number(row["max_quench_difference_dex"]),
    }
    models.append(model)
    if not model["climate_converged"]:
        nonconverged.append(model)

sources = [
    {
        "id": "model-source",
        "label": "Frozen 26-model NetCDF summary",
        "path": "model_summary.csv",
        "query": {
            "description": "Python/xarray profile of the explicit 26-file NetCDF snapshot.",
            "language": "python",
            "executed_at": GENERATED_AT,
            "filters": [
                "Explicit run indices 0-25 only",
                "Snapshot frozen while corrected Slurm array remained active",
            ],
            "metric_definitions": [
                "Transmission modulation = (maximum transit depth - minimum transit depth) × 10^6 ppm over 0.6-15 µm",
                "Visible albedo median = median geometric albedo over 0.6-1.0 µm",
            ],
        },
    },
    {
        "id": "tint-source",
        "label": "Tint endpoint sensitivity calculations",
        "path": "tint_sensitivity.csv",
        "query": {
            "description": "Wavelength-wise Tint=100 K minus Tint=25 K transmission comparisons.",
            "language": "python",
            "executed_at": GENERATED_AT,
            "filters": ["Otherwise identical models", "Chart includes converged endpoints only"],
            "metric_definitions": [
                "RMS transmission change = sqrt(mean((depth_100K-depth_25K)^2)) × 10^6 ppm"
            ],
        },
    },
    {
        "id": "failure-source",
        "label": "Slurm traceback classification",
        "path": "failure_summary.csv",
        "query": {
            "description": "Classification of every non-empty traceback log available at the snapshot time.",
            "language": "python",
            "executed_at": GENERATED_AT,
            "filters": ["Traceback-containing .err files only", "Counts are attempts, not final model counts"],
        },
    },
    {
        "id": "thermal-source",
        "label": "Thermal ratio dimensional audit",
        "path": "thermal_ratio_issue.txt",
        "query": {
            "description": "Code-path and unit audit of PICASO climate fpfs_thermal calculation.",
            "language": "text",
            "executed_at": GENERATED_AT,
        },
    },
]

headline = [
    {
        "valid_models": 26,
        "expected_models": 36,
        "coverage_rate": 26 / 36,
        "converged_models": 19,
        "valid_model_convergence_rate": 19 / 26,
        "missing_or_failed_models": 10,
        "thermal_ratio_reliable": False,
    }
]

manifest = {
    "version": 1,
    "surface": "report",
    "title": "PICASO Tint Sensitivity: Partial 26-Model Analysis",
    "description": "Scientific findings, data-quality assessment, and failure diagnosis for the frozen partial experiment.",
    "generatedAt": GENERATED_AT,
    "sources": sources,
    "cards": [
        {
            "id": "coverage-card",
            "dataset": "headline",
            "sourceId": "model-source",
            "description": "Schema-valid, unique, restartable NetCDF models in the frozen 36-model design.",
            "metrics": [
                {"label": "Valid models", "field": "valid_models", "format": "number"},
                {"label": "Expected", "field": "expected_models", "format": "number"},
                {"label": "Coverage", "field": "coverage_rate", "format": "percent"},
            ],
        },
        {
            "id": "convergence-card",
            "dataset": "headline",
            "sourceId": "model-source",
            "description": "Saved valid files whose PICASO climate convergence flag is true.",
            "metrics": [
                {"label": "Converged models", "field": "converged_models", "format": "number"},
                {
                    "label": "Of valid files",
                    "field": "valid_model_convergence_rate",
                    "format": "percent",
                },
            ],
        },
        {
            "id": "remaining-card",
            "dataset": "headline",
            "sourceId": "model-source",
            "description": "Designed models without a valid frozen-snapshot output.",
            "metrics": [
                {
                    "label": "Missing or failed",
                    "field": "missing_or_failed_models",
                    "format": "number",
                }
            ],
        },
    ],
    "charts": [
        {
            "id": "tint-rms-chart",
            "title": "Transmission sensitivity to Tint",
            "subtitle": "Tint=100 K versus 25 K; converged endpoint pairs only, RMS across 0.6-15 µm",
            "intent": "comparison",
            "question": "How much does Tint change the transmission spectrum when all other model inputs are fixed?",
            "rationale": "A horizontal bar chart makes six discrete, long-label model-pair comparisons readable and keeps a zero baseline.",
            "comparisonContext": {
                "baseline": "Tint=25 K",
                "grain": "case × cloud × metallicity endpoint pair",
                "unit": "ppm RMS",
            },
            "type": "horizontalBar",
            "dataset": "tint_pairs_converged",
            "sourceId": "tint-source",
            "encodings": {
                "x": {
                    "field": "rms_transmission_change_ppm",
                    "type": "quantitative",
                    "format": "number",
                    "label": "RMS transmission change",
                    "unit": "ppm",
                },
                "y": {"field": "pair", "type": "nominal", "label": "Model pair"},
                "tooltip": [
                    {"field": "maximum_transmission_change_ppm", "type": "quantitative", "label": "Maximum change", "unit": "ppm"},
                    {"field": "temperature_1bar_change_k", "type": "quantitative", "label": "1-bar temperature change", "unit": "K"},
                    {"field": "case", "type": "text", "label": "Case"},
                ],
            },
            "valueFormat": "number",
            "unit": "ppm",
            "layout": "full",
        }
    ],
    "tables": [
        {
            "id": "case-table",
            "title": "Coverage and transmission summary by coupled case",
            "subtitle": "Frozen snapshot; transmission values are peak-to-trough over 0.6-15 µm",
            "dataset": "coverage",
            "sourceId": "model-source",
            "defaultSort": {"field": "case", "direction": "asc"},
            "density": "spacious",
            "layout": "full",
            "columns": [
                {"field": "case", "label": "Case", "type": "text"},
                {"field": "valid_models", "label": "Valid", "format": "number"},
                {"field": "expected_models", "label": "Expected", "format": "number"},
                {"field": "converged_models", "label": "Converged", "format": "number"},
                {"field": "median_transmission_modulation_ppm", "label": "Median modulation (ppm)", "format": "number"},
                {"field": "median_temperature_1bar_k", "label": "Median T at 1 bar (K)", "format": "number"},
            ],
        },
        {
            "id": "failure-table",
            "title": "Why attempts failed",
            "subtitle": "Traceback counts describe execution attempts, not unique final scientific models",
            "dataset": "failures",
            "sourceId": "failure-source",
            "defaultSort": {"field": "failed_attempt_logs", "direction": "desc"},
            "density": "spacious",
            "layout": "full",
            "columns": [
                {"field": "stage", "label": "Stage", "type": "text"},
                {"field": "failure_category", "label": "Failure", "type": "text"},
                {"field": "severity", "label": "Severity", "type": "text"},
                {"field": "failed_attempt_logs", "label": "Attempt logs", "format": "number"},
                {"field": "unique_run_indices", "label": "Unique indices", "format": "number"},
                {"field": "root_cause", "label": "Root cause", "type": "text"},
                {"field": "remediation", "label": "Remediation", "type": "text"},
            ],
        },
        {
            "id": "nonconverged-table",
            "title": "Saved models with climate_converged=false",
            "subtitle": "Finite, schema-valid outputs that remain provisional",
            "dataset": "nonconverged",
            "sourceId": "model-source",
            "defaultSort": {"field": "run_index", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "run_index", "label": "Index", "format": "number"},
                {"field": "case", "label": "Case", "type": "text"},
                {"field": "tint_k", "label": "Tint (K)", "format": "number"},
                {"field": "cloud", "label": "Cloud", "type": "text"},
                {"field": "metallicity_xsolar", "label": "Metallicity (× solar)", "format": "number"},
                {"field": "transmission_modulation_ppm", "label": "Modulation (ppm)", "format": "number"},
            ],
        },
        {
            "id": "model-table",
            "title": "All 26 frozen-snapshot models",
            "subtitle": "Exact model-level values used in this partial analysis",
            "dataset": "models",
            "sourceId": "model-source",
            "defaultSort": {"field": "run_index", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "run_index", "label": "Index", "format": "number"},
                {"field": "case", "label": "Case", "type": "text"},
                {"field": "tint_k", "label": "Tint (K)", "format": "number"},
                {"field": "cloud", "label": "Cloud", "type": "text"},
                {"field": "metallicity_xsolar", "label": "Metallicity (× solar)", "format": "number"},
                {"field": "climate_converged", "label": "Converged", "type": "text"},
                {"field": "transmission_modulation_ppm", "label": "Modulation (ppm)", "format": "number"},
                {"field": "visible_albedo_median", "label": "Visible albedo", "format": "number"},
                {"field": "temperature_1bar_k", "label": "T at 1 bar (K)", "format": "number"},
            ],
        },
    ],
    "blocks": [
        {"id": "title", "type": "markdown", "body": "# PICASO Tint Sensitivity: Partial 26-Model Analysis", "layout": "full"},
        {
            "id": "technical-summary",
            "type": "markdown",
            "body": "## Technical summary\n\nThe frozen cohort has **26/36 valid restart files** and represents all three coupled cases, but only the two 255 K cases are complete. Among converged endpoint pairs, Tint=25→100 K changes transmission by **1.6–9.3 ppm RMS**, smaller than the observed gravity, metallicity, cloud, and Teq contrasts. Seven valid files are nonconverged and remain provisional. Logged failures were caused by identifiable PICASO/Virga interface or numerical-domain issues—not equilibrium-only chemistry—and the current thermal planet/star ratios are excluded because they fail a dimensional audit.",
            "layout": "full",
        },
        {"id": "metrics", "type": "metric-strip", "cardIds": ["coverage-card", "convergence-card", "remaining-card"], "layout": "full"},
        {
            "id": "tint-finding",
            "type": "markdown",
            "body": "## Tint is a secondary transmission driver in the complete 255 K cases\n\nAcross the six converged endpoint pairs, the wavelength-wise RMS change from Tint=25 K to 100 K is 1.6–9.3 ppm. The response is larger at 100× solar than at 1× solar. Read each bar as an otherwise identical model pair; the 500 K case is absent because it does not yet have both Tint endpoints.",
            "sourceId": "tint-source",
            "layout": "full",
        },
        {"id": "tint-chart", "type": "chart", "chartId": "tint-rms-chart", "layout": "full"},
        {
            "id": "case-finding",
            "type": "markdown",
            "body": "## Gravity, metallicity, clouds, and Teq dominate the present contrasts\n\nThe complete lower-gravity GJ 1214 b grid has **23% greater median transmission modulation** than K2-18 b (172.3 versus 139.6 ppm). In converged 100×-solar comparisons, clouds suppress modulation by roughly **40–62 ppm** and increase median visible albedo by about **34–84×**. The two provisional 500 K clear models span **293–496 ppm**, but cannot establish Tint or cloud sensitivity.",
            "sourceId": "model-source",
            "layout": "full",
        },
        {"id": "case-table-block", "type": "table", "tableId": "case-table", "layout": "full"},
        {
            "id": "scope",
            "type": "markdown",
            "body": "## Scope, data, and metric definitions\n\nThe analysis unit is one unique case × Tint × cloud × metallicity model. The frozen file list contains indices 0–25: twelve K2-18 b models, twelve GJ 1214 b low-temperature models, and two clear GJ 1214 b observed-temperature models. Transmission modulation is peak-to-trough transit depth over 0.6–15 µm in ppm. Visible albedo is the median geometric albedo over 0.6–1.0 µm. All included files passed schema, finiteness, constant-Kzz, quench, and uniqueness checks.",
            "sourceId": "model-source",
            "layout": "full",
        },
        {"id": "model-detail", "type": "table", "tableId": "model-table", "layout": "full"},
        {
            "id": "methodology",
            "type": "markdown",
            "body": "## Methodology preserves a frozen denominator\n\nThe companion notebook opens an explicit 26-file list rather than globbing live outputs. It validates required flags and arrays, computes per-model PT and spectral summaries, forms Tint endpoint pairs, and inventories traceback logs. This prevents ongoing Slurm completion from changing the cohort during analysis. Thermal ratios are intentionally omitted from every comparison.",
            "layout": "full",
        },
        {
            "id": "failure-finding",
            "type": "markdown",
            "body": "## Failed attempts have four concrete root causes\n\nThe largest scientific-domain failure was the original 31.6-bar pressure grid: all twelve 500 K attempts placed the CO–CH4–H2O quench crossing below the modeled domain. Earlier preflight failures came from PICASO dropping the radius in its gravity-only branch or omitting kz from the returned dataframe. The latest cloudy 100× hot attempt reached Virga but requested a settling radius below Virga's 0.1-nm physical floor. Counts below describe traceback attempts, so repeated diagnostics must not be read as 24 distinct failed science models.",
            "sourceId": "failure-source",
            "layout": "full",
        },
        {"id": "failure-table-block", "type": "table", "tableId": "failure-table", "layout": "full"},
        {
            "id": "nonconvergence",
            "type": "markdown",
            "body": "## Seven saved models are finite but not converged\n\nThese are not crashed jobs: each produced a valid atomic NetCDF with finite spectra and quenched abundances. However, `climate_converged=false` means the PT solution did not satisfy PICASO's convergence criterion, so these rows should remain provisional. Six of seven are 1×-solar cloudy models; the seventh is K2-18 b, Tint=50 K, cloudy, 100× solar.",
            "sourceId": "model-source",
            "layout": "full",
        },
        {"id": "nonconverged-table-block", "type": "table", "tableId": "nonconverged-table", "layout": "full"},
        {
            "id": "thermal-limitation",
            "type": "markdown",
            "body": "## Thermal planet/star ratios are not decision-ready\n\nThe installed PICASO climate path integrates stellar flux per native bin, then divides a planet spectral flux density by that integrated value. The units do not cancel, and saved ratios reach physically implausible values. Transmission, reflected ratios, albedo, PT, and abundance arrays do not use this thermal division and remain separately analyzable. Final production should correct the native thermal ratio and regenerate affected files.",
            "sourceId": "thermal-source",
            "layout": "full",
        },
        {
            "id": "next-steps",
            "type": "markdown",
            "body": "## Recommended next steps\n\n1. Correct the thermal flux-density/bin-integral mismatch and rerun all outputs that will be used for thermal inference.\n2. Complete the ten missing hot-case files with the adaptive deep grids and recorded Virga minimum-radius guard.\n3. Rerun or tune the seven nonconverged climate cases before final comparative claims.\n4. Repeat this frozen analysis on the final 36/36 validated ensemble and require zero invalid files, constant Kzz, enabled/applied quench flags, and finite spectra.",
            "layout": "full",
        },
        {
            "id": "further-questions",
            "type": "markdown",
            "body": "## Further questions\n\n- Does the full 500 K cloudy ensemble preserve the current 293–496 ppm transmission range?\n- Are the cloudy 1×-solar nonconvergences sensitive to the initial RCB guess or Virga iteration cadence?\n- After a dimensionally correct thermal calculation, does Tint affect thermal emission more strongly than the modest transmission response?",
            "layout": "full",
        },
    ],
}

artifact = {
    "surface": "report",
    "manifest": manifest,
    "snapshot": {
        "version": 1,
        "generatedAt": GENERATED_AT,
        "status": "partial",
        "datasets": {
            "headline": headline,
            "coverage": coverage,
            "tint_pairs_converged": tint_pairs,
            "failures": failures,
            "nonconverged": nonconverged,
            "models": models,
        },
        "accessIssues": [
            {
                "id": "incomplete-hot-case",
                "scope": "GJ 1214 b observed 500 K",
                "dataset": "models",
                "message": "Ten of twelve hot-case models were unavailable in the frozen snapshot; hot-case Tint and cloud comparisons are incomplete.",
            }
        ],
    },
    "sources": sources,
}

(OUT / "artifact.json").write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
print(OUT / "artifact.json")
