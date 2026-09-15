#!/usr/bin/env python3
"""Day 4: run the session-level instrumentation-health diagnostic over a
dataset and, when a locked-baseline artifact is supplied, evaluate how
well the diagnostic's flag lines up with the locked pipeline's own
per-session segmentation quality.

This script is read-only with respect to raw data and does not touch the
locked segmentation path -- it never imports V1/V2, the reconstruction
rules, or the protection layer. When `--baseline` is given, it only
*reads* the already-produced Dataset-A experiment artifact to compare
against; it does not re-run or modify segmentation.

Ground truth is used for one purpose only: evaluating whether the
GT-free diagnostic agrees with observed per-session segmentation quality
on Dataset A. The diagnostic itself consumes no ground truth, which is
what allows the same code to run unchanged on Dataset B.

Usage:
    python scripts/analyze_instrumentation_health.py \
        --dataset dataset_a --out reports/day4 \
        --baseline reports/day2/protected_boundary_experiment_dataset_a.json

    python scripts/analyze_instrumentation_health.py \
        --dataset dataset_b --out reports/day4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.instrumentation_health import (  # noqa: E402
    assess_instrumentation_health,
    summarize_dataset_health,
)
from procmine.loaders.events import load_session_events  # noqa: E402
from procmine.paths import discover_dataset  # noqa: E402
from procmine.segmentation.canonical import to_canonical_stream  # noqa: E402
from procmine.validation import ValidationReport  # noqa: E402


def machine_of(session_id: str) -> str:
    """Sessions are named ses_<date>-<time>-<machine>."""
    parts = session_id.split("-", 2)
    return parts[2] if len(parts) > 2 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="optional locked-baseline experiment JSON (Dataset A only) to "
             "evaluate the diagnostic's agreement with observed quality",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    dataset_name = args.dataset.name

    healths = []
    for session in discover_dataset(args.dataset):
        report = ValidationReport(scope=session.session_id)
        events = load_session_events(session, report)
        canonical = to_canonical_stream(events)
        healths.append(assess_instrumentation_health(session.session_id, canonical))

    healths.sort(key=lambda h: h.session_id)
    summary = summarize_dataset_health(healths)
    print(f"{dataset_name}: {summary['n_sessions']} sessions, "
          f"{summary['n_degraded']} degraded", file=sys.stderr)

    by_machine: dict[str, dict] = defaultdict(lambda: {"n": 0, "n_degraded": 0, "sessions": []})
    for h in healths:
        m = by_machine[machine_of(h.session_id)]
        m["n"] += 1
        m["n_degraded"] += 1 if h.is_degraded else 0
        m["sessions"].append(h.session_id)

    result = {
        "dataset": dataset_name,
        "summary": summary,
        "per_session": [h.to_dict() for h in healths],
        "by_machine": {k: by_machine[k] for k in sorted(by_machine)},
    }

    # --- Optional: agreement with the locked baseline's own per-session quality ---
    if args.baseline is not None:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        per_session_f1 = {
            sid: m["f1"]
            for sid, m in baseline["systems"]["Strategy_Combined"]["per_session"].items()
        }
        per_session_under = {
            sid: m["under_segmentation_rate"]
            for sid, m in baseline["systems"]["Strategy_Combined"]["per_session"].items()
        }
        per_session_over = {
            sid: m["over_segmentation_rate"]
            for sid, m in baseline["systems"]["Strategy_Combined"]["per_session"].items()
        }
        per_session_frag = {
            sid: m["pct_fragmented"]
            for sid, m in baseline["systems"]["Strategy_Combined"]["per_session"].items()
        }

        flagged = [h for h in healths if h.is_degraded and h.session_id in per_session_f1]
        healthy = [h for h in healths if not h.is_degraded and h.session_id in per_session_f1]

        def stats(hs, table):
            vals = [table[h.session_id] for h in hs]
            if not vals:
                return None
            return {
                "n": len(vals),
                "median": round(statistics.median(vals), 6),
                "mean": round(statistics.fmean(vals), 6),
                "min": round(min(vals), 6),
                "max": round(max(vals), 6),
            }

        # Confusion is reported against an explicitly-stated observable:
        # "did the locked pipeline do materially worse on this session".
        # The cut is the healthy population's own 5th percentile F1, so it
        # is derived from the data rather than hand-picked to flatter the
        # diagnostic. Stated plainly: this is a descriptive agreement
        # check, not proof of causation.
        healthy_f1s = sorted(per_session_f1[h.session_id] for h in healthy)
        idx = max(0, int(0.05 * len(healthy_f1s)) - 1)
        poor_cut = healthy_f1s[idx] if healthy_f1s else 0.0

        tp = sum(1 for h in flagged if per_session_f1[h.session_id] <= poor_cut)
        fp = sum(1 for h in flagged if per_session_f1[h.session_id] > poor_cut)
        fn = sum(1 for h in healthy if per_session_f1[h.session_id] <= poor_cut)
        tn = sum(1 for h in healthy if per_session_f1[h.session_id] > poor_cut)

        result["baseline_agreement"] = {
            "note": "Ground truth used ONLY to evaluate the diagnostic; the "
                    "diagnostic itself consumes none. Segmentation was not "
                    "re-run or modified.",
            "interpretation_caveat": "These figures describe OBSERVED segmentation "
                                     "behaviour on flagged versus healthy sessions. "
                                     "They do not establish that the diagnostic "
                                     "predicts segmentation quality.",
            "poor_performance_cut_f1": round(poor_cut, 6),
            "poor_cut_derivation": "5th percentile of the healthy population's own F1",
            "flagged_f1": stats(flagged, per_session_f1),
            "healthy_f1": stats(healthy, per_session_f1),
            "flagged_under_segmentation": stats(flagged, per_session_under),
            "healthy_under_segmentation": stats(healthy, per_session_under),
            "flagged_over_segmentation": stats(flagged, per_session_over),
            "healthy_over_segmentation": stats(healthy, per_session_over),
            "flagged_pct_fragmented": stats(flagged, per_session_frag),
            "healthy_pct_fragmented": stats(healthy, per_session_frag),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "sensitivity": round(tp / (tp + fn), 6) if (tp + fn) else None,
            "specificity": round(tn / (tn + fp), 6) if (tn + fp) else None,
            "flagged_sessions": [
                {
                    "session_id": h.session_id,
                    "machine": machine_of(h.session_id),
                    "coverage": round(h.browser_domain_coverage, 6),
                    "distinct_domains": h.n_distinct_browser_domains,
                    "baseline_f1": round(per_session_f1[h.session_id], 6),
                    "baseline_under_segmentation": round(per_session_under[h.session_id], 6),
                }
                for h in flagged
            ],
        }

        print(f"  flagged F1 median={result['baseline_agreement']['flagged_f1']['median']:.4f} "
              f"vs healthy median={result['baseline_agreement']['healthy_f1']['median']:.4f}",
              file=sys.stderr)

    out_path = args.out / f"instrumentation_health_{dataset_name}.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)

    for h in healths:
        if h.is_degraded:
            print(f"  DEGRADED {h.session_id} "
                  f"coverage={h.browser_domain_coverage:.2%} "
                  f"domains={h.n_distinct_browser_domains}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
