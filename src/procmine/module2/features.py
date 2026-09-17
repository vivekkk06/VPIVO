"""Module 2 candidate features: operator-normalized timing and content drift.

WHY THESE TWO, AND WHY THEY ARE SEPARATE FROM MODULE 1
-----------------------------------------------------
Module 1's temporal feature is `log1p(delta_t)` — an absolute scale. If operators work
at materially different speeds, the same absolute pause means different things for
different people, and a single global threshold blurs that distinction (H1).

Module 1's only text signal is `extracted_text_at_transition`, a *presence* bit. It
says text was on screen; it says nothing about whether the screen content *changed*.
Two events can both carry text and be about completely different work (H2).

Both features are computed from raw event data only. **No ground truth is touched**:
no `process_code`, no `case_id`, no GT execution span, no GT boundary, no
`dwell_scale` (which lives in the GT manifest and is therefore off limits as a
feature, however tempting).

MEASURED FEASIBILITY (Dataset A, 162,705 transitions) — recorded here because it
governs how much either feature could possibly contribute:

* Operator identity is recoverable for 100% of sessions (8 operators, 63 sessions),
  but operator median gaps span only 52-56 ms (ratio 1.077). Dispersion varies more
  than location (MAD of log-gap 1.105-1.404, ~27%), which is why the formulation below
  is a MAD-scaled z-score rather than a simple ratio: if anything is going to differ
  between operators here, it is scale, not centre.
* Adjacent-event text pairs: 48 transitions (0.03%). Unusable — this was the first
  formulation tried and it is rejected on coverage, not on results.
* N=10 window text pairs: 18,779 transitions (11.54%), Jaccard median 0.0857,
  mean 0.3265, 16.6% fully disjoint. Usable, and the window form is also consistent
  with how the locked V2 model already consumes N=10 Jaccards.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

from procmine.segmentation.canonical import CanonicalEvent

_SESSION_RE = re.compile(r"^ses_\d{8}-\d{6}-(.+)$")
_WORD_RE = re.compile(r"\w+")

WINDOW_N = 10
#: Below this many observed gaps an operator baseline is not trusted and the documented
#: global-training fallback is used instead. Chosen so a baseline rests on a meaningful
#: sample; the smallest real operator in Dataset A contributes ~7,150 gaps, so this
#: floor never fires there and exists for robustness on future data.
MIN_GAPS_FOR_BASELINE = 200
#: MAD can legitimately be 0 for a degenerate operator; this floor keeps the z-score
#: finite rather than silently producing inf.
_MAD_FLOOR = 1e-6

# Feature-set identifiers used by the Module 2 experiment.
FEATURE_SET_M1 = "M1_compatible"
FEATURE_SET_M2A = "M2A_operator_timing"
FEATURE_SET_M2B = "M2B_content_drift"
FEATURE_SET_M2C = "M2C_operator_timing_plus_content_drift"

FEATURE_SETS = [FEATURE_SET_M1, FEATURE_SET_M2A, FEATURE_SET_M2B, FEATURE_SET_M2C]

_EXTRA_NAMES: dict[str, list[str]] = {
    FEATURE_SET_M1: [],
    FEATURE_SET_M2A: ["operator_z_log_gap"],
    FEATURE_SET_M2B: ["content_drift", "content_drift_available"],
    FEATURE_SET_M2C: ["operator_z_log_gap", "content_drift", "content_drift_available"],
}


def operator_of(session_id: str) -> str | None:
    """Operator identity from the session id suffix.

    Verified against `source.machine_id` in the raw events: both yield the same 8
    distinct values across the 63 Dataset-A sessions, so the cheap form is used.
    """
    m = _SESSION_RE.match(session_id or "")
    return m.group(1) if m else None


# --- H1: operator-normalized timing ---------------------------------------

@dataclass(frozen=True)
class OperatorBaseline:
    """Robust location and scale of one operator's log-gap distribution."""

    operator: str
    n_gaps: int
    median_log_gap: float
    mad_log_gap: float
    source: str  # "operator" | "global_fallback"

    def z(self, log_gap: float) -> float:
        return (log_gap - self.median_log_gap) / max(self.mad_log_gap, _MAD_FLOOR)


def _median_mad(values: list[float]) -> tuple[float, float]:
    med = statistics.median(values)
    return med, statistics.median([abs(v - med) for v in values])


