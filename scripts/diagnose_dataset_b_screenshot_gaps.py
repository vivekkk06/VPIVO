#!/usr/bin/env python3
"""Day 6 · Module 2 — why are Dataset-B screenshots missing?

Reads the Dataset-B event logs and chunk manifests (read-only) and describes the pattern
of screenshot files that the capture agent referenced but the dataset does not contain.
Also checks where the missing screenshots of the blind review sample sit. Nothing is
downloaded, recovered or substituted; this only counts.

Usage:
    python scripts/diagnose_dataset_b_screenshot_gaps.py --dataset dataset_b \
        --out reports/day6/module2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.module2.visual_review import ChunkScreenshots, diagnose_gaps  # noqa: E402

MANIFEST = ROOT / "reports" / "day6" / "module2" / "dataset_b_visual_review_manifest.json"


def _events(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_chunks(dataset_dir: Path) -> tuple[list[ChunkScreenshots], dict]:
    chunks = []
    # An upload is logged in a LATER chunk of the same session and names the uploaded
    # chunk by id. Chunk ids repeat across sessions, so the key includes the session.
    uploads: dict[str, dict] = {}
    for events_path in sorted(dataset_dir.glob("*/*/events.jsonl")):
        chunk_dir = events_path.parent
        session = chunk_dir.parent.name
        referenced: dict[str, int] = {}
        for e in _events(events_path):
            kind = e.get("event_type")
            payload = e.get("payload") or {}
            if kind in ("upload_started", "upload_completed"):
                rec = uploads.setdefault(f"{session}/{payload.get('chunk_id')}", {})
                rec[kind] = True
                if "file_count" in payload:
                    rec["file_count"] = payload["file_count"]
            if kind != "screenshot_smart":
                continue
            ref = payload.get("file_reference") or {}
            name = ref.get("filename") or os.path.basename(ref.get("relative_path") or "")
            if name:
                referenced.setdefault(name, e.get("timestamp_ms") or 0)
        shot_dir = chunk_dir / "screenshots"
        present = frozenset(p.name for p in shot_dir.glob("*.jpg")) if shot_dir.is_dir() else frozenset()
        manifest_path = chunk_dir / "manifest.json"
        declared = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            declared = (manifest.get("files", {}).get("screenshots", {}) or {}).get("file_count")
        chunks.append(ChunkScreenshots(
            chunk=f"{chunk_dir.parent.name}/{chunk_dir.name}",
            referenced=referenced, present=present, declared_file_count=declared))
    return chunks, uploads


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    chunks, uploads = load_chunks(args.dataset)
    report = diagnose_gaps(chunks)
    incomplete = {r["chunk"] for r in report["per_chunk"] if r["missing_files"]}

    # Upload records per chunk. A session's last chunk cannot have one inside the
    # dataset: its upload would be logged in a chunk that was never delivered.
    last_chunk = {}
    for row in report["per_chunk"]:
        session, chunk_id = row["chunk"].split("/", 1)
        last_chunk[session] = max(last_chunk.get(session, ""), chunk_id)
    upload_rows = []
    for row in report["per_chunk"]:
        session, chunk_id = row["chunk"].split("/", 1)
        rec = uploads.get(row["chunk"]) or {}
        upload_rows.append({
            "chunk": row["chunk"],
            "incomplete": row["chunk"] in incomplete,
            "last_chunk_of_session": last_chunk[session] == chunk_id,
            "upload_started_logged": bool(rec.get("upload_started")),
            "upload_completed_logged": bool(rec.get("upload_completed")),
            "upload_file_count": rec.get("file_count"),
        })
    upload_summary = {
        "uploads_logged": sum(1 for r in upload_rows if r["upload_started_logged"]),
        "uploads_logged_as_completed": sum(1 for r in upload_rows if r["upload_completed_logged"]),
        "completed_uploads_for_incomplete_chunks": sum(
            1 for r in upload_rows if r["upload_completed_logged"] and r["incomplete"]),
        "incomplete_chunks_with_an_unfinished_upload_record": [
            r["chunk"] for r in upload_rows
            if r["incomplete"] and r["upload_started_logged"] and not r["upload_completed_logged"]],
        "incomplete_chunks_that_are_the_last_of_their_session": sum(
            1 for r in upload_rows if r["incomplete"] and r["last_chunk_of_session"]),
    }

    # Where do the sample's missing screenshots sit? Uses the BLIND manifest only.
    sample_rows = []
    if MANIFEST.exists():
        points = json.loads(MANIFEST.read_text(encoding="utf-8"))["points"]
        for p in points:
            if p["primary_available"] or not p["referenced_screenshot"]:
                continue
            parts = Path(p["referenced_screenshot"]).parts   # dataset_b/<session>/<chunk>/...
            chunk = f"{parts[1]}/{parts[2]}"
            sample_rows.append({"review_index": p["review_index"], "chunk": chunk,
                                "chunk_incomplete": chunk in incomplete})

    out = {
        "purpose": "Descriptive diagnosis of screenshot files referenced by the Dataset-B "
                   "event logs but absent from the dataset. No file is recovered, "
                   "substituted or inferred.",
        "dataset": str(args.dataset),
        "summary": {k: v for k, v in report.items() if k != "per_chunk"},
        "screenshot_events": sum(1 for p in sorted(args.dataset.glob("*/*/events.jsonl"))
                                 for e in _events(p) if e.get("event_type") == "screenshot_smart"),
        "upload_failure_event_types_in_log": [],
        "upload_records": upload_summary,
        "upload_records_per_chunk": upload_rows,
        "sample_missing_screenshots": {
            "n": len(sample_rows),
            "all_in_incomplete_chunks": all(r["chunk_incomplete"] for r in sample_rows),
            "points": sample_rows,
        },
        "cause": ("Not determinable from the repository. The pattern is consistent with a "
                  "per-chunk file limit applied somewhere between capture and the dataset "
                  "as delivered; the logs do not say where, or how the kept files were "
                  "chosen."),
        "per_chunk": report["per_chunk"],
    }
    kinds = {e.get("event_type") for p in args.dataset.glob("*/*/events.jsonl") for e in _events(p)}
    out["upload_failure_event_types_in_log"] = sorted(
        k for k in kinds if k and "upload" in k and "fail" in k)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "dataset_b_screenshot_gaps.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    s = out["summary"]
    print(f"{s['missing_files']} of {s['referenced_files']} referenced files missing; "
          f"{s['incomplete_chunks']} incomplete chunks, present counts "
          f"{s['present_counts_in_incomplete_chunks']}; sample: "
          f"{out['sample_missing_screenshots']['n']} missing, all in incomplete chunks: "
          f"{out['sample_missing_screenshots']['all_in_incomplete_chunks']}", file=sys.stderr)
    print(f"Wrote {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
