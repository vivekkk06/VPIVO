from datetime import datetime, timezone

from procmine.models import GTExecution
from procmine.segmentation.continuity_labels import (
    ENTRY_FROM_NOISE_EXCLUDED,
    EXCLUDED_CATEGORIES,
    EXIT_TO_DIFFERENT_EXEC,
    EXIT_TO_NOISE_BOUNDARY,
    EXIT_TO_NOISE_UNRELIABLE_EXCLUDED,
    NOISE_TO_NOISE_EXCLUDED,
    SAME_EXECUTION,
    label_continuity,
)
from procmine.segmentation.features import TransitionFeatures
from procmine.segmentation.model import FEATURE_NAMES
from procmine.segmentation.signals import Boundary


def _f(t_ms, next_t_ms) -> TransitionFeatures:
    return TransitionFeatures(
        session_id="s1", event_i_id=f"e{t_ms}", event_next_id=f"e{next_t_ms}",
        timestamp_ms=t_ms, next_timestamp_ms=next_t_ms,
        delta_t_ms=next_t_ms - t_ms, log1p_delta_t_ms=0.0,
        density_before=0, density_after=0, application_changed=False,
        window_title_changed=False, browser_domain_changed=False,
        interaction_category_changed=False, extracted_text_at_transition=False,
        chunk_boundary=False,
    )


def _exec(case_id, start_s, end_s) -> GTExecution:
    return GTExecution(
        process_code="A", process_name=None, case_id=case_id,
        start_ts=datetime.fromtimestamp(start_s, tz=timezone.utc),
        end_ts=datetime.fromtimestamp(end_s, tz=timezone.utc),
        variant=None,
    )


def test_same_execution_gets_positive_label():
    # transition entirely inside one execution [0,100]
    feats = [_f(10_000, 20_000)]
    execs = [_exec("c1", 0, 100)]
    labels = label_continuity("s1", feats, [], execs)
    assert labels[0].category == SAME_EXECUTION
    assert labels[0].continuity_label == 1
    assert labels[0].excluded is False


def test_exit_to_different_execution_gets_negative_label():
    # c1 ends at 10.000s, c2 starts at 10.001s -- adjacent, effectively no
    # gap, but not an exact-millisecond collision (real Dataset A GT
    # timestamps carry microsecond precision and were never observed to
    # collide exactly -- see the reconciliation check in the Stage 4
    # report; an exact tie is a documented, untested edge case, not
    # something exercised by real data)
    feats = [_f(9_000, 10_001)]
    execs = [_exec("c1", 0, 10), _exec("c2", 10.001, 20)]
    boundaries = [Boundary("s1", 10_000, False, "A", "A")]
    labels = label_continuity("s1", feats, boundaries, execs)
    assert labels[0].category == EXIT_TO_DIFFERENT_EXEC
    assert labels[0].continuity_label == 0
    assert labels[0].excluded is False


def test_exit_to_noise_with_boundary_evidence_gets_negative_label():
    # c1 ends at 10s, c2 doesn't start until 20s -- a real gap, but the
    # boundary-first label still marks the exit transition (per
    # extract_boundaries' pairing of consecutive executions)
    feats = [_f(9_000, 15_000)]
    execs = [_exec("c1", 0, 10), _exec("c2", 20, 30)]
    boundaries = [Boundary("s1", 10_000, False, "A", "A")]
    labels = label_continuity("s1", feats, boundaries, execs)
    assert labels[0].category == EXIT_TO_NOISE_BOUNDARY
    assert labels[0].continuity_label == 0
    assert labels[0].excluded is False


def test_exit_to_noise_without_boundary_evidence_is_excluded():
    # c1 is the session's last execution -- no paired boundary exists at all
    feats = [_f(9_000, 15_000)]
    execs = [_exec("c1", 0, 10)]
    labels = label_continuity("s1", feats, [], execs)
    assert labels[0].category == EXIT_TO_NOISE_UNRELIABLE_EXCLUDED
    assert labels[0].continuity_label is None
    assert labels[0].excluded is True
    assert labels[0].excluded_reason is not None


def test_noise_to_noise_is_excluded():
    feats = [_f(100_000, 110_000)]
    execs = [_exec("c1", 0, 10)]
    labels = label_continuity("s1", feats, [], execs)
    assert labels[0].category == NOISE_TO_NOISE_EXCLUDED
    assert labels[0].continuity_label is None
    assert labels[0].excluded is True


def test_entry_from_noise_is_excluded():
    feats = [_f(15_000, 21_000)]
    execs = [_exec("c1", 20, 30)]
    labels = label_continuity("s1", feats, [], execs)
    assert labels[0].category == ENTRY_FROM_NOISE_EXCLUDED
    assert labels[0].continuity_label is None
    assert labels[0].excluded is True


def test_no_excluded_transition_appears_in_training_table():
    feats = [
        _f(10_000, 20_000),   # SAME_EXECUTION
        _f(100_000, 110_000),  # NOISE_TO_NOISE
        _f(15_000, 25_000),    # ENTRY_FROM_NOISE
    ]
    execs = [_exec("c1", 0, 30), _exec("c2", 20, 30)]
    # deliberately overlapping/simple spans just to exercise all branches;
    # what matters here is the invariant, not the specific scenario realism
    execs = [_exec("c1", 0, 30)]
    labels = label_continuity("s1", feats, [], execs)
    training_rows = [l for l in labels if not l.excluded]
    assert all(l.category not in EXCLUDED_CATEGORIES for l in training_rows)
    assert all(l.continuity_label is not None for l in training_rows)


def test_no_gt_metadata_in_model_feature_names():
    forbidden = {"process_code", "case_id", "process_variant", "session_id"}
    assert forbidden.isdisjoint(set(FEATURE_NAMES))


def test_session_id_is_carried_on_the_label_only_for_grouping():
    feats = [_f(10_000, 20_000)]
    execs = [_exec("c1", 0, 30)]
    labels = label_continuity("session_XYZ", feats, [], execs)
    assert labels[0].session_id == "session_XYZ"
    # and it must not be one of the model's feature columns (checked above);
    # here we only confirm the label object exposes it for grouped CV use
    label_dict = labels[0].to_dict()
    assert "session_id" in label_dict
