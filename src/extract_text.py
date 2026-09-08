"""
extract_text.py
=================

Extract plain text from downloaded PDFs (data/raw/literature/pdfs/) into
data/raw/literature/text/, one .txt file per .pdf, using pdfplumber.

Skips PDFs that already have a corresponding .txt file, so it's safe to re-run
after downloading more papers.

USAGE
-----
    python src/collection/extract_text.py \\
        --input-dir data/raw/literature/pdfs \\
        --output-dir data/raw/literature/text

Produces:
    data/raw/literature/text/<same_stem>.txt
    reports/text_extraction_log.csv   - status per file (success/empty/failed)

TODO:
    - Scanned/image-only PDFs will extract as empty or near-empty text; add an
      OCR fallback (e.g. pytesseract) if you encounter these in practice.
"""

import argparse
import csv
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


def extract_pdf_text(pdf_path: Path) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n\n".join(text_parts)


def main():
    parser = argparse.ArgumentParser(description="Extract text from downloaded PDFs.")
    parser.add_argument("--input-dir", default="data/raw/literature/pdfs")
    parser.add_argument("--output-dir", default="data/raw/literature/text")
    parser.add_argument("--log", default="reports/text_extraction_log.csv")
    args = parser.parse_args()

    if pdfplumber is None:
        print("ERROR: the 'pdfplumber' package is required. pip install pdfplumber", file=sys.stderr)
        sys.exit(1)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    log_rows = []
    n_success = n_skipped = n_empty = n_failed = 0

    for pdf_path in sorted(input_dir.glob("*.pdf")):
        txt_path = output_dir / (pdf_path.stem + ".txt")
        if txt_path.exists():
            log_rows.append({"file": pdf_path.name, "status": "already_extracted"})
            n_skipped += 1
            continue
        try:
            text = extract_pdf_text(pdf_path)
        except Exception as exc:  # noqa: BLE001
            log_rows.append({"file": pdf_path.name, "status": f"failed: {exc}"})
            n_failed += 1
            continue

        if not text.strip():
            log_rows.append({"file": pdf_path.name, "status": "empty_text_possible_scanned_pdf"})
            n_empty += 1
            # Still write the (empty) file so re-runs don't retry it indefinitely;
            # remove it manually if you add OCR later and want to reprocess.
            txt_path.write_text(text, encoding="utf-8")
            continue

        txt_path.write_text(text, encoding="utf-8")
        log_rows.append({"file": pdf_path.name, "status": "success"})
        n_success += 1

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "status"])
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"Extracted: {n_success}, already done: {n_skipped}, "
          f"empty/possible scanned: {n_empty}, failed: {n_failed}")
    print(f"Log written to: {log_path}")


if __name__ == "__main__":
    main()
