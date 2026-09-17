#!/usr/bin/env python3
"""Day 6, Phase 7 (step 1 of 2): build compressed, token-bounded segment
representations for LLM semantic labelling.

Rule 9 of the day: do not send massive raw logs to an LLM. This emits one
small summary per process — a few hundred tokens each — rather than any part
of the event stream. The whole point is that the LLM sees compressed
evidence, not the dataset.

Anti-circularity: the Day-3 `readable_name` is deliberately **withheld** from
the representation. If it were included, the model would simply read the
answer back. The label the LLM produces is compared against that withheld
name afterwards, in step 2.

The Japanese system/UI text IS included, because interpreting it is exactly
the capability being tested — the raw operational events carry no
business-process label, and the business meaning is in that text.

Output: reports/day6/llm_labeling_inputs.json
Step 2 records the LLM's labels and the comparison.

Usage:
    python scripts/build_llm_labeling_inputs.py --day3-dir reports/day3 --out reports/day6
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

TOP_N = 6


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day3-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--top-n", type=int, default=TOP_N)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    executions = json.loads(
        (args.day3_dir / "process_executions_dataset_b.json").read_text(encoding="utf-8")
    )["executions"]
    profiles = json.loads(
        (args.day3_dir / "process_profiles_dataset_b.json").read_text(encoding="utf-8")
    )
    hr = json.loads(
        (args.day3_dir / "hr_payroll_dominant_path_dataset_b.json").read_text(encoding="utf-8")
    )

    ranked = sorted(
        (p for p in profiles.values() if not p["excluded_from_ranking"]),
        key=lambda p: -p["execution_count"],
    )[: args.top_n]

    by_pid: dict[str, list[dict]] = {}
    for ex in executions:
        by_pid.setdefault(ex["dominant_context"], []).append(ex)

    hr_pid = hr["hr_process_id"]
    hr_fields = list(
        (hr.get("dominant_variant_analysis", {}) or {})
        .get("form_field_frequency", {})
        .keys()
    )

    items = []
    for p in ranked:
        pid = p["process_id"]
        exs = by_pid.get(pid, [])
        cats, etypes, systems, apps = Counter(), Counter(), Counter(), Counter()
        for ex in exs:
            for a in ex.get("applications", []) or []:
                apps[a] += 1
            for s in ex.get("ordered_steps", []):
                cats[s.get("interaction_category") or "none"] += s.get("n_events", 0)
                if s.get("system"):
                    systems[s["system"]] += s.get("n_events", 0)
                for t, n in s.get("dominant_event_types", []):
                    etypes[t] += n
        durs = [ex["duration_ms"] for ex in exs] or [0]

        item = {
            "process_id": pid,  # contains the Japanese system/document name
            "execution_count": p["execution_count"],
            "n_variants": p["n_variants"],
            "dominant_variant_share": p["dominant_variant_share"],
            "median_duration_ms": int(statistics.median(durs)),
            "mean_events_per_execution": p["event_count_distribution"].get("mean"),
            "manual_event_share": p["avg_manual_event_share"],
            "n_operators": len(p.get("frequency_by_operator", {})),
            "applications_top": [a for a, _ in apps.most_common(5)],
            "systems_touched_top": [s for s, _ in systems.most_common(5)],
            "interaction_categories_top": [c for c, _ in cats.most_common(6)],
            "event_types_top": [t for t, _ in etypes.most_common(6)],
        }
        if pid == hr_pid and hr_fields:
            # Japanese UI placeholder text -- the strongest semantic evidence
            item["ui_form_fields"] = hr_fields
        items.append(item)

    out = {
        "purpose": "Compressed evidence for LLM semantic labelling (Day-6 Phase 7).",
        "withheld_note": "The Day-3 `readable_name` is deliberately NOT included in these "
                         "representations, so the LLM cannot read the answer back. It is used "
                         "only for comparison in step 2.",
        "size_note": "One short summary per process. No raw event stream is sent to the LLM.",
        "n_items": len(items),
        "items": items,
    }
    path = args.out / "llm_labeling_inputs.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path} ({len(items)} compressed process representations)", file=sys.stderr)
    for it in items:
        print(f"  {it['process_id'][:52]:52s} n={it['execution_count']}", file=sys.stderr)


if __name__ == "__main__":
    main()
