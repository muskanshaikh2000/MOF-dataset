"""
download_papers.py
====================

Download OPEN-ACCESS PDFs only, for candidate papers listed by search_literature.py.
Never attempts to bypass a paywall. Tries, in order:

    1. The oa_url already recorded by search_literature.py (from OpenAlex).
    2. Unpaywall (requires an email in .env - see .env.example).
    3. Europe PMC (for biomedical-adjacent venues).

Filenames are DOI-derived and stable (slashes replaced with underscores) so the
script is safe to re-run - already-downloaded files are skipped, not re-fetched.

USAGE
-----
    python src/collection/download_papers.py \\
        --input reports/literature_search_results.csv \\
        --output-dir data/raw/literature/pdfs

Produces:
    data/raw/literature/pdfs/<doi>.pdf   (one per successfully downloaded paper)
    reports/download_log.csv             (status per attempted paper: success/no_oa_source/failed)

TODO:
    - Add a Springer Open Access API fallback if you have access to it (it
      returns JATS XML rather than PDF, which extract_text.py does not yet
      parse - would need its own text-extraction branch).
    - Consider a retry-with-backoff policy for transient network failures
      instead of the current single-attempt-per-source behavior.
"""

import argparse
import csv
import os
import re
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

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def safe_filename(doi: str) -> str:
    doi = doi.replace("https://doi.org/", "").strip()
    return re.sub(r"[^A-Za-z0-9._-]", "_", doi) + ".pdf"


def try_download(url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "MOF-dataset-collector/1.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not resp.content[:4] == b"%PDF":
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


def unpaywall_oa_url(doi: str, email: str) -> str | None:
    try:
        resp = requests.get(UNPAYWALL_URL.format(doi=doi), params={"email": email}, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
    except Exception:
        return None


def europe_pmc_oa_url(doi: str) -> str | None:
    try:
        resp = requests.get(EUROPE_PMC_SEARCH_URL, params={
            "query": f"DOI:{doi}", "format": "json",
        }, timeout=30)
        if resp.status_code != 200:
            return None
        results = (resp.json().get("resultList") or {}).get("result") or []
        for r in results:
            if r.get("isOpenAccess") == "Y" and r.get("pmcid"):
                pmcid = r["pmcid"]
                return f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF"
        return None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Download open-access PDFs for candidate papers.")
    parser.add_argument("--input", required=True, help="CSV from search_literature.py (needs doi, oa_url columns).")
    parser.add_argument("--output-dir", default="data/raw/literature/pdfs")
    parser.add_argument("--log", default="reports/download_log.csv")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on number of papers to attempt.")
    args = parser.parse_args()

    if requests is None:
        print("ERROR: the 'requests' package is required. pip install requests", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    unpaywall_email = os.environ.get("UNPAYWALL_EMAIL")

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    if args.limit:
        reader = reader[: args.limit]

    log_rows = []
    n_success = n_skipped = n_no_source = n_failed = 0

    for row in reader:
        doi = (row.get("doi") or "").strip()
        if not doi:
            log_rows.append({"doi": "", "status": "no_doi", "source": ""})
            n_failed += 1
            continue

        dest = output_dir / safe_filename(doi)
        if dest.exists():
            log_rows.append({"doi": doi, "status": "already_downloaded", "source": ""})
            n_skipped += 1
            continue

        candidates = []
        oa_url = (row.get("oa_url") or "").strip()
        if oa_url:
            candidates.append(("openalex_oa_url", oa_url))
        if unpaywall_email:
            u = unpaywall_oa_url(doi, unpaywall_email)
            if u:
                candidates.append(("unpaywall", u))
        epmc = europe_pmc_oa_url(doi)
        if epmc:
            candidates.append(("europe_pmc", epmc))

        if not candidates:
            log_rows.append({"doi": doi, "status": "no_oa_source", "source": ""})
            n_no_source += 1
            continue

        downloaded = False
        for source_name, url in candidates:
            if try_download(url, dest):
                log_rows.append({"doi": doi, "status": "success", "source": source_name})
                n_success += 1
                downloaded = True
                break
            time.sleep(0.3)

        if not downloaded:
            log_rows.append({"doi": doi, "status": "failed", "source": ""})
            n_failed += 1

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["doi", "status", "source"])
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"Downloaded: {n_success}, already had: {n_skipped}, "
          f"no OA source: {n_no_source}, failed: {n_failed}")
    print(f"Log written to: {log_path}")
    if not unpaywall_email:
        print("NOTE: UNPAYWALL_EMAIL not set - Unpaywall fallback was skipped. See .env.example.")


if __name__ == "__main__":
    main()
