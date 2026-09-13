#!/usr/bin/env python3
"""Stage 3 (pre-training): quantify the structure of transitions relative
to GT execution spans, so the noise-gap labeling decision is made from
evidence rather than assumption. Does not train anything, does not
construct final continuity labels, does not touch Dataset B.

For every transition, classifies which of two GT execution spans (if any)
its two endpoints fall into:

    SAME_EXECUTION        - both endpoints inside the same execution
    EXIT_TO_DIFFERENT_EXEC - endpoints inside two different executions
                             (no gap between them)
    EXIT_TO_NOISE          - first endpoint inside an execution, second
                             endpoint inside no execution at all
    ENTRY_FROM_NOISE        - first endpoint inside no execution, second
                             endpoint inside an execution
    NOISE_TO_NOISE          - neither endpoint inside any execution

Cross-references each category against the existing `is_boundary` label
(from Stage 2/4's containment join) to show precisely which categories
the current scheme already treats as a confident boundary, and which are
not currently labeled as anything.

Usage:
    python scripts/analyze_noise_gap_structure.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport


def containing_execution(ts_ms: int, exec_spans: list[tuple]) -> object | None:
    for start, end, case_id in exec_spans:
        if start <= ts_ms <= end:
            return case_id
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    category_counts = Counter()
    category_vs_is_boundary = Counter()  # (category, is_boundary) -> count
    examples = {}  # category -> a few example records
    n_sessions = 0
    per_session_noise_to_noise_rate = {}

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
        labeled = label_transitions(feats, [(b.timestamp_ms, b.is_resume) for b in boundaries])
        n_sessions += 1

        exec_spans = [
            (int(e.start_ts.timestamp() * 1000), int(e.end_ts.timestamp() * 1000), e.case_id)
            for e in executions
            if e.end_ts is not None
        ]

        session_noise_to_noise = 0
        session_total = 0
        for lt in labeled:
            f = lt.features
            span_i = containing_execution(f.timestamp_ms, exec_spans)
            span_next = containing_execution(f.next_timestamp_ms, exec_spans)
            session_total += 1

            if span_i is not None and span_next is not None and span_i == span_next:
                category = "SAME_EXECUTION"
            elif span_i is not None and span_next is not None and span_i != span_next:
                category = "EXIT_TO_DIFFERENT_EXEC"
            elif span_i is not None and span_next is None:
                category = "EXIT_TO_NOISE"
            elif span_i is None and span_next is not None:
                category = "ENTRY_FROM_NOISE"
            else:
                category = "NOISE_TO_NOISE"
                session_noise_to_noise += 1

            category_counts[category] += 1
            category_vs_is_boundary[(category, lt.is_boundary)] += 1

            if category not in examples:
                examples[category] = {
                    "session_id": session.session_id,
                    "event_i_id": f.event_i_id,
                    "event_next_id": f.event_next_id,
                    "delta_t_ms": f.delta_t_ms,
                    "is_boundary_label": lt.is_boundary,
                    "span_i": span_i,
                    "span_next": span_next,
                }

        per_session_noise_to_noise_rate[session.session_id] = (
            round(session_noise_to_noise / session_total, 4) if session_total else 0.0
        )

    total = sum(category_counts.values())
    print(f"{n_sessions} sessions, {total} total transitions\n", file=sys.stderr)
    print("Category breakdown:", file=sys.stderr)
    for cat, count in category_counts.most_common():
        print(f"  {cat:<26} {count:>8}  ({100*count/total:.2f}%)", file=sys.stderr)

    print("\nCategory x current is_boundary label:", file=sys.stderr)
    for (cat, is_b), count in sorted(category_vs_is_boundary.items()):
        print(f"  {cat:<26} is_boundary={is_b!s:<5} {count:>8}", file=sys.stderr)

    noise_rates = list(per_session_noise_to_noise_rate.values())
    print(f"\nNOISE_TO_NOISE rate per session: min={min(noise_rates):.3f} "
          f"max={max(noise_rates):.3f} mean={sum(noise_rates)/len(noise_rates):.3f}", file=sys.stderr)

    out = {
        "n_sessions": n_sessions,
        "n_total_transitions": total,
        "category_counts": dict(category_counts),
        "category_pct": {k: round(100 * v / total, 3) for k, v in category_counts.items()},
        "category_vs_is_boundary": {f"{cat}|is_boundary={b}": c for (cat, b), c in category_vs_is_boundary.items()},
        "examples": examples,
        "per_session_noise_to_noise_rate": per_session_noise_to_noise_rate,
    }
    out_path = args.out / f"noise_gap_structure_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
