#!/usr/bin/env python3
"""Day 6 · Module 2 — prepare the BLIND Dataset-B surrogate visual review.

Reuses the frozen fixed-seed sample (seed 20260918, N=40) exactly as written by
`run_module2_dataset_b_screenshot_review.py`. Nothing is re-sampled.

Writes a BLIND manifest: review index, session, sampled time, and the frames to
inspect. The answer key — which points are Module-1 predicted boundaries — is never
written into the manifest, never printed by this script, and never drawn onto a review
image. `assert_blind` enforces that before anything is written.

Also re-checks every sampled screenshot that was recorded as missing: an exact
filename search across the whole dataset, accepted only if the session matches and the
file size equals the size the capture agent recorded. Nothing is downloaded and no
frame is substituted.

Review images (optional, `--composites-dir`) are reviewer convenience copies built
with ImageMagick. They contain dataset screenshots and must stay outside the
repository, like the dataset itself.

Usage:
    python scripts/prepare_module2_visual_review.py --dataset dataset_b \
        --out reports/day6/module2 --composites-dir /tmp/visual_review
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.module2.visual_review import (  # noqa: E402
    CONTEXT_WINDOW_MS, RUBRIC, SURROGATE_LABEL, Frame, assert_blind, available_frames,
    blind_row, context_frame, is_available, referenced_path,
)

SAMPLE = ROOT / "reports" / "day6" / "module2" / "module2_dataset_b_screenshot_sample.json"
FRAME_WIDTH = 1400


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "m2_screenshot_review", ROOT / "scripts" / "run_module2_dataset_b_screenshot_review.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _recorded_screenshots(dataset_dir: Path) -> dict[str, tuple[str, int | None]]:
    """filename -> (session_id, file size the capture agent recorded)."""
    out: dict[str, tuple[str, int | None]] = {}
    for events_path in sorted(dataset_dir.resolve().glob("*/*/events.jsonl")):
        with events_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event_type") != "screenshot_smart":
                    continue
                ref = (e.get("payload") or {}).get("file_reference") or {}
                name = ref.get("filename") or os.path.basename(ref.get("relative_path") or "")
                if name:
                    out[name] = (e["session_id"], ref.get("file_size_bytes"))
    return out


def try_recover(ref: str, dataset_dir: Path,
                index: dict[str, list[Path]],
                recorded: dict[str, tuple[str, int | None]],
                root: Path = ROOT) -> str | None:
    """A missing file is recovered only if an exact-name copy exists in the SAME session
    with the SAME byte size the agent recorded. Anything weaker would be substitution."""
    name = os.path.basename(ref)
    expected_session, expected_size = recorded.get(name, (None, None))
    if expected_session is None:
        return None          # no record of what the file should be: cannot verify a copy
    for hit in index.get(name, []):
        if expected_session not in hit.parts:
            continue
        if expected_size is not None and hit.stat().st_size != expected_size:
            continue
        return str(hit.resolve().relative_to(root.resolve()))
    return None


def _label(text: str, out: Path) -> None:
    subprocess.run(["magick", "-size", f"{FRAME_WIDTH}x54", "xc:#1f2937",
                    "-fill", "white", "-pointsize", "30", "-gravity", "West",
                    "-annotate", "+14+0", text, str(out)], check=True)


def build_composite(entry: dict, out_dir: Path) -> Path | None:
    frames = entry["frames_chronological"]
    if not frames:
        return None
    work = out_dir / f"_work_{entry['review_index']:02d}"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for i, fr in enumerate(frames, start=1):
        when = "EARLIER" if fr["offset_s"] < 0 else "LATER"
        header = work / f"h{i}.png"
        _label(f"Review #{entry['review_index']}  ·  frame {i} of {len(frames)}  ·  "
               f"{when} ({fr['offset_s']:+.1f} s from the sampled moment)", header)
        parts += [str(header), "(", str(ROOT / fr["path"]), "-resize", f"{FRAME_WIDTH}x", ")"]
    if len(frames) == 1:
        note = work / "note.png"
        _label("No second frame within the registered 60 s window", note)
        parts.append(str(note))
    target = out_dir / f"review_{entry['review_index']:02d}.jpg"
    subprocess.run(["magick", *parts, "-append", "-quality", "85", str(target)], check=True)
    shutil.rmtree(work, ignore_errors=True)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--composites-dir", type=Path)
    args = ap.parse_args()

    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    generator = _load_generator()
    shots = generator.load_screenshots(args.dataset)  # identical indexing to the sample

    index: dict[str, list[Path]] = defaultdict(list)
    for p in args.dataset.resolve().rglob("*.jpg"):
        index[p.name].append(p)
    recorded = _recorded_screenshots(args.dataset)

    manifest = []
    recovered_count = 0
    for row in sorted(sample["sample"], key=lambda r: r["review_index"]):
        entry = blind_row(row)            # whitelist: the answer never enters
        t = entry["timestamp_ms"]
        ref = referenced_path(entry["nearest_screenshot"])
        available = is_available(ROOT, entry["nearest_screenshot"])
        recovered = None
        if not available and ref:
            recovered = try_recover(ref, args.dataset, index, recorded)
            if recovered:
                available, recovered_count = True, recovered_count + 1

        session_entries = shots.get(entry["session_id"], [])
        frames = available_frames(session_entries)
        primary = None
        if available:
            path = recovered or entry["nearest_screenshot"]
            ts = next((ts for ts, p in session_entries if p == entry["nearest_screenshot"]), None)
            primary = Frame(ts if ts is not None else t, path)

        chronological = []
        context = None
        if primary is not None:
            context = context_frame(frames, t, primary)
            for fr in sorted([f for f in (primary, context) if f is not None],
                             key=lambda f: f.timestamp_ms):
                chronological.append({"path": fr.path, "timestamp_ms": fr.timestamp_ms,
                                      "offset_s": fr.offset_s(t)})

        entry.update({
            "referenced_screenshot": ref,
            "primary_available": available,
            "recovered_from": recovered,
            "context_frame_found": context is not None,
            "frames_chronological": chronological,
        })
        manifest.append(entry)

    assert_blind(manifest)

    out = {
        "label": SURROGATE_LABEL,
        "status": "BLIND MANIFEST — contains no answer key",
        "sample_source": str(SAMPLE.relative_to(ROOT)),
        "sample_regenerated": False,
        "seed": sample["sampling"]["seed"],
        "rubric": RUBRIC,
        "context_window_ms": CONTEXT_WINDOW_MS,
        "frame_selection": ("The sampled (nearest) frame plus the nearest AVAILABLE frame "
                            "on the other side of the sampled moment, same session, within "
                            "the window. Selected by time only, never by execution span."),
        "unavailable_rule": ("A point whose sampled frame is missing is D_UNAVAILABLE by "
                             "rule. No substitute frame is used."),
        "recovery": {
            "method": ("exact filename search across the whole dataset; accepted only "
                       "with a matching session and the recorded byte size"),
            "referenced_missing": sum(1 for m in manifest if m["referenced_screenshot"]
                                      and not m["primary_available"]) + recovered_count,
            "recovered": recovered_count,
        },
        "points": manifest,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "dataset_b_visual_review_manifest.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    n_avail = sum(1 for m in manifest if m["primary_available"])
    n_pairs = sum(1 for m in manifest if len(m["frames_chronological"]) == 2)
    print(f"blind manifest: {len(manifest)} points, {n_avail} with the sampled frame "
          f"available, {n_pairs} with a bracketing pair, {recovered_count} recovered",
          file=sys.stderr)
    print(f"Wrote {target}", file=sys.stderr)

    if args.composites_dir:
        if shutil.which("magick") is None:
            print("ImageMagick not found; skipping review images", file=sys.stderr)
            return 0
        args.composites_dir.mkdir(parents=True, exist_ok=True)
        made = [build_composite(m, args.composites_dir) for m in manifest]
        print(f"review images: {sum(1 for p in made if p)} written to {args.composites_dir}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
