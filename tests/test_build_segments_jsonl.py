"""Tests for the Day-3 segments.jsonl conversion helper
(`scripts/build_segments_jsonl.py`). Pure format-conversion logic --
no segmentation algorithm lives here, so these tests only check the
millisecond-to-ISO-8601-UTC conversion is correct."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "build_segments_jsonl.py"
_spec = importlib.util.spec_from_file_location("build_segments_jsonl", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["build_segments_jsonl"] = _module
_spec.loader.exec_module(_module)
ms_to_iso_utc = _module.ms_to_iso_utc


def test_known_epoch_ms_converts_correctly():
    # 1782924264390 ms is the exact start_ms of the first execution in
    # process_executions_dataset_b.json, cross-checked against the raw
    # event's own "timestamp_iso": "2026-07-01T16:44:24.390Z"
    assert ms_to_iso_utc(1782924264390) == "2026-07-01T16:44:24.390Z"


def test_zero_epoch_ms():
    assert ms_to_iso_utc(0) == "1970-01-01T00:00:00.000Z"


def test_millisecond_component_is_zero_padded():
    assert ms_to_iso_utc(1782924264005).endswith(".005Z")


def test_ends_with_z_utc_marker():
    assert ms_to_iso_utc(1700000000000).endswith("Z")


def test_output_is_lexically_sortable_like_the_input_ms():
    # a basic sanity property segments.jsonl relies on: converting two
    # ms values that differ by 1ms must not collide or reorder
    a = ms_to_iso_utc(1782924264390)
    b = ms_to_iso_utc(1782924264391)
    assert a != b
    assert a < b
