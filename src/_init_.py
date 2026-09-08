"""
src/collection/
================

Scripts for building the literature-derived slice of data/raw/literature/ and for
fetching public MOF database exports. These are the "search / download / filter"
scripts, kept separate from the core import-clean-validate pipeline in src/ because
they talk to the network and to external APIs, and because their output always
lands in data/raw/ (untouched, unmodified) or as *candidate* rows requiring human
review - never directly into data/processed/mof_master.csv.

Pipeline (literature route):

    search_literature.py       -> reports/literature_search_results.csv
        (query OpenAlex for candidate papers, resumable/checkpointed)
            |
            v
    download_papers.py         -> data/raw/literature/pdfs/*.pdf
        (fetch open-access PDFs only; never bypasses paywalls)
            |
            v
    extract_text.py            -> data/raw/literature/text/*.txt
        (PDF -> plain text, one .txt per .pdf)
            |
            v
    filter_papers.py           -> reports/relevant_candidates.csv
        (keyword/pattern relevance scoring: does this paper report intrinsic
        MOF structural/porosity/crystallographic data at all?)
            |
            v
    extract_structured_ai.py   -> data/processed/ai_extracted_candidates.csv
        (LLM-assisted structured extraction of candidate mof_master.csv-shaped
        rows from relevant papers - output is marked structure_source=inferred
        and calculation_status=needs_review; nothing here is auto-merged into
        mof_master.csv)

Pipeline (public database route):

    download_database_exports.py -> data/raw/mof_databases/<source>/
        (fetch a named public MOF database export from a URL you supply and verify
        yourself; nothing is downloaded from a hardcoded/guessed URL)

Neither route auto-populates data/processed/mof_master.csv. A human decides what
to import from data/raw/ using src/import_csd.py or src/import_external_database.py,
and what to accept from data/processed/ai_extracted_candidates.csv.
"""
