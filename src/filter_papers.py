"""
filter_papers.py
==================

Score extracted paper text for relevance to the INTRINSIC MOF descriptor database
(this repository) - i.e. does the paper actually report structural, porosity,
crystallographic, or stability data for a specific named MOF, as opposed to being
a review article, an unrelated topic, or (deliberately out of scope here) a
radiation-response study.

This is a keyword/pattern-based heuristic filter, not a guarantee of relevance -
its output (reports/relevant_candidates.csv) is a shortlist for either manual
review or extract_structured_ai.py, not a final answer.

USAGE
-----
    python src/collection/filter_papers.py \\
        --input-dir data/raw/literature/text \\
        --output reports/relevant_candidates.csv

Produces:
    reports/relevant_candidates.csv   - file, strong_hits, weak_hits, is_review,
                                         relevance_score, recommended_action

TODO:
    - Tune STRUCTURAL_KEYWORDS / REVIEW_KEYWORDS / EXCLUDE_KEYWORDS against a
      batch of real results - this starting list is a reasonable first pass,
      not a validated classifier.
    - Consider excluding papers that score high on radiation vocabulary if the
      intent is to keep this corpus fully separate from MOF_Radiation_AI's own
      literature corpus (EXCLUDE_KEYWORDS below is a starting point for that).
"""

import argparse
import csv
import re
from pathlib import Path

# Strong signal: specific, quantitative intrinsic-property terms.
STRUCTURAL_KEYWORDS = [
    r"\bBET surface area\b", r"\bpore volume\b", r"\bpore size distribution\b",
    r"\bPXRD\b", r"\bpowder x-?ray diffraction\b", r"\bsingle[- ]crystal\b",
    r"\bspace group\b", r"\bunit cell\b", r"\blattice parameter", r"\btopology\b",
    r"\bcrystal structure\b", r"\bthermogravimetric\b", r"\bTGA\b",
    r"\bvoid fraction\b", r"\bLangmuir surface area\b",
]

# Weaker/general signal: MOF-adjacent vocabulary that alone doesn't confirm relevance.
WEAK_KEYWORDS = [
    r"\bmetal-organic framework\b", r"\bMOF\b", r"\bcovalent organic framework\b",
    r"\bCOF\b", r"\blinker\b", r"\bnode\b", r"\bporous coordination polymer\b",
]

REVIEW_KEYWORDS = [
    r"\bin this review\b", r"\bthis review (summarizes|discusses|covers)\b",
    r"\bcomprehensive review\b",
]

# Vocabulary belonging to the separate MOF_Radiation_AI project's corpus -
# flagged here so it can optionally be excluded to keep the two corpora distinct.
RADIATION_EXCLUDE_KEYWORDS = [
    r"\bgamma ray", r"\bgamma-ray", r"\bgamma irradiation\b", r"\bCo-60\b",
    r"\bradiation stability\b", r"\bradiolysis\b", r"\bdose rate\b",
    r"\bfluence\b", r"\bkGy\b", r"\bMGy\b",
]


def count_matches(text: str, patterns: list) -> int:
    return sum(len(re.findall(p, text, flags=re.IGNORECASE)) for p in patterns)


def score_file(text: str) -> dict:
    strong_hits = count_matches(text, STRUCTURAL_KEYWORDS)
    weak_hits = count_matches(text, WEAK_KEYWORDS)
    review_hits = count_matches(text, REVIEW_KEYWORDS)
    radiation_hits = count_matches(text, RADIATION_EXCLUDE_KEYWORDS)

    is_review = review_hits > 0
    relevance_score = strong_hits * 2 + min(weak_hits, 10)

    if weak_hits == 0:
        recommended_action = "exclude_not_mof"
    elif is_review:
        recommended_action = "exclude_review"
    elif relevance_score >= 6:
        recommended_action = "candidate_high_priority"
    elif relevance_score >= 2:
        recommended_action = "candidate_low_priority"
    else:
        recommended_action = "exclude_low_signal"

    return {
        "strong_hits": strong_hits,
        "weak_hits": weak_hits,
        "review_hits": review_hits,
        "radiation_hits": radiation_hits,
        "is_review": is_review,
        "relevance_score": relevance_score,
        "recommended_action": recommended_action,
    }


def main():
    parser = argparse.ArgumentParser(description="Score extracted paper text for MOF intrinsic-data relevance.")
    parser.add_argument("--input-dir", default="data/raw/literature/text")
    parser.add_argument("--output", default="reports/relevant_candidates.csv")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"ERROR: input directory not found: {input_dir}")
        return

    rows = []
    for txt_path in sorted(input_dir.glob("*.txt")):
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
        result = score_file(text)
        result["file"] = txt_path.name
        rows.append(result)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["file", "strong_hits", "weak_hits", "review_hits", "radiation_hits",
                  "is_review", "relevance_score", "recommended_action"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})

    from collections import Counter
    action_counts = Counter(r["recommended_action"] for r in rows)
    print(f"Scored {len(rows)} files. Wrote {output_path}")
    print("Breakdown by recommended_action:")
    for action, count in action_counts.items():
        print(f"  {action}: {count}")


if __name__ == "__main__":
    main()
