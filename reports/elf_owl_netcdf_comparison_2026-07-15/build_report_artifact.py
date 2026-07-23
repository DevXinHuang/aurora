from __future__ import annotations

import json
import sqlite3
from pathlib import Path


REPORT_DIR = Path(__file__).resolve().parent
GENERATED_AT = "2026-07-15T12:00:00-07:00"


def source(source_id: str, label: str, path: str) -> dict:
    return {"id": source_id, "label": label, "path": path}


def write_rows(connection: sqlite3.Connection, table_name: str, rows: list[dict]) -> None:
    fields = list(rows[0])
    type_names = []
    for field in fields:
        values = [row.get(field) for row in rows if row.get(field) is not None]
        if values and all(isinstance(value, (bool, int)) for value in values):
            type_names.append("INTEGER")
        elif values and all(isinstance(value, (bool, int, float)) for value in values):
            type_names.append("REAL")
        else:
            type_names.append("TEXT")
    connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    columns = ", ".join(f'"{field}" {kind}' for field, kind in zip(fields, type_names))
    connection.execute(f'CREATE TABLE "{table_name}" ({columns})')
    placeholders = ", ".join("?" for _ in fields)
    connection.executemany(
        f'INSERT INTO "{table_name}" VALUES ({placeholders})',
        [[int(value) if isinstance(value, bool) else value for value in (row.get(field) for field in fields)] for row in rows],
    )


