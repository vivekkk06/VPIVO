#!/usr/bin/env python3
"""Day 6 · Module 2 — Dataset-B qualitative boundary review (H3).

WHY THIS EXISTS, AND WHAT IT IS NOT
-----------------------------------
Dataset B has **no ground truth**. Therefore this script computes **no accuracy, no
precision, no recall and no F1**, and nothing downstream may derive one from its
output. Dataset B is used here for *operational* validation only.

What it does produce is a **blind review sheet**: a deterministic, unbiased sample of
points in the Dataset-B event stream, each paired with the nearest available
screenshot, so a human can judge whether the segmentation's decision looks defensible.

THREE DESIGN CHOICES THAT MAKE THE SAMPLE HONEST
------------------------------------------------
1. **Deterministic.** A fixed seed and a sorted population, so the sample is
   reproducible by anyone re-running this command. Not "interesting examples".
2. **Blinded by construction.** The sample mixes predicted boundaries with
   mid-execution control points and shuffles them. A reviewer who simply answered
   "transition" every time would score no better than chance, which is exactly the
   failure mode an unblinded sheet invites.
3. **The judgment column ships empty.** This script never fills in a verdict. If no
   human review is performed, the limitation is reported as such rather than papered
   over with a model-generated label presented as evidence.

If a vision-capable model is later used to help, its output is **surrogate review**,
must be labelled as such, and may not become a segmentation metric.

Usage:
    python scripts/run_module2_dataset_b_screenshot_review.py \
        --dataset dataset_b --out reports/day6/module2 --n 40
"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: Fixed so the sample is reproducible. Changing it re-rolls the sample and must be
#: disclosed if it ever happens.
SEED = 20260918

EXECUTIONS_ARTIFACT = ROOT / "reports" / "day3" / "process_executions_dataset_b.json"

JUDGMENT_OPTIONS = ["LIKELY TRANSITION", "LIKELY SAME TASK", "AMBIGUOUS"]


def load_screenshots(dataset_dir: Path) -> dict[str, list[tuple[int, str]]]:
    """(timestamp_ms, relative path) per session, sorted — the review evidence.

    Read from the screenshot_smart events rather than by globbing the filesystem, so
    every entry has a real timestamp to match against. Existence on disk is checked
    separately and reported.
    """
    by_session: dict[str, list[tuple[int, str]]] = {}
    # Resolved so a relative --dataset still yields repo-relative display paths.
    for events_path in sorted(dataset_dir.resolve().glob("*/*/events.jsonl")):
        chunk_dir = events_path.parent
        with events_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event_type") != "screenshot_smart":
                    continue
                ref = ((e.get("payload") or {}).get("file_reference") or {})
                rel = ref.get("relative_path")
                ts = e.get("timestamp_ms")
                if not rel or ts is None:
                    continue
                full = (chunk_dir / rel).resolve()
                try:
                    shown = str(full.relative_to(ROOT))
                except ValueError:  # outside the repo; show the absolute path
                    shown = str(full)
                if not full.exists():
                    shown = f"MISSING:{shown}"
                by_session.setdefault(e["session_id"], []).append((int(ts), shown))
    for sid in by_session:
        by_session[sid].sort()
    return by_session


def nearest_screenshot(shots: list[tuple[int, str]], ts: int) -> tuple[str | None, int | None]:
    if not shots:
        return None, None
    keys = [s[0] for s in shots]
    i = bisect.bisect_left(keys, ts)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(shots):
            d = abs(shots[j][0] - ts)
            if best is None or d < best[0]:
                best = (d, shots[j][1])
    return (best[1], best[0]) if best else (None, None)


def build_population(executions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Predicted boundaries, and mid-execution control points.

    A *boundary* is the gap between two consecutive executions in the same session —
    the place Module 1 decided one unit of work ended and another began. A *control*
    is the temporal midpoint of a single execution, where Module 1 decided the work
    continued. Both are Module 1 decisions; only their direction differs.
    """
    by_session: dict[str, list[dict]] = {}
    for e in executions:
        by_session.setdefault(e["session_id"], []).append(e)
    for v in by_session.values():
        v.sort(key=lambda r: r["start_ms"])

    boundaries, controls = [], []
    for sid, execs in sorted(by_session.items()):
        for i in range(len(execs) - 1):
            a, b = execs[i], execs[i + 1]
            boundaries.append({
                "point_id": f"{sid}::bnd{i}",
                "session_id": sid,
                "kind": "predicted_boundary",
                "timestamp_ms": int((a["end_ms"] + b["start_ms"]) / 2),
                "module1_decision": "different units of work",
                "prev_execution_id": a["execution_id"],
                "next_execution_id": b["execution_id"],
                "gap_ms": int(b["start_ms"] - a["end_ms"]),
            })
        for i, e in enumerate(execs):
            if e["event_count"] < 4:
                continue  # too short for a meaningful interior point
            controls.append({
                "point_id": f"{sid}::mid{i}",
                "session_id": sid,
                "kind": "mid_execution_control",
                "timestamp_ms": int((e["start_ms"] + e["end_ms"]) / 2),
                "module1_decision": "same unit of work",
                "execution_id": e["execution_id"],
                "gap_ms": None,
            })
    return boundaries, controls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--n", type=int, default=40, help="total sampled points")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    executions = json.loads(EXECUTIONS_ARTIFACT.read_text(encoding="utf-8"))["executions"]
    boundaries, controls = build_population(executions)
    print(f"population: {len(boundaries)} predicted boundaries, "
          f"{len(controls)} mid-execution controls", file=sys.stderr)

    rng = random.Random(SEED)
    half = args.n // 2
    sample = (rng.sample(sorted(boundaries, key=lambda r: r["point_id"]),
                         min(half, len(boundaries)))
              + rng.sample(sorted(controls, key=lambda r: r["point_id"]),
                           min(args.n - half, len(controls))))
    rng.shuffle(sample)  # blind: the sheet must not be ordered by kind

    shots = load_screenshots(args.dataset)
    n_with_shot = 0
    missing_files = 0
    for k, row in enumerate(sample, start=1):
        path, delta = nearest_screenshot(shots.get(row["session_id"], []),
                                         row["timestamp_ms"])
        row["review_index"] = k
        row["nearest_screenshot"] = path
        row["screenshot_delta_ms"] = delta
        if path:
            n_with_shot += 1
            if path.startswith("MISSING:"):
                missing_files += 1
        # Ship empty. This script never fills in a verdict.
        row["review_judgment"] = None
        row["review_rationale"] = None

    out = {
        "module": "Module 2 — Adaptive Evidence-Guided Reconstruction & Automation",
        "purpose": "Qualitative, blind review of Dataset-B segmentation decisions (H3)",
        "dataset_b_rule": (
            "Dataset B is used for operational validation, not supervised segmentation "
            "evaluation. No accuracy, precision, recall or F1 is computed here, and "
            "none may be derived from this artifact."
        ),
        "provenance": {
            "boundaries_from": "reports/day3/process_executions_dataset_b.json "
                               "(Module 1 output; field start_ms/end_ms per execution)",
            "screenshots_from": "dataset_b screenshot_smart events, "
                                "payload.file_reference.relative_path",
        },
        "sampling": {
            "deterministic": True,
            "seed": SEED,
            "method": "population sorted by point_id, then random.Random(SEED).sample; "
                      "boundaries and controls drawn separately, then shuffled together",
            "blinded": True,
            "blinding_note": "The sheet mixes predicted boundaries with mid-execution "
                             "controls in shuffled order, so answering 'transition' "
                             "every time scores no better than chance.",
            "population_boundaries": len(boundaries),
            "population_controls": len(controls),
            "sampled": len(sample),
            "sampled_boundaries": sum(1 for r in sample
                                      if r["kind"] == "predicted_boundary"),
            "sampled_controls": sum(1 for r in sample
                                    if r["kind"] == "mid_execution_control"),
        },
        "screenshot_availability": {
            "points_with_a_nearest_screenshot": n_with_shot,
            "points_without": len(sample) - n_with_shot,
            "nearest_screenshot_file_missing_on_disk": missing_files,
            "delta_ms_distribution": {
                "median": sorted(r["screenshot_delta_ms"] for r in sample
                                 if r["screenshot_delta_ms"] is not None)[len(sample) // 2]
                if n_with_shot else None,
            },
        },
        "judgment_options": JUDGMENT_OPTIONS,
        "review_status": "NOT REVIEWED — judgments ship empty by design",
        "sample": sample,
    }
    path = args.out / "module2_dataset_b_screenshot_sample.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human-facing review sheet.
    lines = [
        "# Module 2 — Dataset-B blind boundary review sheet",
        "",
        "> **Blind review framework prepared; review not completed.** No Dataset-B",
        "> segmentation quality claim is made from this sheet because the judgments were",
        "> not completed. This is a prepared review instrument, not a validation result.",
        "",
        "**Dataset B has no ground truth.** Nothing on this sheet produces an accuracy",
        "number. It exists so a human can judge whether the segmentation's decisions",
        "look defensible against the screen evidence.",
        "",
        f"Deterministic sample, seed `{SEED}`. Boundaries and mid-execution controls are",
        "mixed and shuffled, so the sheet is blind: you cannot tell which is which",
        "without opening the answer key in the JSON artifact.",
        "",
        f"For each row, open the screenshot and record one of: "
        f"{', '.join('`' + j + '`' for j in JUDGMENT_OPTIONS)}.",
        "",
        "| # | session | screenshot | Δt (ms) | judgment | rationale |",
        "|---:|---|---|---:|---|---|",
    ]
    for r in sample:
        shot = r["nearest_screenshot"] or "—"
        lines.append(f"| {r['review_index']} | `{r['session_id'][:28]}` | `{shot}` | "
                     f"{r['screenshot_delta_ms'] if r['screenshot_delta_ms'] is not None else '—'} "
                     f"|  |  |")
    lines += ["", "_Judgments intentionally blank. If no human review is performed, that",
              "limitation is reported rather than filled in with a generated label._"]
    sheet = args.out / "module2_dataset_b_review_sheet.md"
    sheet.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"sampled {len(sample)} points "
          f"({out['sampling']['sampled_boundaries']} boundaries / "
          f"{out['sampling']['sampled_controls']} controls); "
          f"{n_with_shot} have a nearest screenshot", file=sys.stderr)
    print(f"Wrote {path}\nWrote {sheet}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
