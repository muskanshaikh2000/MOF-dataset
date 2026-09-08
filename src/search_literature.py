"""
search_literature.py
=====================

Search OpenAlex for candidate papers likely to report INTRINSIC MOF material data
(structure, porosity, BET surface area, crystallography, topology, stability) -
deliberately NOT radiation-response papers, which belong to the separate
MOF_Radiation_AI project's own search script.

Cursor-paginated and checkpointed so a long search can be interrupted and resumed
without re-querying pages you've already fetched or re-adding papers you already have.

USAGE
-----
    python src/collection/search_literature.py --output reports/literature_search_results.csv

    # Resume an interrupted run (uses the same checkpoint file automatically):
    python src/collection/search_literature.py --output reports/literature_search_results.csv --resume

    # Use your own search terms instead of the defaults:
    python src/collection/search_literature.py --terms "MOF BET surface area,MOF crystallographic structure" --output reports/literature_search_results.csv

CONFIGURATION
-------------
Set OPENALEX_EMAIL in a .env file (or the environment) to use OpenAlex's polite
pool (faster, more reliable rate limits). See .env.example.

TODO:
    - Tune DEFAULT_SEARCH_TERMS based on which terms actually surface relevant,
      non-radiation MOF structural-data papers versus noise, once run against
      real OpenAlex results.
    - Consider adding a date-range or venue filter if the term list alone
      returns too broad a set of candidates.
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OPENALEX_WORKS_URL = "https://api.openalex.org/works"

# Deliberately intrinsic-property focused, not radiation-focused.
DEFAULT_SEARCH_TERMS = [
    "metal-organic framework BET surface area",
    "metal-organic framework pore volume porosity",
    "metal-organic framework crystal structure PXRD",
    "metal-organic framework topology synthesis characterization",
    "MOF single crystal X-ray structure",
    "MOF thermal stability TGA",
    "MOF composite structural characterization",
    "covalent organic framework porosity structure",
]

RESULTS_FIELDS = [
    "id", "doi", "title", "publication_year", "primary_location",
    "open_access", "authorships", "cited_by_count",
]


def load_checkpoint(checkpoint_path: Path) -> set:
    if not checkpoint_path.exists():
        return set()
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def append_checkpoint(checkpoint_path: Path, work_id: str) -> None:
    with open(checkpoint_path, "a", encoding="utf-8") as f:
        f.write(work_id + "\n")


def extract_row(work: dict, term: str) -> dict:
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    oa = work.get("open_access") or {}
    authorships = work.get("authorships") or []
    authors = "; ".join(
        (a.get("author") or {}).get("display_name", "") for a in authorships
    )
    return {
        "openalex_id": work.get("id"),
        "doi": work.get("doi"),
        "title": work.get("title"),
        "year": work.get("publication_year"),
        "journal": source.get("display_name"),
        "is_oa": oa.get("is_oa"),
        "oa_url": oa.get("oa_url"),
        "cited_by_count": work.get("cited_by_count"),
        "authors": authors,
        "matched_search_term": term,
    }


def search_term(term: str, seen_ids: set, per_page: int = 100, max_pages: int = 5,
                 email: str | None = None):
    if requests is None:
        raise RuntimeError("The 'requests' package is required. pip install requests")

    cursor = "*"
    pages_fetched = 0
    while cursor and pages_fetched < max_pages:
        params = {
            "search": term,
            "per_page": per_page,
            "cursor": cursor,
        }
        if email:
            params["mailto"] = email
        resp = requests.get(OPENALEX_WORKS_URL, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        for work in payload.get("results", []):
            work_id = work.get("id")
            if not work_id or work_id in seen_ids:
                continue
            seen_ids.add(work_id)
            yield work_id, extract_row(work, term)

        cursor = (payload.get("meta") or {}).get("next_cursor")
        pages_fetched += 1
        time.sleep(0.2)  # be polite even within the polite pool


def main():
    parser = argparse.ArgumentParser(description="Search OpenAlex for candidate MOF intrinsic-data papers.")
    parser.add_argument("--output", default="reports/literature_search_results.csv")
    parser.add_argument("--checkpoint", default="reports/.literature_search_checkpoint.txt")
    parser.add_argument("--terms", default=None,
                         help="Comma-separated custom search terms (overrides DEFAULT_SEARCH_TERMS).")
    parser.add_argument("--max-pages-per-term", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--resume", action="store_true",
                         help="Append to --output and skip work_ids already in --checkpoint.")
    args = parser.parse_args()

    terms = [t.strip() for t in args.terms.split(",")] if args.terms else DEFAULT_SEARCH_TERMS
    email = os.environ.get("OPENALEX_EMAIL")

    output_path = Path(args.output)
    checkpoint_path = Path(args.checkpoint)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen_ids = load_checkpoint(checkpoint_path) if args.resume else set()
    write_header = not (args.resume and output_path.exists())

    mode = "a" if args.resume and output_path.exists() else "w"
    total_new = 0
    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "openalex_id", "doi", "title", "year", "journal", "is_oa", "oa_url",
            "cited_by_count", "authors", "matched_search_term",
        ])
        if write_header:
            writer.writeheader()

        for term in terms:
            print(f"Searching: {term!r}")
            try:
                for work_id, row in search_term(
                    term, seen_ids, per_page=args.per_page,
                    max_pages=args.max_pages_per_term, email=email,
                ):
                    writer.writerow(row)
                    append_checkpoint(checkpoint_path, work_id)
                    total_new += 1
            except Exception as exc:  # noqa: BLE001 - report and continue with next term
                print(f"  WARNING: search failed for term {term!r}: {exc}", file=sys.stderr)

    print(f"\nWrote {total_new} new candidate rows to {output_path}")
    print(f"Checkpoint file: {checkpoint_path} ({len(seen_ids)} total OpenAlex IDs seen)")


if __name__ == "__main__":
    main()
