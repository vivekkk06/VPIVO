#!/usr/bin/env python3
"""Build continuity labels for a dataset per the Stage 4 approved policy,
and produce the reconciliation/class-balance/session-distribution report.

Does not train anything. Does not touch Dataset B. Does not build
context/trajectory features.

Usage:
    python scripts/build_continuity_labels.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.features import extract_transition_features
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    all_labels = []
    per_session_counts: dict[str, Counter] = {}

    for session in sessions:
        if session.gt_manifest_path is None:
            continue
        report = ValidationReport(scope=session.session_id)
        events = load_session_events(session, report)
        gt_manifest = load_gt_manifest(session.gt_manifest_path, report)
        if gt_manifest is None or not events:
            continue
        executions = parse_gt_manifest_executions(gt_manifest)
        boundaries = extract_boundaries(session.session_id, executions)
        canonical = to_canonical_stream(events)
        feats = extract_transition_features(canonical)
        labels = label_continuity(session.session_id, feats, boundaries, executions)
        all_labels.extend(labels)

        c = Counter(l.category for l in labels)
        per_session_counts[session.session_id] = c

    total = len(all_labels)
    category_counts = Counter(l.category for l in all_labels)
    n_excluded = sum(1 for l in all_labels if l.excluded)
    n_labeled = total - n_excluded
    n_positive = sum(1 for l in all_labels if l.continuity_label == 1)
    n_negative = sum(1 for l in all_labels if l.continuity_label == 0)

    print(f"Total transitions: {total}", file=sys.stderr)
    print(f"Labeled: {n_labeled} ({100*n_labeled/total:.2f}%)  Excluded: {n_excluded} ({100*n_excluded/total:.2f}%)", file=sys.stderr)
    print(f"Positive (S=1): {n_positive} ({100*n_positive/n_labeled:.2f}% of labeled)", file=sys.stderr)
    print(f"Negative (S=0): {n_negative} ({100*n_negative/n_labeled:.2f}% of labeled)", file=sys.stderr)
    print(f"Positive:Negative ratio = {n_positive/n_negative:.2f}:1", file=sys.stderr)
    print("\nCategory counts:", file=sys.stderr)
    for cat, count in category_counts.most_common():
        print(f"  {cat:<36} {count:>8}  ({100*count/total:.2f}%)", file=sys.stderr)

    assert n_labeled + n_excluded == total
    assert (
        category_counts["SAME_EXECUTION"] + category_counts["EXIT_TO_DIFFERENT_EXEC"]
        + category_counts.get("EXIT_TO_NOISE_BOUNDARY", 0)
        + category_counts.get("EXIT_TO_NOISE_UNRELIABLE_EXCLUDED", 0)
        + category_counts.get("NOISE_TO_NOISE_EXCLUDED", 0)
        + category_counts.get("ENTRY_FROM_NOISE_EXCLUDED", 0)
        == total
    )
    print("\nReconciliation check: category counts sum to total transitions exactly. PASS", file=sys.stderr)

    # Session-level distribution: flag sessions with only one label class present
    only_positive, only_negative, unusual = [], [], []
    for sid, c in per_session_counts.items():
        pos = c.get("SAME_EXECUTION", 0)
        neg = c.get("EXIT_TO_DIFFERENT_EXEC", 0) + c.get("EXIT_TO_NOISE_BOUNDARY", 0)
        if pos > 0 and neg == 0:
            only_positive.append(sid)
        elif neg > 0 and pos == 0:
            only_negative.append(sid)
        if neg > 0 and pos / neg > 500:
            unusual.append((sid, pos, neg, round(pos / neg, 1)))

    print(f"\nSessions with only positive labels (no negatives at all): {len(only_positive)}", file=sys.stderr)
    print(f"Sessions with only negative labels (no positives at all): {len(only_negative)}", file=sys.stderr)
    print(f"Sessions with an unusually extreme pos:neg ratio (>500:1): {len(unusual)}", file=sys.stderr)
    for u in unusual[:10]:
        print("  ", u, file=sys.stderr)

    out = {
        "total_transitions": total,
        "n_labeled": n_labeled,
        "n_excluded": n_excluded,
        "pct_labeled": round(100 * n_labeled / total, 2),
        "pct_excluded": round(100 * n_excluded / total, 2),
        "n_positive": n_positive,
        "n_negative": n_negative,
        "pct_positive_of_labeled": round(100 * n_positive / n_labeled, 2),
        "pct_negative_of_labeled": round(100 * n_negative / n_labeled, 2),
        "positive_to_negative_ratio": round(n_positive / n_negative, 2),
        "category_counts": dict(category_counts),
        "category_pct_of_total": {k: round(100 * v / total, 3) for k, v in category_counts.items()},
        "reconciles_with_total": True,
        "sessions_with_only_positive": only_positive,
        "sessions_with_only_negative": only_negative,
        "sessions_with_extreme_ratio": unusual,
        "per_session_category_counts": {sid: dict(c) for sid, c in per_session_counts.items()},
    }
    out_path = args.out / f"continuity_label_report_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