def main() -> None:
    analysis = json.loads((REPORT_DIR / "analysis.json").read_text())
    variables = json.loads((REPORT_DIR / "variable_inventory.json").read_text())
    elf = analysis["elf"]
    aurora = analysis["aurora"]
    grid = analysis["grid"]
    comparison = analysis["comparison"]

    sources = [
        source(
            "elf_sample",
            "Sonora Elf Owl v2 representative NetCDF",
            "science_inputs/sonora_elf_owl_v2/teff_1300_1500/"
            + elf["representative_file"],
        ),
        source(
            "aurora_sample",
            "AURORA weekend-grid representative NetCDF",
            "outputs/weekend_nc/" + aurora["representative_file"],
        ),
        source(
            "aurora_schema",
            "AURORA NetCDF schema implementation",
            "roadrunner_egp/aurora_subneptune_grid/src/aurora_grid/io/netcdf_schema.py",
        ),
        source(
            "analysis_code",
            "Reproducible NetCDF structure analysis",
            "reports/elf_owl_netcdf_comparison_2026-07-15/analyze_netcdf_structures.py",
        ),
        {
            "id": "grid_coverage_sql",
            "label": "Elf Owl grid coverage query",
            "path": "reports/elf_owl_netcdf_comparison_2026-07-15/analysis.sqlite",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "sql": "SELECT gravity_ms2, gravity_label, model_count, expected_full_count FROM grid_coverage ORDER BY gravity_ms2",
                "description": "Returns the observed Elf Owl model count at each gravity value across the three extracted temperatures.",
                "tables_used": ["grid_coverage"],
                "filters": ["Archive subset: Teff 1300, 1400, and 1500 K"],
                "metric_definitions": ["model_count is the number of extracted NetCDF files at each gravity; expected_full_count is 360 for a complete gravity slice."],
                "executed_at": GENERATED_AT,
            },
        },
    ]

    headline = [
        {
            "elf_files": elf["files"],
            "elf_spectral_points": elf["spectral"]["points"],
            "aurora_spectral_points": aurora["spectral"]["points"],
            "shared_species": len(comparison["shared_species"]),
        }
    ]

    schema_comparison = [
        {
            "aspect": "Scientific target",
            "elf_owl": "Cloud-free, self-luminous L-type atmosphere; thermal emission",
            "aurora": "Irradiated sub-Neptune run; reflected + thermal spectra and cloud/QC products",
            "compatibility": "Different model products",
        },
        {
            "aspect": "Core dimensions",
            "elf_owl": "pressure=91; wavelength=193,132",
            "aurora": "level=61; layer=60; species=50; wavelength=2,201; brightness wavelength=196",
            "compatibility": "Requires remapping",
        },
        {
            "aspect": "Wavelength coverage",
            "elf_owl": "0.6000015–14.9997608 µm, descending",
            "aurora": "0.3–2.5 µm, ascending",
            "compatibility": "Only 0.6–2.5 µm overlaps",
        },
        {
            "aspect": "Spectral sampling",
            "elf_owl": "Approximately constant R=60,000; one stitch interval near 5 µm",
            "aurora": "Uniform Δλ≈0.001 µm; sampling R rises from ~300 to ~2,499",
            "compatibility": "Must choose a target grid",
        },
        {
            "aspect": "Vertical representation",
            "elf_owl": "91 pressure levels; no explicit layer axis",
            "aurora": "61 levels plus 60 derived layers",
            "compatibility": "Interpolate levels; derive layers",
        },
        {
            "aspect": "Chemistry",
            "elf_owl": "38 separate 1-D species variables",
            "aurora": "One mole_fraction(level, species) array with 50 species labels",
            "compatibility": "Stack and normalize metadata",
        },
        {
            "aspect": "Flux units",
            "elf_owl": "flux: erg cm⁻² s⁻¹ cm⁻¹",
            "aurora": "thermal_flux: erg cm⁻² s⁻¹ µm⁻¹",
            "compatibility": "Multiply Elf Owl numeric flux by 10⁻⁴ for per-µm units",
        },
        {
            "aspect": "Metadata/provenance",
            "elf_owl": "5 global attributes; parameters mostly embedded in filename/planet_params",
            "aurora": "27 global attributes; versioned schema, run scalars, code versions, git commit and QC",
            "compatibility": "AURORA requires additional metadata",
        },
        {
            "aspect": "Storage",
            "elf_owl": "All float64; no variable compression/chunking",
            "aurora": "Mixed dtypes; 18 compressed variables in representative file",
            "compatibility": "Re-encode on import",
        },
    ]

    grid_axes = [
        {
            "axis": "Effective temperature",
            "field": "teff",
            "values": ", ".join(f"{v:g}" for v in grid["axes"]["teff_k"]),
            "units": "K",
            "aurora_equivalent": "No direct equivalent; do not substitute equilibrium_temperature_k",
        },
        {
            "axis": "Gravity",
            "field": "grav",
            "values": ", ".join(f"{v:g}" for v in grid["axes"]["gravity_ms2"]),
            "units": "m s⁻²",
            "aurora_equivalent": "gravity_ms2",
        },
        {
            "axis": "Vertical mixing",
            "field": "logzz",
            "values": ", ".join(f"{v:g}" for v in grid["axes"]["logkzz"]),
            "units": "log₁₀(cm² s⁻¹)",
            "aurora_equivalent": "log10(kzz_cm2_s)",
        },
        {
            "axis": "Metallicity",
            "field": "mh",
            "values": ", ".join(f"{v:g}" for v in grid["axes"]["metallicity_dex"]),
            "units": "dex [M/H]",
            "aurora_equivalent": "log10(metallicity_xsolar)",
        },
        {
            "axis": "C/O enrichment",
            "field": "co",
            "values": ", ".join(f"{v:g}" for v in grid["axes"]["c_to_o_xsolar"]),
            "units": "× solar C/O",
            "aurora_equivalent": "c_to_o_xsolar",
        },
    ]

    mapping = [
        {
            "elf_source": "pressure(pressure)",
            "aurora_target": "pressure_bar(level)",
            "transform": "Rename pressure→level or interpolate to the AURORA level grid",
            "status": "Direct concept; different length/range",
        },
        {
            "elf_source": "temperature(pressure)",
            "aurora_target": "temperature_k(level)",
            "transform": "Rename and interpolate consistently with pressure",
            "status": "Direct concept",
        },
        {
            "elf_source": "38 species variables",
            "aurora_target": "mole_fraction(level, species)",
            "transform": "Stack variables along a species coordinate; set units to v/v",
            "status": "37 names overlap; e⁻ naming differs/missing",
        },
        {
            "elf_source": "wavelength(wavelength)",
            "aurora_target": "wavelength_um(wavelength), wavenumber_cm1(wavelength)",
            "transform": "Reverse to ascending; optionally crop/resample; compute 10⁴/λ",
            "status": "Direct coordinate conversion",
        },
        {
            "elf_source": "flux(wavelength)",
            "aurora_target": "thermal_flux(wavelength)",
            "transform": "Reverse with wavelength; multiply by 10⁻⁴ to convert per cm to per µm",
            "status": "Confirm identical physical normalization before scientific comparison",
        },
        {
            "elf_source": "filename logzz",
            "aurora_target": "kzz_cm2_s",
            "transform": "kzz_cm2_s = 10**logzz",
            "status": "Direct parameter conversion",
        },
        {
            "elf_source": "filename mh",
            "aurora_target": "metallicity_xsolar",
            "transform": "metallicity_xsolar = 10**mh",
            "status": "Direct parameter conversion",
        },
        {
            "elf_source": "filename grav",
            "aurora_target": "gravity_ms2",
            "transform": "Copy numeric value",
            "status": "Direct parameter conversion",
        },
        {
            "elf_source": "No layer variables",
            "aurora_target": "layer pressure/temperature and cloud optical fields",
            "transform": "Derive layer centers; cloud fields remain unavailable/NaN",
            "status": "Not present in Elf Owl",
        },
        {
            "elf_source": "No stellar/orbit/reflection data",
            "aurora_target": "stellar, orbit, phase, reflected-light fields",
            "transform": "Do not fabricate; represent as unavailable or use a separate import schema",
            "status": "Scientifically inapplicable",
        },
    ]

    quality_issues = [
        {
            "priority": 1,
            "system": "AURORA",
            "issue": "Spurious species named 'index'",
            "evidence": "Representative values span 307.8–1,067.5; total mole-fraction sums become 308.8–1,068.5. Removing it restores sums to 0.999858–0.999877. Present in all 60 sampled files.",
            "action": "Add 'index' to _IGNORED_PROFILE_COLUMNS, regenerate affected outputs, and add a sum-to-one validation.",
        },
        {
            "priority": 1,
            "system": "Elf Owl",
            "issue": "All 38 chemistry variables incorrectly advertise units='Kelvin'",
            "evidence": "Their level-wise sum is 0.99999987–0.999999997, demonstrating mixing fractions rather than temperatures.",
            "action": "Override units to v/v in an import adapter; preserve original files unchanged.",
        },
        {
            "priority": 2,
            "system": "Crosswalk",
            "issue": "Thermal-flux normalization needs a scientific check beyond unit conversion",
            "evidence": "Elf Owl describes emergent flux requiring R²/D² scaling for observed flux; AURORA's field is a PICASO absolute-flux diagnostic.",
            "action": "Verify both fields are defined at the same reference surface before comparing amplitudes.",
        },
        {
            "priority": 2,
            "system": "Elf Owl grid",
            "issue": "The filename axes are not a full Cartesian grid",
            "evidence": f"{grid['actual_files']:,} files versus {grid['full_cartesian_product']:,} naive combinations ({grid['coverage_fraction']:.1%}); gravity≥17 m s⁻² is complete, while gravity=10 has one special model per Teff.",
            "action": "Build the available-model index from filenames rather than generating expected paths from axis products.",
        },
        {
            "priority": 3,
            "system": "Elf Owl spectrum",
            "issue": "One wavelength-grid stitch interrupts constant R",
            "evidence": "R≈60,000 at 193,130 of 193,131 intervals; the interval around 5 µm has R≈41,595.",
            "action": "Treat R=60,000 as the native sampling with a documented stitch boundary.",
        },
    ]

    grid_coverage = [
        {
            "gravity_ms2": float(gravity),
            "gravity_label": f"{float(gravity):g} m s⁻²",
            "model_count": count,
            "expected_full_count": 360,
        }
        for gravity, count in grid["counts_by_gravity"].items()
    ]
    database_path = REPORT_DIR / "analysis.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE IF EXISTS grid_coverage")
        connection.execute(
            "CREATE TABLE grid_coverage (gravity_ms2 REAL, gravity_label TEXT, model_count INTEGER, expected_full_count INTEGER)"
        )
        connection.executemany(
            "INSERT INTO grid_coverage VALUES (:gravity_ms2, :gravity_label, :model_count, :expected_full_count)",
            grid_coverage,
        )
        cursor = connection.execute(
            "SELECT gravity_ms2, gravity_label, model_count, expected_full_count FROM grid_coverage ORDER BY gravity_ms2"
        )
        column_names = [item[0] for item in cursor.description]
        grid_coverage = [dict(zip(column_names, row)) for row in cursor.fetchall()]

    datasets = {
        "headline": headline,
        "schema_comparison": schema_comparison,
        "grid_axes": grid_axes,
        "mapping": mapping,
        "quality_issues": quality_issues,
        "grid_coverage": grid_coverage,
        "variable_inventory": variables,
    }
    table_source_specs = {
        "schema_comparison": ("schema_comparison_sql", "Structural comparison query"),
        "grid_axes": ("grid_axes_sql", "Elf Owl grid-axis query"),
        "mapping": ("mapping_sql", "NetCDF import crosswalk query"),
        "quality_issues": ("quality_issues_sql", "Data-quality findings query"),
        "variable_inventory": ("variable_inventory_sql", "Variable inventory query"),
    }
    with sqlite3.connect(database_path) as connection:
        for dataset_id in table_source_specs:
            write_rows(connection, dataset_id, datasets[dataset_id])
    for dataset_id, (source_id, label) in table_source_specs.items():
        fields = list(datasets[dataset_id][0])
        query_text = f'SELECT {", ".join(fields)} FROM {dataset_id}'
        sources.append(
            {
                "id": source_id,
                "label": label,
                "path": "reports/elf_owl_netcdf_comparison_2026-07-15/analysis.sqlite",
                "query": {
                    "engine": "sqlite",
                    "language": "sql",
                    "sql": query_text,
                    "description": f"Returns the reviewed rows used by the {dataset_id} report table.",
                    "tables_used": [dataset_id],
                    "executed_at": GENERATED_AT,
                },
            }
        )

    _unused_cards = [
        {
            "id": "elf_file_count",
            "dataset": "headline",
            "sourceId": "grid_coverage_sql",
            "description": "Extracted 1300–1500 K models",
            "metrics": [{"label": "Elf Owl files", "field": "elf_files", "format": "number"}],
        },
        {
            "id": "elf_spectral_points",
            "dataset": "headline",
            "sourceId": "elf_sample",
            "description": "0.6–15 µm native wavelength samples",
            "metrics": [
                {"label": "Elf spectral points", "field": "elf_spectral_points", "format": "number"}
            ],
        },
        {
            "id": "aurora_spectral_points",
            "dataset": "headline",
            "sourceId": "aurora_sample",
            "description": "0.3–2.5 µm AURORA wavelength samples",
            "metrics": [
                {
                    "label": "AURORA spectral points",
                    "field": "aurora_spectral_points",
                    "format": "number",
                }
            ],
        },
        {
            "id": "shared_species",
            "dataset": "headline",
            "sourceId": "analysis_code",
            "description": "Exact species-name overlap after excluding structural fields",
            "metrics": [{"label": "Shared species", "field": "shared_species", "format": "number"}],
        },
    ]

    cards = []
    tables = [
        {
            "id": "schema_comparison_table",
            "title": "Structural comparison",
            "subtitle": "Representative files plus versioned AURORA schema; exact values shown for audit",
            "showDescription": True,
            "dataset": "schema_comparison",
            "sourceId": "schema_comparison_sql",
            "density": "spacious",
            "layout": "full",
            "defaultSort": {"field": "aspect", "direction": "asc"},
            "columns": [
                {"field": "aspect", "label": "Aspect"},
                {"field": "elf_owl", "label": "Elf Owl v2"},
                {"field": "aurora", "label": "Your AURORA setup"},
                {"field": "compatibility", "label": "Compatibility"},
            ],
        },
        {
            "id": "grid_axes_table",
            "title": "Elf Owl 1300–1500 K grid axes",
            "subtitle": "Parameter values parsed from all 3,603 filenames",
            "showDescription": True,
            "dataset": "grid_axes",
            "sourceId": "grid_axes_sql",
            "density": "spacious",
            "layout": "full",
            "defaultSort": {"field": "axis", "direction": "asc"},
            "columns": [
                {"field": "axis", "label": "Axis"},
                {"field": "field", "label": "Filename field"},
                {"field": "values", "label": "Available values"},
                {"field": "units", "label": "Interpretation"},
                {"field": "aurora_equivalent", "label": "AURORA equivalent"},
            ],
        },
        {
            "id": "mapping_table",
            "title": "Import crosswalk",
            "subtitle": "Required transformations for an AURORA-compatible view of Elf Owl data",
            "showDescription": True,
            "dataset": "mapping",
            "sourceId": "mapping_sql",
            "density": "spacious",
            "layout": "full",
            "defaultSort": {"field": "elf_source", "direction": "asc"},
            "columns": [
                {"field": "elf_source", "label": "Elf Owl source"},
                {"field": "aurora_target", "label": "AURORA target"},
                {"field": "transform", "label": "Transformation"},
                {"field": "status", "label": "Status/caveat"},
            ],
        },
        {
            "id": "quality_table",
            "title": "Data-quality and compatibility findings",
            "subtitle": "Priority 1 requires correction before chemistry analysis or schema conversion",
            "showDescription": True,
            "dataset": "quality_issues",
            "sourceId": "quality_issues_sql",
            "density": "spacious",
            "layout": "full",
            "defaultSort": {"field": "priority", "direction": "asc"},
            "columns": [
                {"field": "priority", "label": "Priority", "format": "number"},
                {"field": "system", "label": "System"},
                {"field": "issue", "label": "Finding"},
                {"field": "evidence", "label": "Evidence"},
                {"field": "action", "label": "Recommended action"},
            ],
        },
        {
            "id": "variable_table",
            "title": "Variable-level inventory",
            "subtitle": "Representative Elf Owl and AURORA files; use filters/search for exact fields",
            "showDescription": True,
            "dataset": "variable_inventory",
            "sourceId": "variable_inventory_sql",
            "density": "dense",
            "layout": "full",
            "defaultSort": {"field": "name", "direction": "asc"},
            "columns": [
                {"field": "family", "label": "Family"},
                {"field": "name", "label": "Variable"},
                {"field": "role", "label": "Role"},
                {"field": "dimensions", "label": "Dimensions"},
                {"field": "dtype", "label": "Type"},
                {"field": "units", "label": "Declared units"},
                {"field": "compressed", "label": "Compressed"},
            ],
        },
    ]

    charts = [
        {
            "id": "grid_coverage_chart",
            "title": "Available models by gravity",
            "subtitle": "All three temperatures combined; a full gravity slice contains 360 models",
            "showDescription": True,
            "intent": "comparison",
            "question": "Where is the extracted parameter grid incomplete?",
            "rationale": "A horizontal bar chart makes the single low-gravity exception visible across 11 ordered gravity values.",
            "comparisonContext": {
                "baseline": "360 models for a complete gravity slice",
                "grain": "gravity value",
                "unit": "models",
            },
            "type": "horizontalBar",
            "dataset": "grid_coverage",
            "sourceId": "grid_coverage_sql",
            "encodings": {
                "x": {"field": "gravity_label", "type": "ordinal", "label": "Gravity"},
                "y": {"field": "model_count", "type": "quantitative", "label": "Models"},
                "tooltip": [
                    {"field": "gravity_ms2", "type": "quantitative", "label": "Gravity", "unit": "m s⁻²"},
                    {"field": "model_count", "type": "quantitative", "label": "Available models"},
                    {"field": "expected_full_count", "type": "quantitative", "label": "Full slice"},
                ],
            },
            "xAxisTitle": "Gravity",
            "yAxisTitle": "Available models",
            "valueFormat": "number",
            "unit": "models",
            "layout": "full",
            "maxRows": 20,
            "referenceLines": [
                {"axis": "y", "value": 360, "label": "Complete slice", "color": "neutral", "lineStyle": "dashed"}
            ],
            "surface": {"surface": "card", "viewMode": "both"},
        }
    ]

    blocks = [
        {"id": "title", "type": "markdown", "body": "# Elf Owl NetCDF Structure and AURORA Compatibility"},
        {
            "id": "technical_summary",
            "type": "markdown",
            "body": (
                "## Technical summary\n\n"
                "**Elf Owl can be imported into your tooling, but it cannot be treated as a native AURORA run file.** "
                "The shared physical core is pressure, temperature, chemistry and thermal flux; the array layout, wavelength grid, units, parameter semantics and run metadata differ. A dedicated adapter is safer than modifying either source format.\n\n"
                "**The most urgent finding is in your current AURORA outputs:** `mole_fraction` includes a spurious species named `index` with values hundreds of times larger than a valid mixing fraction. It appeared in all 60 deterministically sampled weekend-grid files. Remove that column during schema construction and regenerate or repair affected files before chemistry analysis.\n\n"
                "**Elf Owl also has a metadata defect:** all chemistry fields declare `units='Kelvin'`, although their sums show they are volume mixing fractions. Override these units only in the adapter and preserve the downloaded originals."
            ),
        },
        {
            "id": "structural_finding",
            "type": "markdown",
            "body": (
                "## The two formats share science variables, not a common schema\n\n"
                "Elf Owl is optimized for compact distribution of one atmosphere per file: two coordinates and separate one-dimensional chemistry arrays. AURORA is optimized for reproducible grid operations: explicit level/layer/species axes, multiple spectral products, cloud optical properties, run scalars, QC diagnostics and provenance. The table below is the decisive compatibility view."
            ),
        },
        {"id": "structural_table_block", "type": "table", "tableId": "schema_comparison_table"},
        {
            "id": "grid_finding",
            "type": "markdown",
            "body": (
                "## The extracted grid is regular above 10 m s⁻², with one low-gravity exception\n\n"
                "The archive contains 1,201 models at each of 1300, 1400 and 1500 K. Every combination is present for gravity ≥17 m s⁻². At 10 m s⁻², only one special combination per temperature is included (`logKzz=8`, `[M/H]=+1`, `C/O=1× solar`). Code should index actual filenames instead of assuming the naive 3,960-row Cartesian product."
            ),
        },
        {"id": "grid_coverage_chart_block", "type": "chart", "chartId": "grid_coverage_chart"},
        {"id": "grid_table_block", "type": "table", "tableId": "grid_axes_table"},
        {
            "id": "crosswalk_finding",
            "type": "markdown",
            "body": (
                "## A loss-aware adapter can expose the shared subset\n\n"
                "The safe conversion path reverses and optionally resamples wavelength, converts per-centimeter flux to per-micron flux, interpolates the vertical profile, stacks chemistry variables, and translates logarithmic parameters. It must explicitly mark stellar, orbital, reflected-light and cloud products as unavailable; inventing placeholders would make an imported atmosphere look like a completed AURORA simulation."
            ),
        },
        {"id": "mapping_table_block", "type": "table", "tableId": "mapping_table"},
        {
            "id": "quality_finding",
            "type": "markdown",
            "body": (
                "## Two metadata/data defects matter more than the layout differences\n\n"
                "The AURORA `index` pseudo-species corrupts any total-abundance calculation, while the Elf Owl chemistry unit labels can mislead generic readers. Both should be corrected at ingestion or generation boundaries and covered by automated validation. The flux-normalization question is separate: the algebraic unit conversion is known, but amplitude comparison is not trustworthy until the physical reference surface is confirmed."
            ),
        },
        {"id": "quality_table_block", "type": "table", "tableId": "quality_table"},
        {
            "id": "inventory_finding",
            "type": "markdown",
            "body": (
                "## The variable inventory shows where each format carries extra meaning\n\n"
                "Use this table as the field-level reference. Elf Owl chemistry appears as individual variables on `pressure`; AURORA chemistry is a matrix on `(level, species)`. AURORA's additional scalar and QC variables are operational metadata, not quantities that can be inferred from Elf Owl."
            ),
        },
        {"id": "inventory_table_block", "type": "table", "tableId": "variable_table"},
        {
            "id": "scope_methods",
            "type": "markdown",
            "body": (
                "## Scope and method\n\n"
                "The analysis parsed all 3,603 Elf Owl filenames and inspected a representative file's dimensions, coordinates, variables, attributes, encodings, wavelength sampling and chemistry sums. It compared that result with `outputs/weekend_nc/run_0000000.nc` and the versioned AURORA schema implementation. Structural consistency was checked on 60 evenly spaced files from each corpus; each sample had one schema signature and no open failures. The patchy-cloud product was inspected as a secondary variant but is not the primary baseline."
            ),
        },
        {
            "id": "limitations",
            "type": "markdown",
            "body": (
                "## Limitations and robustness\n\n"
                "This is a structural and metadata comparison, not a validation that the two model families predict the same atmosphere. The representative-file value checks establish units/layout issues but do not compare spectra at matched physical parameters. Only 60 files per corpus were opened for schema-signature consistency, while the complete Elf filename grid was indexed. The archive's native wavelength spacing was measured directly; it should not be confused with the effective opacity or instrument resolution."
            ),
        },
        {
            "id": "next_steps",
            "type": "markdown",
            "body": (
                "## Recommended next steps\n\n"
                "1. Fix `_IGNORED_PROFILE_COLUMNS` to exclude `index`, add mole-fraction range and sum checks, and repair/regenerate the weekend-grid files.\n"
                "2. Implement a read-only `open_elf_owl()` adapter that returns a normalized intermediate dataset without rewriting the source files.\n"
                "3. Keep an explicit `source_model_family='sonora_elf_owl_v2'` marker and use nullable/unavailable fields for AURORA-only products.\n"
                "4. Confirm thermal-flux normalization with a matched PICASO calculation before amplitude comparisons.\n"
                "5. Add adapter tests for wavelength reversal, the 5 µm stitch, unit conversion, chemistry sums, parameter transforms and missing-field behavior."
            ),
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": (
                "## Further questions\n\n"
                "The next design choice is whether Elf Owl should remain an external comparison dataset or be converted into an AURORA-shaped interchange file. The external-adapter approach preserves scientific distinctions and is the recommended default. A full conversion is appropriate only if downstream software cannot consume a normalized in-memory view."
            ),
        },
    ]

    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Elf Owl NetCDF Structure and AURORA Compatibility",
            "description": "Technical comparison of Sonora Elf Owl v2 files with the AURORA sub-Neptune NetCDF schema.",
            "generatedAt": GENERATED_AT,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": GENERATED_AT,
            "status": "ready",
            "datasets": datasets,
        },
        "sources": sources,
    }
    (REPORT_DIR / "artifact.json").write_text(json.dumps(artifact, indent=2) + "\n")
    (REPORT_DIR / "REPORT_NOTES.md").write_text(
        "# Report notes\n\n"
        "- Audience: technical.\n"
        "- Delivery mode: portable HTML because an MCP artifact renderer was unavailable.\n"
        "- Required technical-report roles map to visible blocks: technical summary; structural/grid/data-quality findings; scope and method; limitations; recommended next steps; further questions.\n"
        "- Visual omission for schema-size comparisons: counts use heterogeneous units, so native tables are more honest than mixing wavelength points, levels, variables, files, and attributes on one scale.\n"
        "- Chart map: `grid_coverage_chart` asks where the grid is incomplete; horizontal bar; gravity label × model count with a 360-model completeness reference; 11 rows; single-root palette with a neutral benchmark; delivered inside the portable HTML report.\n"
        "- Structural consistency uses 60 evenly spaced files from each corpus; full-corpus filename indexing is used for the Elf Owl parameter grid.\n",
    )
    print(REPORT_DIR / "artifact.json")


if __name__ == "__main__":
    main()
