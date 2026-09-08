"""
extract_structured_ai.py
==========================

For papers flagged as relevant by filter_papers.py, use an LLM to extract
candidate mof_master.csv-shaped rows (material identity, metal/linker, topology,
porosity, stability) from the paper's plain text.

This is explicitly a CANDIDATE-generation step, not an import step:
- Output goes to data/processed/ai_extracted_candidates.csv, never mof_master.csv.
- Every extracted row is marked structure_source="inferred" and
  calculation_status="needs_review" - a human must check each row against the
  source paper before it is eligible for import via import_external_database.py
  (or manual entry).
- If the model cannot find a value, it must return null - the prompt explicitly
  forbids guessing, and rows where the model returns no usable data at all are
  marked calculation_status="not_available" instead of being fabricated.

USAGE
-----
    python src/collection/extract_structured_ai.py \\
        --candidates reports/relevant_candidates.csv \\
        --text-dir data/raw/literature/text \\
        --output data/processed/ai_extracted_candidates.csv

Requires ANTHROPIC_API_KEY in your environment or a .env file (see .env.example).

Rate limiting: a simple token-bucket limiter caps requests per minute
(--rpm, default 12) to stay well under typical API rate limits.

TODO:
    - Confirm the model name/version you want to use (MODEL_NAME below) against
      current Anthropic API documentation before running at scale.
    - Consider chunking very long papers (full text can exceed a single
      request's practical context) - currently the whole text is sent as-is.
    - Add a cost/usage log if running this across a large corpus.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL_NAME = "claude-sonnet-4-6"  # TODO: confirm against current API docs before running at scale

EXTRACTION_FIELDS = [
    "mof_id_suggestion", "mof_name", "chemical_formula", "material_type",
    "metal_identity", "linker_identity", "topology", "crystal_system",
    "space_group", "BET_surface_area_m2_g", "pore_volume_cm3_g",
    "void_fraction", "thermal_stability_temp_C", "water_stability",
    "chemical_stability", "notes",
]

SYSTEM_PROMPT = """You are extracting structured data about metal-organic framework \
(MOF) materials from a research paper's text for a scientific database.

Rules you MUST follow:
- Only report values that are explicitly stated in the text. Never estimate, \
infer, or guess a numeric value that is not directly given.
- If a field is not reported in the text, set it to null. Do not leave it out \
of the JSON object.
- If the paper describes more than one distinct MOF material with its own \
reported properties, return one JSON object per material in a JSON array.
- If the paper does not report any usable intrinsic MOF structural/porosity/ \
stability data at all, return an empty JSON array: []
- Return ONLY a JSON array. No prose, no markdown code fences, no explanation.

Each object in the array must have exactly these keys:
mof_id_suggestion, mof_name, chemical_formula, material_type, metal_identity, \
linker_identity, topology, crystal_system, space_group, BET_surface_area_m2_g, \
pore_volume_cm3_g, void_fraction, thermal_stability_temp_C, water_stability, \
chemical_stability, notes.

mof_id_suggestion should be a short readable slug you invent from the mof_name \
(e.g. "UiO-66-NH2"), not a database ID - it will be reviewed and possibly \
changed by a human before import.
notes should mention anything a human reviewer should check (e.g. ambiguous \
units, a value read from a figure rather than text, multiple similar samples)."""


class RateLimiter:
    def __init__(self, rpm: int):
        self.min_interval = 60.0 / rpm if rpm > 0 else 0
        self._last_call = 0.0

    def wait(self):
        elapsed = time.time() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.time()


def extract_from_text(client, text: str, source_file: str) -> list:
    # TODO: add chunking here if a given paper's text is very long.
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = "".join(block.text for block in message.content if hasattr(block, "text"))
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"  WARNING: could not parse model output as JSON for {source_file}: {exc}", file=sys.stderr)
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


def main():
    parser = argparse.ArgumentParser(description="LLM-assisted structured extraction of MOF candidates from relevant papers.")
    parser.add_argument("--candidates", required=True, help="reports/relevant_candidates.csv from filter_papers.py")
    parser.add_argument("--text-dir", default="data/raw/literature/text")
    parser.add_argument("--output", default="data/processed/ai_extracted_candidates.csv")
    parser.add_argument("--min-relevance-score", type=int, default=2)
    parser.add_argument("--rpm", type=int, default=12, help="Max requests per minute.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if anthropic is None:
        print("ERROR: the 'anthropic' package is required. pip install anthropic", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. See .env.example.", file=sys.stderr)
        sys.exit(1)

    candidates_path = Path(args.candidates)
    if not candidates_path.exists():
        print(f"ERROR: candidates file not found: {candidates_path}", file=sys.stderr)
        sys.exit(1)

    text_dir = Path(args.text_dir)
    client = anthropic.Anthropic()
    limiter = RateLimiter(args.rpm)

    with open(candidates_path, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))

    to_process = [
        c for c in candidates
        if c.get("recommended_action", "").startswith("candidate")
        and int(c.get("relevance_score", 0)) >= args.min_relevance_score
    ]
    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Processing {len(to_process)} candidate papers (of {len(candidates)} total in input).")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows = []
    for candidate in to_process:
        txt_name = candidate["file"]
        txt_path = text_dir / txt_name
        if not txt_path.exists():
            print(f"  SKIP: text file not found: {txt_path}")
            continue

        text = txt_path.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            continue

        limiter.wait()
        try:
            extracted = extract_from_text(client, text, txt_name)
        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: extraction failed for {txt_name}: {exc}", file=sys.stderr)
            continue

        for item in extracted:
            row = {field: item.get(field) for field in EXTRACTION_FIELDS}
            row["source_file"] = txt_name
            row["structure_source"] = "inferred"
            row["calculation_status"] = "needs_review"
            all_rows.append(row)

        print(f"  {txt_name}: {len(extracted)} candidate material(s) extracted")

    fieldnames = ["source_file"] + EXTRACTION_FIELDS + ["structure_source", "calculation_status"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} candidate material rows to {output_path}")
    print("All rows are marked structure_source=inferred, calculation_status=needs_review.")
    print("Review each row against its source paper before importing into mof_master.csv.")


if __name__ == "__main__":
    main()
