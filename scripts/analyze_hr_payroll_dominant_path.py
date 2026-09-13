#!/usr/bin/env python3
"""Focused forensic analysis of the HR/Payroll System's dominant
(single-system, 77%) variant, requested before any Step-3 prototype
work. Does NOT touch the Dataset-A locked architecture and does NOT
build any automation code -- this is analysis only.

Rebuilds Section 3's exact execution pipeline (system-change boundaries
+ leave-and-return merge, unchanged from `build_process_executions_dataset_b.py`)
directly against the raw dataset, rather than reverse-engineering event
slices from the already-written `process_executions_dataset_b.json` by
timestamp range -- an earlier draft of this script tried the
timestamp-range approach and a cross-check caught it silently
misattributing events for 16 of 94 executions wherever two events share
an exact millisecond at a segment boundary. Rebuilding from the same
index-based pipeline that originally produced the JSON is exact by
construction; the JSON is used only to confirm this rebuild reproduces
the same `execution_id`s and counts, not as the source of the event
slices themselves.

No business semantics are invented: page/route names, field labels, and
DOM element identifiers below are quoted directly from the schema's own
payload fields (`payload.url`, `payload.field.label`,
`payload.element.attributes.id`), not guessed.

Usage:
    python scripts/analyze_hr_payroll_dominant_path.py --dataset dataset_b --executions reports/day3/process_executions_dataset_b.json --out reports/day3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.paths import discover_dataset
from procmine.process_discovery.boundaries import system_change_boundaries
from procmine.process_discovery.dom_evidence import (
    KNOWN_ROUTE_PREFIXES,
    click_context_route,
    click_target,
    form_field_info,
    navigation_route_change,
)
from procmine.process_discovery.document_identity import document_key
from procmine.process_discovery.dominant_path_forensics import classify_variant, surrounding_context
from procmine.process_discovery.execution_construction import build_executions, merge_leave_and_return
from procmine.process_discovery.variant_analysis import variant_signature
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.segment_coherence import segment_index_bounds
from procmine.validation import ValidationReport

HR_PROCESS_ID = "system:HR人事給与システム"
MERGE_MAX_AWAY_EVENTS = 5  # Section 3's own value -- reused, not re-selected


def dist_summary(values):
    if not values:
        return {"n": 0}
    s = sorted(values)
    def pct(p):
        return s[min(int(len(s) * p), len(s) - 1)]
    return {
        "n": len(values), "mean": round(statistics.fmean(values), 2), "median": statistics.median(values),
        "std": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
        "p25": pct(0.25), "p75": pct(0.75), "min": min(values), "max": max(values),
    }


def rebuild_executions_with_raw_slices(dataset_dir: Path) -> dict[str, tuple[dict, list[dict]]]:
    """Reruns Section 3's exact pipeline and returns, for every
    execution_id, its (Execution.to_dict(), raw_event_slice) pair --
    the raw events are sliced by the SAME index range the execution was
    built from, not reconstructed from timestamps afterward."""
    sessions = discover_dataset(dataset_dir)
    out: dict[str, tuple[dict, list[dict]]] = {}
    for s in sessions:
        report = ValidationReport(scope=s.session_id)
        events = load_session_events(s, report)
        if not events:
            continue
        operator = events[0].raw.get("source", {}).get("machine_id", "unknown")
        canonical = to_canonical_stream(events)
        raw_sorted = [e.raw for e in events]  # load_session_events already sorts by timestamp_ms
        raw_boundary = system_change_boundaries(canonical)
        merged_boundary = merge_leave_and_return(canonical, raw_boundary, max_away_events=MERGE_MAX_AWAY_EVENTS)
        execs = build_executions(s.session_id, operator, canonical, merged_boundary)
        ranges = segment_index_bounds(len(canonical), merged_boundary)
        assert len(execs) == len(ranges)
        for ex, (start_idx, end_idx) in zip(execs, ranges):
            out[ex.execution_id] = (ex.to_dict(), raw_sorted[start_idx : end_idx + 1])
    return out


def analyze_group(items: list[tuple[dict, list[dict]]], raw_by_session: dict[str, list[dict]]) -> dict:
    event_type_counter = Counter()
    click_target_counter = Counter()
    form_field_counter = Counter()
    input_method_counter = Counter()
    route_visit_counter = Counter()
    n_routes_per_exec = []
    entry_event_types = Counter()
    exit_event_types = Counter()
    entry_prev_apps = Counter()
    exit_next_apps = Counter()
    mouse_vs_browser_click = Counter()
    clipboard_counts, keystroke_counts = [], []
    per_exec_records = []

    for ex, seg in items:
        raw = raw_by_session.get(ex["session_id"], [])
        before, after = surrounding_context(raw, ex["start_ms"], ex["end_ms"])

        routes_this_exec: set[str] = set()
        n_clipboard = n_keystroke = 0
        for e in seg:
            et = e["event_type"]
            event_type_counter[et] += 1
            if et == "mouse_click":
                mouse_vs_browser_click["mouse_click"] += 1
            if et == "browser_click":
                mouse_vs_browser_click["browser_click"] += 1
                tgt = click_target(e)
                if tgt:
                    click_target_counter[(tgt["id"], tgt["class"])] += 1
                route = click_context_route(e)
                if route:
                    routes_this_exec.add(route)
            if et == "browser_form_input":
                info = form_field_info(e)
                if info:
                    form_field_counter[(info["id"], info["label"])] += 1
                    input_method_counter[info["input_method"]] += 1
                    if info["url_route"]:
                        routes_this_exec.add(info["url_route"])
            if et == "browser_navigation":
                change = navigation_route_change(e)
                if change:
                    if change["to"]:
                        routes_this_exec.add(change["to"])
                    if change["from"]:
                        routes_this_exec.add(change["from"])
            if et == "clipboard_change":
                n_clipboard += 1
            if et == "keystroke":
                n_keystroke += 1

        for r in routes_this_exec:
            route_visit_counter[r] += 1
        n_routes_per_exec.append(len(routes_this_exec))
        clipboard_counts.append(n_clipboard)
        keystroke_counts.append(n_keystroke)

        if seg:
            entry_event_types[seg[0]["event_type"]] += 1
            exit_event_types[seg[-1]["event_type"]] += 1

        def app_name(raw_event):
            ctx = (raw_event.get("context") or {}) if raw_event else {}
            app = ctx.get("active_app")
            return app.get("app_name") if app else None

        entry_prev_apps[app_name(before)] += 1
        exit_next_apps[app_name(after)] += 1

        per_exec_records.append({
            "execution_id": ex["execution_id"], "event_count": ex["event_count"],
            "duration_ms": ex["duration_ms"], "routes_visited": sorted(routes_this_exec),
        })

    return {
        "n_executions": len(items),
        "event_type_frequency": dict(event_type_counter.most_common()),
        "click_target_frequency": {f"{k[0]}|{k[1]}": v for k, v in click_target_counter.most_common(20)},
        "form_field_frequency": {f"{k[0]}|{k[1]}": v for k, v in form_field_counter.most_common(20)},
        "form_input_method_distribution": dict(input_method_counter),
        "mouse_click_vs_browser_click": dict(mouse_vs_browser_click),
        "route_visit_frequency": dict(route_visit_counter.most_common()),
        "n_distinct_routes_per_execution": dist_summary(n_routes_per_exec),
        "clipboard_change_per_execution": dist_summary(clipboard_counts),
        "keystroke_per_execution": dist_summary(keystroke_counts),
        "entry_event_type_distribution": dict(entry_event_types.most_common()),
        "exit_event_type_distribution": dict(exit_event_types.most_common()),
        "app_immediately_before_entry": dict(entry_prev_apps.most_common()),
        "app_immediately_after_exit": dict(exit_next_apps.most_common()),
        "event_count_distribution": dist_summary([ex["event_count"] for ex, _ in items]),
        "duration_ms_distribution": dist_summary([ex["duration_ms"] for ex, _ in items]),
        "per_execution": per_exec_records,
    }


def word_documents_in_detour(items: list[tuple[dict, list[dict]]]) -> dict:
    doc_counter = Counter()
    for _ex, seg in items:
        for e in seg:
            active_app = (e.get("context") or {}).get("active_app") or {}
            if active_app.get("app_name") == "Microsoft Word":
                dk = document_key("Microsoft Word", active_app.get("window_title"))
                if dk:
                    doc_counter[dk] += 1
    return dict(doc_counter.most_common())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--executions", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    expected = json.loads(args.executions.read_text(encoding="utf-8"))
    rebuilt = rebuild_executions_with_raw_slices(args.dataset)

    # Cross-check: the rebuild must reproduce the same execution set the
    # committed process_executions_dataset_b.json already contains.
    mismatches = 0
    for ex in expected["executions"]:
        pair = rebuilt.get(ex["execution_id"])
        if pair is None or pair[0]["event_count"] != ex["event_count"] or pair[0]["dominant_context"] != ex["dominant_context"]:
            mismatches += 1
    print(f"Rebuild cross-check against process_executions_dataset_b.json: "
          f"{mismatches}/{len(expected['executions'])} executions differ", file=sys.stderr)

    hr_items = [(ex, seg) for ex, seg in rebuilt.values() if ex["dominant_context"] == HR_PROCESS_ID]
    print(f"\n{len(hr_items)} HR/Payroll executions found (of {len(rebuilt)} total)", file=sys.stderr)

    dominant, word_detour, rare_edge = [], [], []
    for ex, seg in hr_items:
        group = classify_variant(ex["ordered_steps"], HR_PROCESS_ID)
        {"dominant": dominant, "word_detour": word_detour, "other": rare_edge}[group].append((ex, seg))

    n_hr = len(hr_items)
    print(f"dominant={len(dominant)} ({100*len(dominant)/n_hr:.1f}%)  "
          f"word_detour={len(word_detour)} ({100*len(word_detour)/n_hr:.1f}%)  "
          f"rare_edge={len(rare_edge)} ({100*len(rare_edge)/n_hr:.1f}%)", file=sys.stderr)

    # `surrounding_context` needs each FULL session's event list (to look
    # just outside an execution's own boundaries), not any one execution's
    # own slice -- reloaded per distinct session below.
    session_ids = {ex["session_id"] for ex, _ in hr_items}
    full_session_raw = {}
    for sid in session_ids:
        report = ValidationReport(scope=sid)
        sessions = [s for s in discover_dataset(args.dataset) if s.session_id == sid]
        events = load_session_events(sessions[0], report)
        full_session_raw[sid] = [e.raw for e in events]

    dominant_analysis = analyze_group(dominant, full_session_raw)
    word_detour_analysis = analyze_group(word_detour, full_session_raw)
    rare_edge_analysis = analyze_group(rare_edge, full_session_raw)
    word_detour_documents = word_documents_in_detour(word_detour)

    print("\n--- Dominant variant (n={}) ---".format(len(dominant)), file=sys.stderr)
    print("event types:", dominant_analysis["event_type_frequency"], file=sys.stderr)
    print("routes visited:", dominant_analysis["route_visit_frequency"], file=sys.stderr)
    print("form input methods:", dominant_analysis["form_input_method_distribution"], file=sys.stderr)
    print("click target top:", list(dominant_analysis["click_target_frequency"].items())[:8], file=sys.stderr)
    print("entry event types:", dominant_analysis["entry_event_type_distribution"], file=sys.stderr)
    print("exit event types:", dominant_analysis["exit_event_type_distribution"], file=sys.stderr)
    print("app before entry:", dominant_analysis["app_immediately_before_entry"], file=sys.stderr)
    print("app after exit:", dominant_analysis["app_immediately_after_exit"], file=sys.stderr)
    print("duration dist:", dominant_analysis["duration_ms_distribution"], file=sys.stderr)
    print("event count dist:", dominant_analysis["event_count_distribution"], file=sys.stderr)
    print("n_distinct_routes_per_execution:", dominant_analysis["n_distinct_routes_per_execution"], file=sys.stderr)

    print("\n--- Word-detour variant (n={}) documents opened ---".format(len(word_detour)), file=sys.stderr)
    print(word_detour_documents, file=sys.stderr)

    print("\n--- Rare edge cases (n={}) ---".format(len(rare_edge)), file=sys.stderr)
    for ex, _seg in rare_edge:
        print(f"  {ex['execution_id']}: events={ex['event_count']} dur={ex['duration_ms']}ms "
              f"variant={variant_signature(ex['ordered_steps'])}", file=sys.stderr)

    out = {
        "hr_process_id": HR_PROCESS_ID,
        "rebuild_cross_check_mismatches": mismatches,
        "n_hr_executions_total": n_hr,
        "variant_split": {
            "dominant": {"n": len(dominant), "share": round(len(dominant) / n_hr, 4)},
            "word_detour": {"n": len(word_detour), "share": round(len(word_detour) / n_hr, 4)},
            "rare_edge": {"n": len(rare_edge), "share": round(len(rare_edge) / n_hr, 4)},
        },
        "dominant_variant_analysis": dominant_analysis,
        "word_detour_variant_analysis": word_detour_analysis,
        "word_detour_documents_opened": word_detour_documents,
        "rare_edge_cases": [
            {"execution_id": ex["execution_id"], "event_count": ex["event_count"], "duration_ms": ex["duration_ms"],
             "variant_signature": list(variant_signature(ex["ordered_steps"]))}
            for ex, _seg in rare_edge
        ],
        "rare_edge_analysis": rare_edge_analysis,
        "route_id_prefix_correspondence": KNOWN_ROUTE_PREFIXES,
    }
    out_path = args.out / "hr_payroll_dominant_path_dataset_b.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
