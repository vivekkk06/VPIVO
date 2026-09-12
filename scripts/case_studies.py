#!/usr/bin/env python3
"""Render raw-events-vs-ground-truth timeline figures for a fixed set of
hand-picked representative sessions (see reports/day1/session_case_studies.md
for why each one was chosen — selection is based on real gt_manifest.json
properties, not arbitrary).

Usage:
    python scripts/case_studies.py --dataset dataset_a --out reports/day1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_session
from procmine.validation import ValidationReport

CASE_STUDY_SESSIONS = [
    "ses_20260630-121953-LAPTOP-R36BQBTE",  # typical: cross-chunk + clean suspend/resume + repeats + variants
    "ses_20260701-051820-CHAITANYA0BCF",     # anomaly: process suspended, never resumed in-session
    "ses_20260701-115141-SIDDHIGUPTAB00B",   # most complex (44 execs) + correlation.chunk_id identity glitch
    "ses_20260701-075548-CHAITANYA0BCF",     # least complex in the dataset (24 execs)
    "ses_20260701-070320-JAYESH",            # high noise_rate (0.25) + near-max execution count
]

LAYER_COLORS = {"SYSTEM": "#888888", "L1": "#C44E52", "L2": "#4C72B0", "L3": "#55A868"}


def plot_case_study(session_id: str, dataset_dir: Path, out_dir: Path) -> dict:
    session = discover_session(dataset_dir / session_id)
    report = ValidationReport(scope=session_id)
    events = load_session_events(session, report)
    gt_manifest = load_gt_manifest(session.gt_manifest_path, report)
    executions = parse_gt_manifest_executions(gt_manifest) if gt_manifest else []

    t0 = events[0].timestamp_ms if events else 0
    codes = sorted({e.process_code for e in executions})
    code_lane = {c: i for i, c in enumerate(codes)}
    cmap = plt.get_cmap("tab20")
    code_color = {c: cmap(i % 20) for i, c in enumerate(codes)}

    fig, (ax_gt, ax_events) = plt.subplots(
        2, 1, figsize=(12, 2 + 0.4 * len(codes)), sharex=True,
        gridspec_kw={"height_ratios": [max(1, len(codes) * 0.4), 2]},
    )

    for ex in executions:
        if ex.end_ts is None:
            continue
        start_min = (ex.start_ts.timestamp() * 1000 - t0) / 60000
        dur_min = (ex.end_ts.timestamp() * 1000 - ex.start_ts.timestamp() * 1000) / 60000
        ax_gt.broken_barh(
            [(start_min, max(dur_min, 0.05))],
            (code_lane[ex.process_code] - 0.4, 0.8),
            facecolors=code_color[ex.process_code],
        )
    ax_gt.set_yticks(list(code_lane.values()))
    ax_gt.set_yticklabels([f"{c}" for c in codes])
    ax_gt.set_ylabel("GT process code")
    ax_gt.set_title(f"{session_id}\nGround truth process intervals (top) vs. raw event stream (bottom)")

    xs = [(e.timestamp_ms - t0) / 60000 for e in events]
    ys = [e.layer for e in events]
    for layer, color in LAYER_COLORS.items():
        lx = [x for x, y in zip(xs, ys) if y == layer]
        ax_events.scatter(lx, [layer] * len(lx), s=4, color=color, alpha=0.6)
    ax_events.set_ylabel("layer")
    ax_events.set_xlabel("minutes since session start")
    ax_events.legend(handles=[Patch(color=c, label=l) for l, c in LAYER_COLORS.items()], loc="upper right", fontsize=8)

    fig.tight_layout()
    out_path = out_dir / f"case_study_{session_id}.png"
    fig.savefig(out_path, dpi=140)
    plt.close(fig)

    return {
        "session_id": session_id,
        "n_events": len(events),
        "n_gt_executions": len(executions),
        "n_processes": len(codes),
        "duration_minutes": round((events[-1].timestamp_ms - t0) / 60000, 1) if events else 0,
        "figure": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    figures_dir = args.out / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    summaries = [plot_case_study(sid, args.dataset, figures_dir) for sid in CASE_STUDY_SESSIONS]

    out_path = args.out / "case_study_summaries.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2, ensure_ascii=False)

    for s in summaries:
        print(f"{s['session_id']}: {s['n_events']} events, {s['n_gt_executions']} GT executions -> {s['figure']}", file=sys.stderr)


if __name__ == "__main__":
    main()
