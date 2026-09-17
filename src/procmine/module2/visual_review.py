"""Module 2 — Dataset-B surrogate visual review, under a blind protocol.

    VISION-MODEL SURROGATE REVIEW — NOT GROUND TRUTH.

WHAT THIS IS FOR
----------------
Dataset B has no ground truth. The prepared blind sheet (seed 20260918, N=40) pairs
20 Module-1 predicted boundaries with 20 mid-execution controls. This module holds the
rules that turn that sheet into a *completed* surrogate review without letting the
answer leak into the judgment, and without turning the result into a metric.

THE BLIND PROTOCOL
------------------
    sample id -> screenshot frames -> blind visual judgment -> FREEZE -> reveal -> compare

1. **Blind manifest.** A reviewer sees only `BLIND_FIELDS`. Everything else in a sample
   row encodes the answer: `kind` directly, `point_id` via its `::bnd`/`::mid` suffix,
   `module1_decision` in prose, `gap_ms` by being null only for controls, and the
   execution ids by whether there are one or two of them. `assert_blind` refuses a
   manifest carrying any of them.
2. **Time-anchored frames only.** Context frames are chosen by *time* around the
   sampled moment, never by execution span — selecting "the last frame of the previous
   execution" would require the execution ids and so reveal which points are
   boundaries.
3. **Unavailable is unavailable.** A point whose sampled screenshot is missing on disk
   is judged `D_UNAVAILABLE` by rule, before any image is opened. No substitute frame is
   used and nothing is inferred from event metadata.
4. **Freeze before reveal.** Judgments are hashed before the answer key is joined; the
   reveal refuses to run if the judgments changed afterwards.

WHAT THE SUMMARY IS NOT
-----------------------
The comparison is **descriptive**. It reports visual-support and visual-continuity
*rates* over a 40-point sample. It is not precision, recall, F1 or accuracy, it is not
a segmentation metric, and it is not ground truth. `summarize` names its outputs
accordingly, and a test asserts none of those metric words appear as keys.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SURROGATE_LABEL = "Vision-model surrogate review — not ground truth."

LABEL_CONTINUITY = "A_CLEAR_CONTINUITY"
LABEL_BOUNDARY = "B_CLEAR_BOUNDARY"
LABEL_AMBIGUOUS = "C_AMBIGUOUS"
LABEL_UNAVAILABLE = "D_UNAVAILABLE"
LABELS = (LABEL_CONTINUITY, LABEL_BOUNDARY, LABEL_AMBIGUOUS, LABEL_UNAVAILABLE)

#: Registered before any frame was viewed. Judges only what is visible.
RUBRIC = {
    LABEL_CONTINUITY: (
        "The frames visibly show the same business context on both sides of the "
        "sampled moment: the same application or system and the same screen, form or "
        "document."),
    LABEL_BOUNDARY: (
        "The frames visibly show a change of business context across the sampled "
        "moment: a different system, application, document, or record screen."),
    LABEL_AMBIGUOUS: (
        "The visible evidence is not enough to decide — for example a single frame, a "
        "change of view within the same screen, or a frame that shows neither context "
        "clearly."),
    LABEL_UNAVAILABLE: (
        "The sampled screenshot is missing from disk or unreadable. No judgment is "
        "inferred from event metadata."),
}

#: A context frame must fall within this distance of the sampled moment, in the same
#: session. Fixed before any frame was viewed.
CONTEXT_WINDOW_MS = 60_000

MISSING_PREFIX = "MISSING:"

#: The only sample fields a blind reviewer may see.
BLIND_FIELDS = ("review_index", "session_id", "timestamp_ms",
                "nearest_screenshot", "screenshot_delta_ms")

#: Sample fields that encode the answer. Never allowed into a blind manifest.
FORBIDDEN_FIELDS = ("kind", "point_id", "module1_decision", "execution_id",
                    "prev_execution_id", "next_execution_id", "gap_ms")

#: Strings that would reveal the answer if they appeared anywhere in the manifest.
_LEAK_TOKENS = ("predicted_boundary", "mid_execution_control", "::bnd", "::mid",
                "different units of work", "same unit of work")

#: Words the descriptive summary must never use for its own statistics.
FORBIDDEN_METRIC_WORDS = ("precision", "recall", "f1", "accuracy")


class BlindnessViolation(ValueError):
    """The reviewer-facing material carries information that reveals the answer."""


class ProtocolViolation(ValueError):
    """The judgments do not follow the registered protocol."""


# --- the blind manifest ------------------------------------------------------

def blind_row(row: dict) -> dict:
    """Only the whitelisted fields. A whitelist, so a new answer-bearing field added
    to the sample later cannot leak by default."""
    return {k: row.get(k) for k in BLIND_FIELDS}


def assert_blind(manifest: list[dict]) -> None:
    for row in manifest:
        leaked = sorted(set(row) & set(FORBIDDEN_FIELDS))
        if leaked:
            raise BlindnessViolation(f"review #{row.get('review_index')}: {leaked}")
    blob = json.dumps(manifest, ensure_ascii=False)
    for token in _LEAK_TOKENS:
        if token in blob:
            raise BlindnessViolation(f"manifest contains the answer-bearing token {token!r}")


def referenced_path(nearest: str | None) -> str | None:
    if not nearest:
        return None
    return nearest[len(MISSING_PREFIX):] if nearest.startswith(MISSING_PREFIX) else nearest


def is_available(root: Path, nearest: str | None) -> bool:
    """Available means the file really exists and is non-empty — not merely that the
    capture agent recorded a reference to it."""
    if not nearest or nearest.startswith(MISSING_PREFIX):
        return False
    path = root / nearest
    return path.is_file() and path.stat().st_size > 0


# --- context frames ----------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    timestamp_ms: int
    path: str

    def offset_s(self, t_ms: int) -> float:
        return round((self.timestamp_ms - t_ms) / 1000.0, 1)


def available_frames(entries: list[tuple[int, str]]) -> list[Frame]:
    """Drops references whose file is missing. Sorted by time."""
    return sorted((Frame(ts, p) for ts, p in entries if not p.startswith(MISSING_PREFIX)),
                  key=lambda f: (f.timestamp_ms, f.path))


def context_frame(frames: list[Frame], t_ms: int, primary: Frame,
                  window_ms: int = CONTEXT_WINDOW_MS) -> Frame | None:
    """The nearest available frame on the OTHER side of the sampled moment.

    The primary frame sits on one side of `t_ms`; this picks the closest frame on the
    opposite side so the pair brackets the moment being judged. Returns None rather
    than reaching beyond the window — a frame a minute away no longer shows the moment.
    """
    if primary.timestamp_ms < t_ms:
        candidates = [f for f in frames
                      if f.timestamp_ms >= t_ms and f.path != primary.path]
        best = min(candidates, key=lambda f: f.timestamp_ms, default=None)
    else:
        candidates = [f for f in frames
                      if f.timestamp_ms < t_ms and f.path != primary.path]
        best = max(candidates, key=lambda f: f.timestamp_ms, default=None)
    if best is None or abs(best.timestamp_ms - t_ms) > window_ms:
        return None
    return best


# --- why screenshots are missing ---------------------------------------------

@dataclass(frozen=True)
class ChunkScreenshots:
    """One capture chunk: what its event log references and what is actually on disk."""

    chunk: str
    referenced: dict[str, int]          # filename -> timestamp_ms, one entry per file
    present: frozenset[str]             # filenames that exist on disk
    declared_file_count: int | None     # the chunk manifest's own screenshot count


def diagnose_gaps(chunks: list[ChunkScreenshots]) -> dict:
    """Describe the pattern of missing screenshot files. Descriptive only.

    Reports whether absence looks like a per-chunk cap (every incomplete chunk holds
    the same number of files) and whether the absent files are interleaved in time or
    only a truncated tail. It does not claim a cause: the log cannot say where between
    capture and the delivered dataset the files were lost.
    """
    rows = []
    for c in sorted(chunks, key=lambda c: c.chunk):
        names = set(c.referenced)
        missing = sorted(names - c.present, key=lambda n: (c.referenced[n], n))
        found = names & c.present
        interleaved = None
        if missing and found:
            latest_present = max(c.referenced[n] for n in found)
            interleaved = c.referenced[missing[0]] < latest_present
        rows.append({
            "chunk": c.chunk,
            "referenced_files": len(names),
            "present_files": len(found),
            "missing_files": len(missing),
            "declared_file_count": c.declared_file_count,
            "missing_interleaved": interleaved,
        })
    incomplete = [r for r in rows if r["missing_files"]]
    complete = [r for r in rows if not r["missing_files"]]
    caps = sorted({r["present_files"] for r in incomplete})
    common_cap = caps[0] if len(caps) == 1 else None
    return {
        "chunks": len(rows),
        "referenced_files": sum(r["referenced_files"] for r in rows),
        "present_files": sum(r["present_files"] for r in rows),
        "missing_files": sum(r["missing_files"] for r in rows),
        "incomplete_chunks": len(incomplete),
        "complete_chunks": len(complete),
        "present_counts_in_incomplete_chunks": caps,
        "common_cap": common_cap,
        "largest_complete_chunk": max((r["referenced_files"] for r in complete), default=None),
        "every_chunk_above_cap_is_incomplete": (
            common_cap is not None
            and all(r["missing_files"] for r in rows if r["referenced_files"] > common_cap)),
        "incomplete_chunks_with_interleaved_gaps": sum(
            1 for r in incomplete if r["missing_interleaved"]),
        "manifests_declaring_every_referenced_file": sum(
            1 for r in incomplete if r["declared_file_count"] is not None
            and r["declared_file_count"] >= r["referenced_files"]),
        "per_chunk": rows,
    }


# --- judgments ---------------------------------------------------------------

def validate_judgments(judgments: list[dict], manifest: list[dict]) -> None:
    """Every sampled point judged exactly once, with a rubric label and a reason, and
    `D_UNAVAILABLE` used exactly when — and only when — the sampled frame is missing."""
    by_index = {m["review_index"]: m for m in manifest}
    seen: set[int] = set()
    for j in judgments:
        idx = j.get("review_index")
        if idx not in by_index:
            raise ProtocolViolation(f"judgment for unknown review #{idx}")
        if idx in seen:
            raise ProtocolViolation(f"review #{idx} judged twice")
        seen.add(idx)
        if j.get("label") not in LABELS:
            raise ProtocolViolation(f"review #{idx}: label {j.get('label')!r} not in rubric")
        if not str(j.get("rationale") or "").strip():
            raise ProtocolViolation(f"review #{idx}: a judgment needs a stated reason")
        unavailable = not by_index[idx]["primary_available"]
        if unavailable and j["label"] != LABEL_UNAVAILABLE:
            raise ProtocolViolation(
                f"review #{idx}: the sampled frame is missing, so it must be "
                f"{LABEL_UNAVAILABLE}; nothing may be inferred from metadata")
        if not unavailable and j["label"] == LABEL_UNAVAILABLE:
            raise ProtocolViolation(
                f"review #{idx}: the sampled frame exists, so it must be judged")
    missing = sorted(set(by_index) - seen)
    if missing:
        raise ProtocolViolation(f"no judgment recorded for reviews {missing}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_frozen(path: Path, expected_sha256: str) -> None:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ProtocolViolation(
            "judgments changed after they were frozen — the reveal would no longer be "
            f"blind (expected {expected_sha256[:12]}, found {actual[:12]})")


# --- the descriptive comparison, after the reveal ----------------------------

def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarize(judgments: list[dict], answer_key: dict[int, str]) -> dict:
    """Descriptive surrogate-review statistics. Never a segmentation metric.

    `answer_key` maps review index -> "predicted_boundary" | "mid_execution_control".
    Rates are computed only over points that were actually judgeable; unavailable
    points are reported as unavailable and never counted as evidence either way.
    """
    rows = sorted(judgments, key=lambda j: j["review_index"])
    overall = {label: 0 for label in LABELS}
    by_kind: dict[str, dict[str, int]] = {}
    for j in rows:
        overall[j["label"]] += 1
        kind = answer_key[j["review_index"]]
        by_kind.setdefault(kind, {label: 0 for label in LABELS})[j["label"]] += 1

    def judged(kind: str) -> int:
        counts = by_kind.get(kind, {})
        return sum(v for k, v in counts.items() if k != LABEL_UNAVAILABLE)

    b = by_kind.get("predicted_boundary", {label: 0 for label in LABELS})
    c = by_kind.get("mid_execution_control", {label: 0 for label in LABELS})

    return {
        "label": SURROGATE_LABEL,
        "sample_size": len(rows),
        "screenshots_available": len(rows) - overall[LABEL_UNAVAILABLE],
        "screenshots_unavailable": overall[LABEL_UNAVAILABLE],
        "counts": overall,
        "counts_by_sample_type": {
            "boundary_sample": b,
            "control_sample": c,
        },
        "boundary_samples_judgeable": judged("predicted_boundary"),
        "control_samples_judgeable": judged("mid_execution_control"),
        # Share of judgeable boundary samples whose frames visibly change context.
        "boundary_sample_visual_support_rate":
            _rate(b[LABEL_BOUNDARY], judged("predicted_boundary")),
        # Share of judgeable control samples whose frames visibly stay in one context.
        "control_sample_visual_continuity_rate":
            _rate(c[LABEL_CONTINUITY], judged("mid_execution_control")),
        # The two cells that would indicate a concern, reported rather than hidden.
        "boundary_samples_visually_continuous": b[LABEL_CONTINUITY],
        "control_samples_visually_changing": c[LABEL_BOUNDARY],
        "ambiguous_total": overall[LABEL_AMBIGUOUS],
        "not_metrics_note": (
            "Descriptive surrogate visual-review statistics over a 40-point sample. "
            "They are not segmentation metrics, not ground truth, and must not be "
            "reported as such."),
    }
