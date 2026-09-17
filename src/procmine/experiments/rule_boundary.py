"""Day-7 segmentation-improvement candidates: small, auditable boundary rules.

Why rules first: the locked architecture is a union of two learned models plus a
four-rule reconstruction layer plus a protection layer. That is a lot of machinery
for F1 0.3440. Before reaching for anything more sophisticated, the honest question
is whether a handful of explicit, inspectable conditions do as well — because if
they do, the extra machinery is not earning its complexity.

Nothing here imports `procmine.segmentation`. The locked pipeline is untouched; a
test asserts that isolation by parsing this module's AST.

Every predictor is a pure function from precomputed per-session arrays to a boolean
list, so a parameter sweep can be scored without recomputing features.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionArrays:
    """Everything a rule candidate needs about one session, precomputed once.

    Kept deliberately small: a rule that needs more evidence than this is no longer
    a cheap, auditable rule and belongs in a different experiment.
    """

    session_id: str
    delta_t_ms: tuple[int, ...]
    application_changed: tuple[bool, ...]
    browser_domain_changed: tuple[bool, ...]
    window_title_changed: tuple[bool, ...]
    interaction_category_changed: tuple[bool, ...]
    chunk_boundary: tuple[bool, ...]
    # app-pair identity per transition, used by the motif candidate
    app_pair: tuple[tuple[str | None, str | None], ...]
    # browser-domain coverage for the session (instrumentation health input)
    browser_domain_coverage: float

    def __len__(self) -> int:
        return len(self.delta_t_ms)


def context_changed(a: SessionArrays, i: int) -> bool:
    """A context change is an application change or a browser-domain change.

    `window_title_changed` is deliberately excluded: Day-1 measured its boundary
    lift at 0.048 and Day-4 re-tested it as a fallback at lift 1.10 with alignment
    at or below chance. It is the single most tempting signal here and the evidence
    says it does not work.
    """
    return a.application_changed[i] or a.browser_domain_changed[i]


def predict_rule(
    a: SessionArrays, *, small_gap_ms: float, large_gap_ms: float
) -> list[bool]:
    """C1 — the deterministic two-threshold rule.

    A boundary is predicted when either:
      * the context changed AND the pause was longer than `small_gap_ms`, or
      * the pause was longer than `large_gap_ms`, whatever the context.

    Index 0 is still a transition (between event 0 and 1) and is scored like any
    other; the locked evaluator makes no special case for it, so neither do we.
    """
    out = []
    for i in range(len(a)):
        gap = a.delta_t_ms[i]
        out.append(
            (context_changed(a, i) and gap > small_gap_ms) or (gap > large_gap_ms)
        )
    return out


def predict_rule_with_continuity_veto(
    a: SessionArrays,
    *,
    small_gap_ms: float,
    large_gap_ms: float,
    jaccard: list[float | None],
    veto_above: float,
) -> list[bool]:
    """C2 — C1, then demote boundaries that sit inside a continuing sequence.

    Demote-only, the same discipline Day-2's reconstruction layer used: the veto can
    remove a predicted boundary but never invent one. `jaccard` is the N=10
    event-type trajectory similarity around each transition; a high value means the
    activity after the transition looks like the activity before it.
    """
    base = predict_rule(a, small_gap_ms=small_gap_ms, large_gap_ms=large_gap_ms)
    out = []
    for i, flagged in enumerate(base):
        j = jaccard[i]
        if flagged and j is not None and j >= veto_above:
            out.append(False)
        else:
            out.append(flagged)
    return out


def predict_rule_with_motif(
    a: SessionArrays,
    *,
    small_gap_ms: float,
    large_gap_ms: float,
    common_pairs: frozenset,
) -> list[bool]:
    """C3 — process-aware: require the context change to be an *unfamiliar* one.

    `common_pairs` is the set of (app_from, app_to) transitions seen frequently in
    the TRAINING sessions only. The idea is that a frequently-repeated app hop is a
    motif inside a process (e.g. HR -> Word -> HR), while a rare hop is more likely
    to be a genuine change of work.

    This is deliberately not the Day-3 process labels: using those would be
    circular, because they are themselves derived from segmentation. Only raw
    app-pair frequency is used, and it is fitted per fold.
    """
    out = []
    for i in range(len(a)):
        gap = a.delta_t_ms[i]
        ctx = context_changed(a, i)
        if ctx and a.app_pair[i] in common_pairs:
            ctx = False  # a familiar hop is treated as continuation, not a boundary
        out.append((ctx and gap > small_gap_ms) or (gap > large_gap_ms))
    return out


def predict_rule_instrumentation_aware(
    a: SessionArrays,
    *,
    small_gap_ms: float,
    large_gap_ms: float,
    degraded_small_gap_ms: float,
    degraded_large_gap_ms: float,
    coverage_floor: float,
) -> list[bool]:
    """C4 — use a different threshold pair where the context signal is unobservable.

    Day 4 established that some sessions carry almost no browser-domain evidence. In
    those sessions `context_changed` is structurally weaker, so the rule leans on
    the gap alone. This tests whether acknowledging that explicitly helps.

    Note this does NOT exclude degraded sessions from evaluation — it still segments
    them, which is the only honest way to measure the idea.
    """
    degraded = a.browser_domain_coverage < coverage_floor
    small = degraded_small_gap_ms if degraded else small_gap_ms
    large = degraded_large_gap_ms if degraded else large_gap_ms
    return predict_rule(a, small_gap_ms=small, large_gap_ms=large)


def confusion(preds: list[bool], labels: list[bool]) -> tuple[int, int, int]:
    """(tp, fp, fn) for one session — the unit a pooled sweep sums over."""
    tp = fp = fn = 0
    for p, y in zip(preds, labels):
        if p and y:
            tp += 1
        elif p and not y:
            fp += 1
        elif y and not p:
            fn += 1
    return tp, fp, fn


def f1_from_counts(tp: int, fp: int, fn: int) -> float:
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)