def compute_operator_baselines(
    log_gaps_by_session: dict[str, list[float]], train_session_ids: list[str]
) -> dict[str, OperatorBaseline]:
    """Fit operator baselines on TRAINING SESSIONS ONLY.

    This is the leakage control that matters for H1. A baseline computed over all
    sessions would let the held-out session's own timing distribution shape the feature
    used to predict it — a subtle leak that would inflate the result without any
    obvious symptom. Callers must pass only the training fold's session ids.

    An operator with too few observed gaps in the training fold falls back to the
    pooled training baseline, and says so via `source`. No baseline is ever invented.
    """
    by_operator: dict[str, list[float]] = {}
    pooled: list[float] = []
    for sid in train_session_ids:
        gaps = log_gaps_by_session.get(sid) or []
        op = operator_of(sid)
        if op is not None:
            by_operator.setdefault(op, []).extend(gaps)
        pooled.extend(gaps)

    if not pooled:
        return {}
    g_med, g_mad = _median_mad(pooled)

    out: dict[str, OperatorBaseline] = {}
    for op, values in by_operator.items():
        if len(values) >= MIN_GAPS_FOR_BASELINE:
            med, mad = _median_mad(values)
            out[op] = OperatorBaseline(op, len(values), med, mad, "operator")
        else:
            out[op] = OperatorBaseline(op, len(values), g_med, g_mad, "global_fallback")
    out["__global__"] = OperatorBaseline("__global__", len(pooled), g_med, g_mad,
                                         "global_fallback")
    return out


def baseline_for(baselines: dict[str, OperatorBaseline], session_id: str) -> OperatorBaseline:
    """Never raises: an operator unseen in training uses the pooled training baseline."""
    op = operator_of(session_id)
    if op is not None and op in baselines:
        return baselines[op]
    return baselines["__global__"]


# --- H2: content drift -----------------------------------------------------

def event_text(event: CanonicalEvent) -> str | None:
    """Screen text for one event, or None.

    Reaches through `source_event.raw` rather than adding a field to `CanonicalEvent`,
    so no Module 1 file changes. `CanonicalEvent` already carries the boolean
    `has_extracted_text`; the raw text it was derived from lives in the original event.
    """
    ctx = event.source_event.raw.get("context") or {}
    extracted = ctx.get("extracted_text")
    if isinstance(extracted, dict):
        text = extracted.get("text")
        if isinstance(text, str) and text.strip():
            return text
    return None


def _tokens(events: list[CanonicalEvent]) -> frozenset:
    out: set[str] = set()
    for e in events:
        t = event_text(e)
        if t:
            out.update(w.lower() for w in _WORD_RE.findall(t))
    return frozenset(out)


def content_drift(
    canonical: list[CanonicalEvent], index_i: int, n: int = WINDOW_N
) -> tuple[float, bool]:
    """Token-level content drift across a transition, over N-event windows.

        J(A,B) = |A n B| / |A u B|
        D_content = 1 - J(A,B)

    Returns `(drift, available)`. `available` is False when either window contains no
    screen text at all — which is the majority of transitions. That case is reported
    honestly as "no evidence", never as drift 0 (identical) or drift 1 (disjoint);
    both would be fabricated evidence. The companion indicator feature lets a model
    learn to discount the imputed value rather than read it as a real measurement.

    Windows match the locked V2 convention: `index_i` is the transition's first event,
    the before-window ends at and includes it, the after-window starts at `index_i + 1`.
    """
    start = max(0, index_i - n + 1)
    before = _tokens(canonical[start: index_i + 1])
    end = min(len(canonical), index_i + 1 + n)
    after = _tokens(canonical[index_i + 1: end])

    if not before or not after:
        return 0.0, False
    union = before | after
    if not union:
        return 0.0, False
    return 1.0 - len(before & after) / len(union), True


# --- feature-set assembly --------------------------------------------------

def extra_feature_names(feature_set: str) -> list[str]:
    if feature_set not in _EXTRA_NAMES:
        raise ValueError(f"unknown feature set {feature_set!r}")
    return list(_EXTRA_NAMES[feature_set])


def extra_feature_values(
    feature_set: str, *, z_log_gap: float, drift: float, drift_available: bool
) -> list[float]:
    """The Module 2 columns appended to a locked Module 1 feature vector.

    Module 1's own columns are never altered or reordered — Module 2 only appends, so
    the comparison isolates the effect of the added evidence.
    """
    if feature_set == FEATURE_SET_M1:
        return []
    if feature_set == FEATURE_SET_M2A:
        return [z_log_gap]
    if feature_set == FEATURE_SET_M2B:
        return [drift, float(drift_available)]
    if feature_set == FEATURE_SET_M2C:
        return [z_log_gap, drift, float(drift_available)]
    raise ValueError(f"unknown feature set {feature_set!r}")


def log_gaps_for_session(feats) -> list[float]:
    """The log-gap sample an operator baseline is fitted on, taken from the locked
    `TransitionFeatures` so Module 1 and Module 2 measure the identical quantity."""
    return [f.log1p_delta_t_ms for f in feats]


def log1p_gap(delta_t_ms: int) -> float:
    return math.log1p(max(delta_t_ms, 0))
