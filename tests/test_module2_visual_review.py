"""Module 2 · Dataset-B surrogate visual review — protocol tests.

    VISION-MODEL SURROGATE REVIEW — NOT GROUND TRUTH.

What these guard:

- the fixed-seed sample is reused, never re-drawn;
- nothing a reviewer sees can reveal which points are Module-1 predicted boundaries;
- a missing screenshot is `D_UNAVAILABLE` by rule — never substituted, never evidence;
- judgments are frozen before the reveal, and any later edit is detected;
- the comparison is descriptive and deterministic, and is never named like a metric.

The committed review artifacts are checked directly; the rules themselves are also
checked on small synthetic inputs, so none of this needs the (gitignored) dataset.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import random
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

from procmine.module2.visual_review import (
    BLIND_FIELDS, CONTEXT_WINDOW_MS, FORBIDDEN_FIELDS, FORBIDDEN_METRIC_WORDS, LABELS,
    LABEL_AMBIGUOUS, LABEL_BOUNDARY, LABEL_CONTINUITY, LABEL_UNAVAILABLE, SURROGATE_LABEL,
    BlindnessViolation, ChunkScreenshots, Frame, ProtocolViolation, assert_blind,
    available_frames, blind_row, context_frame, diagnose_gaps, is_available,
    referenced_path, sha256_file, summarize, validate_judgments, verify_frozen,
)

ROOT = Path(__file__).resolve().parent.parent
M2 = ROOT / "reports" / "day6" / "module2"
SAMPLE = M2 / "module2_dataset_b_screenshot_sample.json"
SHEET = M2 / "module2_dataset_b_review_sheet.md"
MANIFEST = M2 / "dataset_b_visual_review_manifest.json"
JUDGMENTS = M2 / "dataset_b_visual_review_judgments.json"
FREEZE = M2 / "dataset_b_visual_review_freeze.json"
RESULTS = M2 / "dataset_b_visual_review_results.json"
GAPS = M2 / "dataset_b_screenshot_gaps.json"
REPORT = M2 / "dataset_b_screenshot_review_results.md"
SEED = 20260918


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sample() -> dict:
    return _load(SAMPLE)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return _load(MANIFEST)


@pytest.fixture(scope="module")
def judgments() -> list[dict]:
    return _load(JUDGMENTS)["judgments"]


@pytest.fixture(scope="module")
def answer_key(sample) -> dict[int, str]:
    return {r["review_index"]: r["kind"] for r in sample["sample"]}


def _point(idx: int, available: bool = True) -> dict:
    return {"review_index": idx, "session_id": "ses_x", "timestamp_ms": 1_000,
            "nearest_screenshot": "a.jpg" if available else "MISSING:a.jpg",
            "screenshot_delta_ms": 0, "primary_available": available}


def _judgment(idx: int, label: str, rationale: str = "visible reason") -> dict:
    return {"review_index": idx, "label": label, "confidence": "medium",
            "rationale": rationale}


# ===================== FIXED SAMPLE =====================

def test_the_review_uses_the_fixed_seed_sample(sample, manifest):
    rows = sample["sample"]
    assert sample["sampling"]["seed"] == SEED
    assert len(rows) == 40
    assert sum(r["kind"] == "predicted_boundary" for r in rows) == 20
    assert sum(r["kind"] == "mid_execution_control" for r in rows) == 20
    assert manifest["seed"] == SEED
    assert manifest["sample_regenerated"] is False
    assert manifest["sample_source"].endswith(SAMPLE.name)


def test_every_manifest_point_is_the_same_sampled_point(sample, manifest):
    by_index = {r["review_index"]: r for r in sample["sample"]}
    points = manifest["points"]
    assert [p["review_index"] for p in points] == list(range(1, 41))
    for p in points:
        row = by_index[p["review_index"]]
        for field in ("session_id", "timestamp_ms", "nearest_screenshot", "screenshot_delta_ms"):
            assert p[field] == row[field]
        assert p["referenced_screenshot"] == referenced_path(row["nearest_screenshot"])


def test_the_sample_still_matches_the_prepared_review_sheet(sample):
    """The sheet was written when the sample was drawn; the rows must still agree."""
    rows = re.findall(r"^\| (\d+) \| `[^`]*` \| `([^`]*)` \| (\d+) \|", SHEET.read_text(encoding="utf-8"),
                      flags=re.M)
    assert len(rows) == 40
    by_index = {r["review_index"]: r for r in sample["sample"]}
    for idx, shot, delta in rows:
        assert by_index[int(idx)]["nearest_screenshot"] == shot
        assert by_index[int(idx)]["screenshot_delta_ms"] == int(delta)


def test_review_order_interleaves_boundaries_and_controls(answer_key):
    order = [answer_key[i] for i in range(1, 41)]
    changes = sum(1 for a, b in zip(order, order[1:]) if a != b)
    assert changes >= 10
    first_half_boundaries = sum(k == "predicted_boundary" for k in order[:20])
    assert 5 <= first_half_boundaries <= 15


# ===================== BLINDNESS =====================

def test_the_manifest_carries_no_answer(manifest):
    for p in manifest["points"]:
        assert not set(p) & set(FORBIDDEN_FIELDS)
    assert_blind(manifest["points"])
    assert "answer key" in manifest["status"]


@pytest.mark.parametrize("field", FORBIDDEN_FIELDS)
def test_assert_blind_rejects_every_answer_bearing_field(field):
    point = _point(1)
    point[field] = "anything"
    with pytest.raises(BlindnessViolation):
        assert_blind([point])


@pytest.mark.parametrize("value", ["ses_x::bnd3", "ses_x::mid7", "predicted_boundary",
                                   "same unit of work", "different units of work"])
def test_assert_blind_rejects_answer_bearing_values(value):
    point = _point(1)
    point["note"] = value
    with pytest.raises(BlindnessViolation):
        assert_blind([point])


def test_blind_row_is_a_whitelist(sample):
    for row in sample["sample"]:
        assert tuple(blind_row(row)) == BLIND_FIELDS


def test_the_judgments_carry_no_answer(judgments):
    assert_blind(judgments)
    allowed = {"review_index", "label", "confidence", "frames_viewed", "rationale"}
    for j in judgments:
        assert set(j) <= allowed


def _string_constants(tree: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_the_preparation_script_never_touches_an_answer_field():
    tree = ast.parse((ROOT / "scripts" / "prepare_module2_visual_review.py").read_text(encoding="utf-8"))
    assert not _string_constants(tree) & set(FORBIDDEN_FIELDS)


def test_freezing_never_reads_the_answer_key():
    tree = ast.parse((ROOT / "scripts" / "finalize_module2_visual_review.py").read_text(encoding="utf-8"))
    freeze = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "freeze")
    names = {n.id for n in ast.walk(freeze) if isinstance(n, ast.Name)}
    assert not names & {"SAMPLE", "EXECUTIONS", "RESULTS"}
    assert "kind" not in _string_constants(freeze)


def test_judgments_were_frozen_before_the_reveal():
    record = _load(FREEZE)
    results = _load(RESULTS)
    assert record["answer_key_read_before_freeze"] is False
    frozen = datetime.fromisoformat(record["frozen_at"])
    revealed = datetime.fromisoformat(results["blindness"]["first_revealed_at"])
    assert frozen < revealed
    assert results["blindness"]["hash_verified_at_reveal"] is True


def test_review_images_are_not_committed():
    """Review images contain dataset screenshots; like the dataset they stay out."""
    assert not list((ROOT / "reports").rglob("*.jpg"))
    assert not list((ROOT / "reports").rglob("review_*.png"))


# ===================== MISSING SCREENSHOTS =====================

def test_is_available_requires_a_real_non_empty_file(tmp_path):
    (tmp_path / "ok.jpg").write_bytes(b"\xff\xd8data")
    (tmp_path / "empty.jpg").write_bytes(b"")
    assert is_available(tmp_path, "ok.jpg")
    assert not is_available(tmp_path, "empty.jpg")
    assert not is_available(tmp_path, "absent.jpg")
    assert not is_available(tmp_path, "MISSING:ok.jpg")
    assert not is_available(tmp_path, None)


def test_referenced_path_strips_only_the_missing_marker():
    assert referenced_path("MISSING:dataset_b/x.jpg") == "dataset_b/x.jpg"
    assert referenced_path("dataset_b/x.jpg") == "dataset_b/x.jpg"
    assert referenced_path(None) is None


def test_the_unavailable_points_are_exactly_the_missing_screenshots(sample, manifest):
    by_index = {r["review_index"]: r for r in sample["sample"]}
    unavailable = [p for p in manifest["points"] if not p["primary_available"]]
    assert len(unavailable) == 14
    for p in manifest["points"]:
        missing = by_index[p["review_index"]]["nearest_screenshot"].startswith("MISSING:")
        assert p["primary_available"] is (not missing)
    for p in unavailable:
        assert p["frames_chronological"] == []
        assert p["context_frame_found"] is False
        assert p["recovered_from"] is None
    assert manifest["recovery"] == {**manifest["recovery"], "referenced_missing": 14, "recovered": 0}


def test_every_missing_point_is_judged_unavailable_and_only_those(manifest, judgments):
    validate_judgments(judgments, manifest["points"])
    available = {p["review_index"]: p["primary_available"] for p in manifest["points"]}
    for j in judgments:
        assert (j["label"] == LABEL_UNAVAILABLE) is (not available[j["review_index"]])
        if j["label"] == LABEL_UNAVAILABLE:
            assert j["frames_viewed"] == 0


def test_no_frame_is_substituted_for_the_sampled_one(manifest):
    for p in manifest["points"]:
        if not p["primary_available"]:
            continue
        frames = p["frames_chronological"]
        paths = [f["path"] for f in frames]
        assert p["nearest_screenshot"] in paths
        session_dir = f"/{p['session_id']}/"
        assert all(session_dir in path for path in paths)
        assert all(abs(f["timestamp_ms"] - p["timestamp_ms"]) <= CONTEXT_WINDOW_MS for f in frames)
        if len(frames) == 2:   # the pair brackets the sampled moment
            assert frames[0]["timestamp_ms"] < p["timestamp_ms"] <= frames[1]["timestamp_ms"]


@pytest.mark.parametrize("label", [LABEL_CONTINUITY, LABEL_BOUNDARY, LABEL_AMBIGUOUS])
def test_a_missing_frame_cannot_be_judged_from_metadata(label):
    with pytest.raises(ProtocolViolation, match="must be D_UNAVAILABLE"):
        validate_judgments([_judgment(1, label)], [_point(1, available=False)])


def test_an_available_frame_cannot_be_skipped_as_unavailable():
    with pytest.raises(ProtocolViolation, match="must be judged"):
        validate_judgments([_judgment(1, LABEL_UNAVAILABLE)], [_point(1)])


@pytest.mark.parametrize("judgments, message", [
    ([_judgment(1, "LIKELY TRANSITION")], "not in rubric"),
    ([_judgment(1, LABEL_BOUNDARY, rationale="  ")], "stated reason"),
    ([_judgment(1, LABEL_BOUNDARY), _judgment(1, LABEL_BOUNDARY)], "judged twice"),
    ([_judgment(9, LABEL_BOUNDARY)], "unknown review"),
    ([], "no judgment recorded"),
])
def test_validate_judgments_enforces_the_protocol(judgments, message):
    with pytest.raises(ProtocolViolation, match=message):
        validate_judgments(judgments, [_point(1)])


def test_recovery_needs_the_same_session_and_the_recorded_size(tmp_path):
    prepare = _script("prepare_module2_visual_review")
    other = tmp_path / "ses_other" / "chunk" / "screenshots" / "s.jpg"
    wrong_size = tmp_path / "ses_a" / "chunk_b" / "screenshots" / "s.jpg"
    right = tmp_path / "ses_a" / "chunk_c" / "screenshots" / "s.jpg"
    for path, payload in ((other, b"12345"), (wrong_size, b"123"), (right, b"12345")):
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
    recorded = {"s.jpg": ("ses_a", 5)}
    ref = "dataset_b/ses_a/chunk_a/screenshots/s.jpg"

    assert prepare.try_recover(ref, tmp_path, {"s.jpg": [other]}, recorded, root=tmp_path) is None
    assert prepare.try_recover(ref, tmp_path, {"s.jpg": [wrong_size]}, recorded, root=tmp_path) is None
    assert prepare.try_recover(ref, tmp_path, {"s.jpg": [other, wrong_size, right]}, recorded,
                               root=tmp_path) == "ses_a/chunk_c/screenshots/s.jpg"
    # Without a record of what the file should be, a same-named file is never accepted.
    assert prepare.try_recover(ref, tmp_path, {"s.jpg": [right]}, {}, root=tmp_path) is None


# ===================== CONTEXT FRAMES =====================

FRAMES = [Frame(900, "f900.jpg"), Frame(950, "f950.jpg"), Frame(1_050, "f1050.jpg"),
          Frame(1_200, "f1200.jpg")]


def test_context_frame_takes_the_nearest_frame_after_an_earlier_primary():
    assert context_frame(FRAMES, 1_000, Frame(950, "f950.jpg")) == Frame(1_050, "f1050.jpg")


def test_context_frame_takes_the_nearest_frame_before_a_later_primary():
    assert context_frame(FRAMES, 1_000, Frame(1_050, "f1050.jpg")) == Frame(950, "f950.jpg")


def test_context_frame_never_reaches_beyond_the_window():
    frames = [Frame(0, "early.jpg"), Frame(100_000, "late.jpg")]
    # The later frame is 80 s after the sampled moment: outside the 60 s window.
    assert context_frame(frames, 20_000, Frame(0, "early.jpg"), window_ms=CONTEXT_WINDOW_MS) is None
    # 50 s away is inside it.
    assert context_frame(frames, 50_000, Frame(0, "early.jpg"),
                         window_ms=CONTEXT_WINDOW_MS) == Frame(100_000, "late.jpg")


def test_context_frame_is_none_when_the_other_side_is_empty():
    assert context_frame([Frame(950, "f950.jpg")], 1_000, Frame(950, "f950.jpg")) is None


def test_available_frames_drop_missing_references_and_sort():
    frames = available_frames([(3, "c.jpg"), (1, "MISSING:a.jpg"), (2, "b.jpg")])
    assert frames == [Frame(2, "b.jpg"), Frame(3, "c.jpg")]


# ===================== FREEZE =====================

def test_verify_frozen_detects_any_edit(tmp_path):
    path = tmp_path / "j.json"
    path.write_text('{"judgments": []}', encoding="utf-8")
    digest = sha256_file(path)
    verify_frozen(path, digest)
    path.write_text('{"judgments": [] }', encoding="utf-8")
    with pytest.raises(ProtocolViolation, match="changed after they were frozen"):
        verify_frozen(path, digest)


def test_the_committed_judgments_match_their_freeze_record():
    record = _load(FREEZE)
    assert sha256_file(JUDGMENTS) == record["judgments_sha256"]
    assert _load(RESULTS)["blindness"]["judgments_sha256"] == record["judgments_sha256"]
    assert record["n_judgments"] == 40


@pytest.fixture
def finalize(tmp_path, monkeypatch):
    """The finalize script, pointed at a scratch copy of the review artifacts."""
    module = _script("finalize_module2_visual_review")
    for name, source in (("MANIFEST", MANIFEST), ("JUDGMENTS", JUDGMENTS),
                         ("FREEZE", FREEZE), ("SAMPLE", SAMPLE)):
        target = tmp_path / source.name
        shutil.copy(source, target)
        monkeypatch.setattr(module, name, target)
    monkeypatch.setattr(module, "RESULTS", tmp_path / "results.json")
    monkeypatch.setattr(module, "GAPS", tmp_path / "absent_gaps.json")
    return module


def test_reveal_refuses_judgments_edited_after_the_freeze(finalize):
    doc = _load(finalize.JUDGMENTS)
    doc["judgments"][0]["label"] = LABEL_CONTINUITY
    finalize.JUDGMENTS.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProtocolViolation):
        finalize.reveal()
    assert not finalize.RESULTS.exists()


def test_reveal_refuses_to_run_without_a_freeze(finalize):
    finalize.FREEZE.unlink()
    with pytest.raises(ProtocolViolation, match="not frozen"):
        finalize.reveal()


def test_freeze_will_not_overwrite_a_different_frozen_set(finalize):
    record = _load(finalize.FREEZE)
    record["judgments_sha256"] = "0" * 64
    finalize.FREEZE.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ProtocolViolation, match="refusing to re-freeze"):
        finalize.freeze()


def test_freeze_rejects_judgments_that_carry_the_answer(finalize):
    finalize.FREEZE.unlink()
    doc = _load(finalize.JUDGMENTS)
    doc["judgments"][0]["kind"] = "predicted_boundary"
    finalize.JUDGMENTS.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BlindnessViolation):
        finalize.freeze()
    assert not finalize.FREEZE.exists()


def test_reveal_reproduces_the_committed_results(finalize):
    finalize.reveal()
    fresh = _load(finalize.RESULTS)
    stored = _load(RESULTS)
    assert fresh["summary"] == stored["summary"]
    assert fresh["comparison"] == stored["comparison"]
    assert fresh["decision"] == stored["decision"]


# ===================== DESCRIPTIVE SUMMARY =====================

_METRIC_KEY = re.compile(r"(^|_)(" + "|".join(FORBIDDEN_METRIC_WORDS) + r")(_|$)", re.I)


def _keys(obj) -> list[str]:
    if isinstance(obj, dict):
        return [k for k in obj] + [k2 for v in obj.values() for k2 in _keys(v)]
    if isinstance(obj, list):
        return [k for v in obj for k in _keys(v)]
    return []


def test_summary_is_never_named_like_a_metric(judgments, answer_key):
    summary = summarize(judgments, answer_key)
    assert not [k for k in _keys(summary) if _METRIC_KEY.search(k)]
    assert not [k for k in _keys(_load(RESULTS)) if _METRIC_KEY.search(k)]
    assert summary["label"] == SURROGATE_LABEL
    assert "not segmentation metrics" in summary["not_metrics_note"]


def test_summary_is_deterministic_and_order_independent(judgments, answer_key):
    first = summarize(judgments, answer_key)
    shuffled = list(judgments)
    random.Random(7).shuffle(shuffled)
    assert summarize(judgments, answer_key) == first
    assert summarize(shuffled, answer_key) == first


def test_the_stored_summary_is_a_fresh_summary_of_the_frozen_judgments(judgments, answer_key):
    stored = _load(RESULTS)["summary"]
    assert stored == summarize(judgments, answer_key)
    assert sum(stored["counts"].values()) == 40
    assert stored["screenshots_available"] + stored["screenshots_unavailable"] == 40
    assert stored["screenshots_unavailable"] == 14
    by_type = stored["counts_by_sample_type"]
    assert sum(by_type["boundary_sample"].values()) == 20
    assert sum(by_type["control_sample"].values()) == 20


def test_rates_leave_unavailable_points_out():
    judged = [_judgment(1, LABEL_BOUNDARY), _judgment(2, LABEL_UNAVAILABLE),
              _judgment(3, LABEL_CONTINUITY), _judgment(4, LABEL_UNAVAILABLE)]
    key = {1: "predicted_boundary", 2: "predicted_boundary",
           3: "mid_execution_control", 4: "mid_execution_control"}
    s = summarize(judged, key)
    assert s["screenshots_unavailable"] == 2
    assert s["boundary_samples_judgeable"] == 1
    assert s["boundary_sample_visual_support_rate"] == 1.0
    assert s["control_sample_visual_continuity_rate"] == 1.0


def test_rates_are_absent_rather_than_zero_when_nothing_is_judgeable():
    judged = [_judgment(1, LABEL_UNAVAILABLE), _judgment(2, LABEL_UNAVAILABLE)]
    s = summarize(judged, {1: "predicted_boundary", 2: "mid_execution_control"})
    assert s["boundary_sample_visual_support_rate"] is None
    assert s["control_sample_visual_continuity_rate"] is None


def test_every_label_is_counted_even_when_unused():
    s = summarize([_judgment(1, LABEL_AMBIGUOUS)], {1: "predicted_boundary"})
    assert set(s["counts"]) == set(LABELS)
    assert set(s["counts_by_sample_type"]["control_sample"]) == set(LABELS)


def test_the_decision_is_an_interpretation_not_a_metric_or_a_promotion():
    decision = _load(RESULTS)["decision"]
    assert decision["outcome"] in decision["options"]
    assert decision["recorded_after_reveal"] is True
    assert decision["not_a_segmentation_metric"] is True
    assert "NOT PROMOTED" in decision["module2_promotion"]
    assert "does not support" in decision["statement"]


def test_module1_context_is_attached_only_to_judged_points():
    for row in _load(RESULTS)["comparison"]:
        context = row["module1_context_after_reveal"]
        if row["visual_label"] == LABEL_UNAVAILABLE:
            assert context is None
        elif row["sample_type"] == "boundary_sample":
            assert set(context) == {"gap_ms", "execution_before", "execution_after"}
        else:
            assert set(context) == {"execution"}


# ===================== GAP DIAGNOSIS =====================

def _chunk(name: str, times: list[int], present: list[int], declared: int | None = None):
    return ChunkScreenshots(chunk=name, referenced={f"s{t}.jpg": t for t in times},
                            present=frozenset(f"s{t}.jpg" for t in present),
                            declared_file_count=declared)


def test_gap_diagnosis_describes_a_common_cap_and_interleaving():
    report = diagnose_gaps([
        _chunk("ses_1/c1", [1, 2, 3, 4, 5], [1, 3, 5], declared=5),   # interleaved gaps
        _chunk("ses_2/c1", [1, 2, 3, 4], [1, 2, 3], declared=4),      # tail only
        _chunk("ses_3/c1", [1, 2], [1, 2], declared=2),               # complete
    ])
    assert report["missing_files"] == 3
    assert report["incomplete_chunks"] == 2
    assert report["common_cap"] == 3
    assert report["largest_complete_chunk"] == 2
    assert report["every_chunk_above_cap_is_incomplete"] is True
    assert report["incomplete_chunks_with_interleaved_gaps"] == 1
    assert report["manifests_declaring_every_referenced_file"] == 2
    assert "cause" not in report          # the pattern is described, not explained


def test_gap_diagnosis_reports_no_cap_when_incomplete_chunks_differ():
    report = diagnose_gaps([_chunk("a/c", [1, 2, 3], [1]), _chunk("b/c", [1, 2, 3], [1, 2])])
    assert report["common_cap"] is None
    assert report["every_chunk_above_cap_is_incomplete"] is False


def test_upload_records_are_attributed_to_their_own_session(tmp_path):
    diagnose = _script("diagnose_dataset_b_screenshot_gaps")

    def write_chunk(session: str, chunk: str, events: list[dict], files: list[str]):
        d = tmp_path / session / chunk
        (d / "screenshots").mkdir(parents=True)
        (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
        (d / "manifest.json").write_text(json.dumps(
            {"files": {"screenshots": {"file_count": len(events)}}}), encoding="utf-8")
        for f in files:
            (d / "screenshots" / f).write_bytes(b"x")

    shot = lambda t: {"event_type": "screenshot_smart", "timestamp_ms": t,  # noqa: E731
                      "payload": {"file_reference": {"filename": f"s{t}.jpg"}}}
    upload = {"event_type": "upload_started", "timestamp_ms": 9,
              "payload": {"chunk_id": "chunk_1", "file_count": 3}}
    # Two sessions reuse the chunk id "chunk_1"; only session A logs an upload of it.
    write_chunk("ses_A", "chunk_1", [shot(1), shot(2)], ["s1.jpg"])
    write_chunk("ses_A", "chunk_2", [upload], [])
    write_chunk("ses_B", "chunk_1", [shot(1)], ["s1.jpg"])

    chunks, uploads = diagnose.load_chunks(tmp_path)
    assert set(uploads) == {"ses_A/chunk_1"}
    assert uploads["ses_A/chunk_1"] == {"upload_started": True, "file_count": 3}
    report = diagnose_gaps(chunks)
    assert report["incomplete_chunks"] == 1


def test_the_committed_gap_diagnosis_covers_every_missing_sample_screenshot():
    gaps = _load(GAPS)
    summary = gaps["summary"]
    assert summary["common_cap"] == 250
    assert summary["every_chunk_above_cap_is_incomplete"] is True
    assert summary["missing_files"] == summary["referenced_files"] - summary["present_files"]
    assert gaps["sample_missing_screenshots"]["n"] == 14
    assert gaps["sample_missing_screenshots"]["all_in_incomplete_chunks"] is True
    assert gaps["upload_records"]["completed_uploads_for_incomplete_chunks"] == 0
    assert "Not determinable" in gaps["cause"]


# ===================== REPORT =====================

REQUIRED_SECTIONS = ("Review protocol", "Blind sampling", "Screenshot availability",
                     "Visual rubric", "Results", "Ambiguous and unavailable cases",
                     "What this review can and cannot establish", "Decision")
_NEGATION = re.compile(r"\b(no|not|never|cannot|nor|without|none)\b|n't", re.I)
_METRIC_WORD = re.compile(r"\b(precision|recall|f1|accuracy)\b", re.I)


def test_the_report_has_every_required_section():
    headings = [line.lstrip("#").strip() for line in REPORT.read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")]
    for section in REQUIRED_SECTIONS:
        assert any(h.split(". ", 1)[-1].startswith(section) for h in headings), section


def test_the_report_labels_the_review_as_surrogate():
    text = REPORT.read_text(encoding="utf-8")
    assert SURROGATE_LABEL in text
    assert "human review" in text.lower()


def test_the_report_never_claims_a_metric():
    """Metric words may appear only in lines that deny computing them."""
    offending = [line for line in REPORT.read_text(encoding="utf-8").splitlines()
                 if _METRIC_WORD.search(line) and not _NEGATION.search(line)]
    assert offending == []


def test_the_report_quotes_the_stored_counts():
    text = REPORT.read_text(encoding="utf-8")
    s = _load(RESULTS)["summary"]
    b, c = s["counts_by_sample_type"]["boundary_sample"], s["counts_by_sample_type"]["control_sample"]
    assert f"{b[LABEL_BOUNDARY]} of {s['boundary_samples_judgeable']}" in text
    assert f"{c[LABEL_CONTINUITY]} of {s['control_samples_judgeable']}" in text
    assert f"{s['screenshots_available']} of {s['sample_size']}" in text
    assert _load(RESULTS)["decision"]["outcome"] in text
