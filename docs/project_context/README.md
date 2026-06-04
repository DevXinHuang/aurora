# Project Context

Use this folder for source material that explains Aurora's research goals, scientific background, and HPC requirements.

## Folders

- `proposal/` - grant proposal PDFs and searchable text extracts.
- `papers/` - related papers, preprints, supporting PDFs, and citation metadata.
- `notes/` - working notes, questions, summaries, and decisions.

## How to Add More Material

For related papers, drop the PDF into `papers/` and use a descriptive filename:

```text
FirstAuthor_Year_short-title.pdf
```

Helpful extras, when available:

- DOI or arXiv URL
- BibTeX citation
- A one-sentence note about why the paper matters
- Whether the source is background, method, validation, or requirement

After adding files, tell Codex something like:

```text
I added three papers in docs/project_context/papers. Please index them and summarize what matters for Aurora.
```

## Current Source Of Truth

The proposal in `proposal/Daniel_Huang_AABC_Grant_Proposal_final.pdf` is the current project proposal. The `.txt` file next to it is generated from the PDF for search and reference; treat the PDF as authoritative if they ever disagree.
