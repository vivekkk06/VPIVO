#!/usr/bin/env python3
"""Day 6 · Module 2 — freeze, then reveal, the Dataset-B surrogate visual review.

    VISION-MODEL SURROGATE REVIEW — NOT GROUND TRUTH.

Two steps, deliberately separate, run in this order:

  freeze   Validates the judgments against the BLIND manifest and records their SHA-256.
           It never reads the answer key. After this, the judgments are fixed.

  reveal   Refuses to run unless the judgments still match the frozen hash. Only then
           does it read which points were Module-1 predicted boundaries, and writes a
           descriptive comparison. Nothing it writes is a segmentation metric.

Usage:
    python scripts/finalize_module2_visual_review.py freeze
    python scripts/finalize_module2_visual_review.py reveal
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.module2.visual_review import (  # noqa: E402
    SURROGATE_LABEL, ProtocolViolation, assert_blind, sha256_file, summarize,
    validate_judgments, verify_frozen,
)

M2 = ROOT / "reports" / "day6" / "module2"
MANIFEST = M2 / "dataset_b_visual_review_manifest.json"
JUDGMENTS = M2 / "dataset_b_visual_review_judgments.json"
FREEZE = M2 / "dataset_b_visual_review_freeze.json"
SAMPLE = M2 / "module2_dataset_b_screenshot_sample.json"   # holds the answer key
RESULTS = M2 / "dataset_b_visual_review_results.json"
GAPS = M2 / "dataset_b_screenshot_gaps.json"                # optional; needs the dataset
EXECUTIONS = ROOT / "reports" / "day3" / "process_executions_dataset_b.json"  # Module 1, read-only

#: Recorded AFTER the reveal, from the counts this script prints. It is an interpretation
#: of descriptive counts — not a computed metric and not a verdict on segmentation quality.
DECISION_OPTIONS = ("USEFUL CORROBORATING EVIDENCE", "INCONCLUSIVE", "IDENTIFIES CONCERNS")
DECISION_OUTCOME = "IDENTIFIES CONCERNS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze() -> int:
    manifest = _load(MANIFEST)["points"]
    judgments = _load(JUDGMENTS)["judgments"]
    assert_blind(manifest)
    assert_blind(judgments)                      # judgments carry no answer fields either
    validate_judgments(judgments, manifest)      # blind: no answer key involved
    digest = sha256_file(JUDGMENTS)
    if FREEZE.exists():
        existing = _load(FREEZE)
        if existing["judgments_sha256"] != digest:
            raise ProtocolViolation(
                "a different set of judgments was already frozen; refusing to re-freeze")
        print("already frozen with the same hash", file=sys.stderr)
        return 0
    FREEZE.write_text(json.dumps({
        "label": SURROGATE_LABEL,
        "judgments_file": str(JUDGMENTS.relative_to(ROOT)),
        "judgments_sha256": digest,
        "frozen_at": _now(),
        "answer_key_read_before_freeze": False,
        "n_judgments": len(judgments),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"frozen {len(judgments)} judgments, sha256 {digest[:16]}…", file=sys.stderr)
    return 0


def _step_systems(execution: dict) -> list[str]:
    """The systems an execution passes through, consecutive repeats collapsed."""
    out: list[str] = []
    for step in execution["ordered_steps"]:
        system = step["system"]
        if system and (not out or out[-1] != system):
            out.append(system)
    return out


def _module1_context(row: dict, executions: dict) -> dict:
    """Module 1's own record of a sampled point. Read only after the reveal and never
    used to set a label: it helps explain a disagreement, it does not score one."""
    def brief(e: dict) -> dict:
        return {"dominant_context": e["dominant_context"], "duration_ms": e["duration_ms"],
                "event_count": e["event_count"], "systems_in_order": _step_systems(e)}

    if row["kind"] == "predicted_boundary":
        return {"gap_ms": row["gap_ms"],
                "execution_before": brief(executions[row["prev_execution_id"]]),
                "execution_after": brief(executions[row["next_execution_id"]])}
    return {"execution": brief(executions[row["execution_id"]])}


def _decision(s: dict) -> dict:
    b = s["counts_by_sample_type"]["boundary_sample"]
    c = s["counts_by_sample_type"]["control_sample"]
    jb, jc = s["boundary_samples_judgeable"], s["control_samples_judgeable"]
    return {
        "outcome": DECISION_OUTCOME,
        "options": list(DECISION_OPTIONS),
        "recorded_after_reveal": True,
        "statement": ("Dataset-B visual evidence does not support the sampled boundary "
                      "interpretations as a group. It is not a measure of segmentation "
                      "quality, which this review cannot assess."),
        "basis": [
            f"Judgeable boundary samples showed a visible context change in "
            f"{b['B_CLEAR_BOUNDARY']} of {jb}; judgeable controls showed one in "
            f"{c['B_CLEAR_BOUNDARY']} of {jc}.",
            f"{b['A_CLEAR_CONTINUITY']} of {jb} judgeable boundary samples show the same "
            f"context continuing across the boundary; {c['A_CLEAR_CONTINUITY']} of {jc} "
            f"judgeable controls show clear continuity.",
            f"{s['ambiguous_total']} of {s['screenshots_available']} reviewable points were "
            f"ambiguous, and {s['screenshots_unavailable']} of {s['sample_size']} had no "
            f"image.",
        ],
        "not_a_segmentation_metric": True,
        "module2_promotion": ("Unchanged: Module 2 segmentation is NOT PROMOTED. This review "
                              "is not a basis for promotion."),
    }


def reveal() -> int:
    if not FREEZE.exists():
        raise ProtocolViolation("judgments are not frozen; run `freeze` before `reveal`")
    record = _load(FREEZE)
    verify_frozen(JUDGMENTS, record["judgments_sha256"])

    manifest = _load(MANIFEST)
    judgments_doc = _load(JUDGMENTS)
    judgments = judgments_doc["judgments"]
    validate_judgments(judgments, manifest["points"])

    # Re-running the reveal must not rewrite history: keep the time of the FIRST reveal
    # of these exact judgments.
    first_revealed_at = None
    if RESULTS.exists():
        previous = _load(RESULTS).get("blindness", {})
        if previous.get("judgments_sha256") == record["judgments_sha256"]:
            first_revealed_at = previous.get("first_revealed_at") or previous.get("revealed_at")

    # Only now is the answer key read.
    sample = {row["review_index"]: row for row in _load(SAMPLE)["sample"]}
    answer_key = {idx: row["kind"] for idx, row in sample.items()}
    executions = {e["execution_id"]: e for e in _load(EXECUTIONS)["executions"]}

    summary = summarize(judgments, answer_key)
    by_index = {p["review_index"]: p for p in manifest["points"]}
    comparison = []
    for j in sorted(judgments, key=lambda x: x["review_index"]):
        idx = j["review_index"]
        judged = j["label"] != "D_UNAVAILABLE"
        comparison.append({
            "review_index": idx,
            "session_id": by_index[idx]["session_id"],
            "sample_type": ("boundary_sample" if answer_key[idx] == "predicted_boundary"
                            else "control_sample"),
            "visual_label": j["label"],
            "confidence": j["confidence"],
            "module1_context_after_reveal":
                _module1_context(sample[idx], executions) if judged else None,
        })

    gaps = _load(GAPS) if GAPS.exists() else None

    out = {
        "label": SURROGATE_LABEL,
        "status": "SURROGATE REVIEW COMPLETED — human review not performed",
        "reviewer": judgments_doc["reviewer"],
        "human_review": judgments_doc["human_review"],
        "protocol": {
            "sample_source": manifest["sample_source"],
            "seed": manifest["seed"],
            "sample_regenerated": manifest["sample_regenerated"],
            "frame_selection": manifest["frame_selection"],
            "context_window_ms": manifest["context_window_ms"],
            "unavailable_rule": manifest["unavailable_rule"],
            "rubric": manifest["rubric"],
            "operational_rules": judgments_doc["operational_rules"],
            "revisions_before_reveal": judgments_doc["revisions_before_reveal"],
        },
        "blindness": {
            "judgments_frozen_at": record["frozen_at"],
            "judgments_sha256": record["judgments_sha256"],
            "first_revealed_at": first_revealed_at or _now(),
            "hash_verified_at_reveal": True,
        },
        "recovery": manifest["recovery"],
        "missing_screenshots": None if gaps is None else {
            "source": str(GAPS.relative_to(ROOT)),
            "summary": gaps["summary"],
            "upload_records": gaps["upload_records"],
            "upload_failure_event_types_in_log": gaps["upload_failure_event_types_in_log"],
            "sample_missing_all_in_incomplete_chunks":
                gaps["sample_missing_screenshots"]["all_in_incomplete_chunks"],
            "cause": gaps["cause"],
            "unavailable_is_not_negative_evidence": True,
        },
        "summary": summary,
        "decision": _decision(summary),
        "comparison": comparison,
        "what_this_cannot_establish": [
            "That Dataset-B segmentation is accurate. No accuracy, precision, recall or F1 "
            "is computed or implied.",
            "Anything about the 14 points whose sampled screenshot is missing; they are "
            "reported as unavailable, not as evidence either way.",
            "Inter-rater agreement: there is one reviewer, and it is a vision model.",
            "Business-level correctness: a screen shows what the UI displayed, not whether "
            "the work was right.",
        ],
    }
    RESULTS.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    s = summary
    print(f"available {s['screenshots_available']}/40, unavailable "
          f"{s['screenshots_unavailable']}/40", file=sys.stderr)
    print(f"counts {s['counts']}", file=sys.stderr)
    print(f"boundary samples {s['counts_by_sample_type']['boundary_sample']}", file=sys.stderr)
    print(f"control samples  {s['counts_by_sample_type']['control_sample']}", file=sys.stderr)
    print(f"boundary-sample visual support rate  {s['boundary_sample_visual_support_rate']} "
          f"(of {s['boundary_samples_judgeable']} judgeable)", file=sys.stderr)
    print(f"control-sample visual continuity rate {s['control_sample_visual_continuity_rate']} "
          f"(of {s['control_samples_judgeable']} judgeable)", file=sys.stderr)
    print(f"Wrote {RESULTS}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["freeze", "reveal"])
    args = ap.parse_args()
    return freeze() if args.step == "freeze" else reveal()


if __name__ == "__main__":
    sys.exit(main())
