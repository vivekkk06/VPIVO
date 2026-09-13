import pytest

from procmine.segmentation.protected_boundary import (
    RULE_4_PROTECTED,
    STRATEGY_AGREEMENT,
    STRATEGY_COMBINED,
    STRATEGY_TEMPO,
    apply_protection,
)
from procmine.segmentation.reconstruction import (
    RULE_1_CHUNK_NOISE,
    RULE_3_CLUSTER_PROTECTION,
    RULE_4_CONTINUITY,
    RULE_NONE,
)


# --- Strategy A: agreement protection --------------------------------------

def test_agreement_protects_a_rule4_demotion_flagged_by_both():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
        flagged_by_both=[True], tempo_value=[None], strategy=STRATEGY_AGREEMENT,
    )
    assert result.final_boundary == [True]
    assert result.rule_applied == [RULE_4_PROTECTED]


def test_agreement_does_not_protect_when_not_flagged_by_both():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
        flagged_by_both=[False], tempo_value=[None], strategy=STRATEGY_AGREEMENT,
    )
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_4_CONTINUITY]


# --- Strategy B: tempo protection -------------------------------------------

def test_tempo_protects_above_threshold():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
        flagged_by_both=[False], tempo_value=[5000.0], strategy=STRATEGY_TEMPO,
        tempo_threshold=3000.0,
    )
    assert result.final_boundary == [True]
    assert result.rule_applied == [RULE_4_PROTECTED]


def test_tempo_does_not_protect_below_threshold():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
        flagged_by_both=[False], tempo_value=[1000.0], strategy=STRATEGY_TEMPO,
        tempo_threshold=3000.0,
    )
    assert result.final_boundary == [False]


def test_tempo_none_value_defaults_to_no_protection():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
        flagged_by_both=[False], tempo_value=[None], strategy=STRATEGY_TEMPO,
        tempo_threshold=3000.0,
    )
    assert result.final_boundary == [False]


def test_tempo_strategy_without_threshold_raises():
    with pytest.raises(ValueError):
        apply_protection(
            design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
            flagged_by_both=[False], tempo_value=[5000.0], strategy=STRATEGY_TEMPO,
        )


# --- Strategy C: combined protection ----------------------------------------

def test_combined_requires_both_conditions():
    args_common = dict(design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
                        strategy=STRATEGY_COMBINED, tempo_threshold=3000.0)
    only_agreement = apply_protection(flagged_by_both=[True], tempo_value=[1000.0], **args_common)
    only_tempo = apply_protection(flagged_by_both=[False], tempo_value=[5000.0], **args_common)
    both = apply_protection(flagged_by_both=[True], tempo_value=[5000.0], **args_common)
    assert only_agreement.final_boundary == [False]
    assert only_tempo.final_boundary == [False]
    assert both.final_boundary == [True]
    assert both.rule_applied == [RULE_4_PROTECTED]


def test_combined_strategy_without_threshold_raises():
    with pytest.raises(ValueError):
        apply_protection(
            design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
            flagged_by_both=[True], tempo_value=[5000.0], strategy=STRATEGY_COMBINED,
        )


# --- Protection scope: only Rule-4 demotions are eligible -------------------

def test_protection_never_applies_to_rule1_demotions():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_1_CHUNK_NOISE],
        flagged_by_both=[True], tempo_value=[999999.0], strategy=STRATEGY_COMBINED,
        tempo_threshold=0.0,
    )
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_1_CHUNK_NOISE]


def test_protection_never_touches_already_kept_candidates():
    # Rule 3 already kept this one -- protection must not re-process it
    result = apply_protection(
        design2_final_boundary=[True], design2_rule_applied=[RULE_3_CLUSTER_PROTECTION],
        flagged_by_both=[False], tempo_value=[None], strategy=STRATEGY_AGREEMENT,
    )
    assert result.final_boundary == [True]
    assert result.rule_applied == [RULE_3_CLUSTER_PROTECTION]


def test_protection_never_creates_a_boundary_that_was_never_a_candidate():
    # rule_applied == RULE_NONE means this transition was never a V1/V2
    # candidate at all -- even maximally favorable protection evidence
    # must not turn it into a boundary.
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_NONE],
        flagged_by_both=[True], tempo_value=[999999.0], strategy=STRATEGY_COMBINED,
        tempo_threshold=0.0,
    )
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_NONE]


# --- Protected candidate remains in the final boundary set ------------------

def test_protected_candidate_final_boundary_is_true():
    result = apply_protection(
        design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
        flagged_by_both=[True], tempo_value=[None], strategy=STRATEGY_AGREEMENT,
    )
    assert result.final_boundary[0] is True


# --- Determinism and mixed-array edge cases ---------------------------------

def test_deterministic_across_repeated_calls():
    args = dict(
        design2_final_boundary=[False, True, False, False],
        design2_rule_applied=[RULE_4_CONTINUITY, RULE_3_CLUSTER_PROTECTION, RULE_1_CHUNK_NOISE, RULE_4_CONTINUITY],
        flagged_by_both=[True, False, True, False],
        tempo_value=[5000.0, None, 5000.0, 100.0],
        strategy=STRATEGY_COMBINED, tempo_threshold=3000.0,
    )
    r1 = apply_protection(**args)
    r2 = apply_protection(**args)
    assert r1.final_boundary == r2.final_boundary
    assert r1.rule_applied == r2.rule_applied
    # index 0: rule4 demotion, both agree, tempo high -> protected
    assert r1.final_boundary == [True, True, False, False]


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        apply_protection(
            design2_final_boundary=[False, False], design2_rule_applied=[RULE_4_CONTINUITY],
            flagged_by_both=[True, True], tempo_value=[None, None], strategy=STRATEGY_AGREEMENT,
        )


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        apply_protection(
            design2_final_boundary=[False], design2_rule_applied=[RULE_4_CONTINUITY],
            flagged_by_both=[True], tempo_value=[None], strategy="not_a_real_strategy",
        )


def test_empty_arrays():
    result = apply_protection(
        design2_final_boundary=[], design2_rule_applied=[], flagged_by_both=[],
        tempo_value=[], strategy=STRATEGY_AGREEMENT,
    )
    assert result.final_boundary == []
    assert result.rule_applied == []
