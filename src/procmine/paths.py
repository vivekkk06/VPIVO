"""Discovery of sessions and chunks on disk.

A session directory name is `ses_<date>-<time>-<machine>`. Inside it, chunk
directories come in two shapes we've observed in the real data:

  chunk_<date>-<time>-<machine>/   <- always holds events.jsonl + manifest.json
  chunk_<HHMM>/                    <- sometimes holds only screenshots/, as a
                                       sibling of the directory above (a layout
                                       quirk in the recording agent's output,
                                       not documented in DATA_SCHEMA.md)

We never assume which shape a directory is; we detect it from its contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChunkPaths:
    chunk_dir: Path
    events_path: Path
    manifest_path: Path
    screenshot_dirs: list[Path]
    """All directories (this chunk's own, plus any matching sibling) that may
    contain this chunk's screenshots. Order = search order."""


@dataclass
class SessionPaths:
    session_dir: Path
    session_id: str
    gt_path: Path | None
    gt_manifest_path: Path | None
    chunks: list[ChunkPaths]


def _short_chunk_key(chunk_dir_name: str) -> str | None:
    """`chunk_20260630-1200-LAPTOP-R36BQBTE` -> `1200`; `chunk_1200` -> `1200`."""
    body = chunk_dir_name.removeprefix("chunk_")
    parts = body.split("-")
    for part in parts:
        if len(part) == 4 and part.isdigit():
            return part
    if body.isdigit():
        return body
    return None


def discover_session(session_dir: Path) -> SessionPaths:
    entries = sorted(p for p in session_dir.iterdir() if p.is_dir())
    full_chunk_dirs = [d for d in entries if (d / "events.jsonl").exists()]
    screenshot_only_dirs = [
        d for d in entries if d.name.startswith("chunk_") and d not in full_chunk_dirs
    ]

    chunks: list[ChunkPaths] = []
    for chunk_dir in sorted(full_chunk_dirs, key=lambda d: d.name):
        own_screens = chunk_dir / "screenshots"
        candidates = [own_screens] if own_screens.is_dir() else []

        key = _short_chunk_key(chunk_dir.name)
        if key is not None:
            for sibling in screenshot_only_dirs:
                if _short_chunk_key(sibling.name) == key:
                    sib_screens = sibling / "screenshots"
                    if sib_screens.is_dir():
                        candidates.append(sib_screens)

        chunks.append(
            ChunkPaths(
                chunk_dir=chunk_dir,
                events_path=chunk_dir / "events.jsonl",
                manifest_path=chunk_dir / "manifest.json",
                screenshot_dirs=candidates,
            )
        )

    gt_path = session_dir / "gt.jsonl"
    gt_manifest_path = session_dir / "gt_manifest.json"

    return SessionPaths(
        session_dir=session_dir,
        session_id=session_dir.name,
        gt_path=gt_path if gt_path.exists() else None,
        gt_manifest_path=gt_manifest_path if gt_manifest_path.exists() else None,
        chunks=chunks,
    )


def discover_dataset(dataset_dir: Path) -> list[SessionPaths]:
    sessions = [
        discover_session(p)
        for p in sorted(dataset_dir.iterdir())
        if p.is_dir() and p.name.startswith("ses_")
    ]
    return sessions


def resolve_screenshot(chunk: ChunkPaths, filename: str) -> Path | None:
    for d in chunk.screenshot_dirs:
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None
