#!/usr/bin/env python3
"""Day 6, Phase 5: does the HMM boundary signal carry information the locked
detector does not — and can an ensemble beat the locked baseline?

This is the honest way to reject (or accept) the ensemble. Rather than
asserting that a worse detector cannot help, it reproduces the locked
Combined predictions, fits the HMM, measures whether their errors are
actually complementary, and scores AND / OR ensembles with the locked
metric definitions.

Isolation and trust:
  * The locked modules are IMPORTED AND USED UNCHANGED. Nothing is modified.
  * The reproduction is VERIFIED against the Day-2 artifact before any
    ensemble conclusion is drawn — if pooled F1 does not match the locked
    0.3440 exactly, the script aborts rather than report a comparison built
    on a faulty reproduction.

Usage:
    python scripts/run_boundary_ensemble_experiment.py \
        --dataset dataset_a --out reports/day6 \
        --baseline reports/day2/protected_boundary_experiment_dataset_a.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.experiments.hmm_boundary import (  # noqa: E402
    boundaries_from_states, fit_hmm, standardize,
)
from procmine.segmentation.context_features import extract_trajectory_features  # noqa: E402
from procmine.segmentation.model import feature_vector  # noqa: E402
from procmine.segmentation.protected_boundary import (  # noqa: E402
    STRATEGY_COMBINED, apply_protection,
)
from procmine.segmentation.reconstruction import (  # noqa: E402
    apply_design2_rules, cluster_size_per_transition, compute_rule2_demotions,
    involves_duplicate_app_switch, union_candidates,
)

# Locked thresholds -- reused exactly, never re-selected.
TRAJECTORY_WINDOW_N = 10
SELECTED_RULE4_THRESHOLD = 0.40
SELECTED_TEMPO_THRESHOLD = 4680.2613
HMM_STATES = 2  # best-F1 state count from the Phase-2 sweep

# Reuse the locked experiment's own loaders rather than reimplementing them.
_spec = importlib.util.spec_from_file_location(
    "locked_experiment", ROOT / "scripts" / "run_protected_boundary_experiment.py"
)
locked = importlib.util.module_from_spec(_spec)
sys.modules["locked_experiment"] = locked
_spec.loader.exec_module(locked)


def combined_predictions(per_session: dict, session_ids: list[str], loso: dict) -> dict:
    """Reproduce the locked Combined boundary set using the locked modules."""
    preds = {}
    for sid in session_ids:
        d = per_session[sid]
        feats, canonical = d["feats"], d["canonical"]
        n = len(feats)
        v1_pred, v2_pred = loso["v1_preds"][sid], loso["v2_preds"][sid]

        candidates = union_candidates(v1_pred.tolist(), v2_pred.tolist())
        chunk_boundary = [f.chunk_boundary for f in feats]
        duplicate_noise = [
            involves_duplicate_app_switch(
                f.event_i_id, f.event_next_id, d["duplicate_app_switch_ids"]
            )
            for f in feats
        ]
        cluster_size = cluster_size_per_transition(candidates)
        candidate_indices = [i for i, c in enumerate(candidates) if c]
        rule2_demote, _ = compute_rule2_demotions(
            canonical, candidate_indices, TRAJECTORY_WINDOW_N
        )

        jac: list[float | None] = [None] * n
        tempo: list[float | None] = [None] * n
        for i in candidate_indices:
            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            jac[i] = traj.event_type_jaccard
            tempo[i] = float(traj.after_window_duration_ms)

        design2 = apply_design2_rules(
            candidates=candidates, chunk_boundary=chunk_boundary,
            duplicate_noise=duplicate_noise, rule2_demote_indices=rule2_demote,
            cluster_size=cluster_size, event_type_jaccard=jac,
            continuity_threshold=SELECTED_RULE4_THRESHOLD,
        )
        flagged_by_both = [bool(v1_pred[i]) and bool(v2_pred[i]) for i in range(n)]
        r = apply_protection(
            design2_final_boundary=design2.final_boundary,
            design2_rule_applied=design2.rule_applied,
            flagged_by_both=flagged_by_both, tempo_value=tempo,
            strategy=STRATEGY_COMBINED, tempo_threshold=SELECTED_TEMPO_THRESHOLD,
        )
        preds[sid] = list(r.final_boundary)
    return preds


def complementarity(per_session: dict, base: dict, hmm: dict) -> dict:
    """Do the two detectors make *different* mistakes? Only if they do can an
    ensemble help."""
    both_tp = base_only_tp = hmm_only_tp = neither = 0
    base_fn_caught_by_hmm = 0
    n_gt = 0
    for sid, d in per_session.items():
        lt = d["is_boundary_labels"]
        b, h = base[sid], hmm[sid]
        for i, l in enumerate(lt):
            if not l.is_boundary:
                continue
            n_gt += 1
            bi, hi = bool(b[i]), bool(h[i])
            if bi and hi:
                both_tp += 1
            elif bi:
                base_only_tp += 1
            elif hi:
                hmm_only_tp += 1
                base_fn_caught_by_hmm += 1
            else:
                neither += 1
    return {
        "n_gt_boundaries": n_gt,
        "caught_by_both": both_tp,
        "caught_by_baseline_only": base_only_tp,
        "caught_by_hmm_only": hmm_only_tp,
        "missed_by_both": neither,
        "baseline_misses_recovered_by_hmm": base_fn_caught_by_hmm,
        "note": "'caught_by_hmm_only' is the only cell an ensemble could add. It must be "
                "weighed against the false positives the HMM brings with it.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print("Loading Dataset A (locked loader) ...", file=sys.stderr)
    per_session = locked.load_dataset(args.dataset)
    session_ids = sorted(per_session.keys())
    print(f"  {len(session_ids)} sessions", file=sys.stderr)

    print("Reproducing locked V1/V2 LOSO ...", file=sys.stderr)
    loso = locked.run_loso(per_session, session_ids)
    base = combined_predictions(per_session, session_ids, loso)

    # --- verify the reproduction before trusting anything built on it ---
    base_eval = locked.evaluate_boundary_set(per_session, session_ids, base)
    artifact = json.loads(args.baseline.read_text(encoding="utf-8"))
    locked_pooled = artifact["systems"]["Strategy_Combined"]["pooled"]
    drift = {
        k: abs(base_eval["pooled"][k] - locked_pooled[k])
        for k in ("precision", "recall", "f1")
    }
    ok = all(v < 1e-9 for v in drift.values())
    print(f"  reproduction check: F1={base_eval['pooled']['f1']:.6f} "
          f"vs locked {locked_pooled['f1']:.6f} -> {'MATCH' if ok else 'MISMATCH'}",
          file=sys.stderr)
    if not ok:
        raise SystemExit(f"ABORT: baseline reproduction drifted: {drift}")

    print(f"Fitting HMM (K={HMM_STATES}) ...", file=sys.stderr)
    hmm = {}
    for sid in session_ids:
        x = np.array(
            [feature_vector(f) for f in per_session[sid]["feats"]], dtype=float
        )
        fit = fit_hmm(standardize(x), HMM_STATES, seed=args.seed)
        hmm[sid] = boundaries_from_states(fit.states)

    comp = complementarity(per_session, base, hmm)

    and_preds = {
        sid: [bool(a) and bool(b) for a, b in zip(base[sid], hmm[sid])]
        for sid in session_ids
    }
    or_preds = {
        sid: [bool(a) or bool(b) for a, b in zip(base[sid], hmm[sid])]
        for sid in session_ids
    }

    systems = {
        "locked_combined_reproduced": base_eval,
        "hmm_only": locked.evaluate_boundary_set(per_session, session_ids, hmm),
        "ensemble_AND_both_must_agree": locked.evaluate_boundary_set(
            per_session, session_ids, and_preds
        ),
        "ensemble_OR_either_flags": locked.evaluate_boundary_set(
            per_session, session_ids, or_preds
        ),
    }

    out = {
        "experiment": "Day-6 Phase 5 — HMM/baseline complementarity and ensemble test",
        "isolation_note": "Locked modules imported and used unchanged; the reproduction is "
                          "verified against the Day-2 artifact before any conclusion.",
        "hmm_states": HMM_STATES,
        "seed": args.seed,
        "reproduction_check": {
            "locked_pooled": locked_pooled,
            "reproduced_pooled": base_eval["pooled"],
            "max_abs_drift": max(drift.values()),
            "verified": ok,
        },
        "complementarity": comp,
        "systems": {k: v["pooled"] for k, v in systems.items()},
        "per_session": {k: v.get("per_session") for k, v in systems.items()},
    }
    path = args.out / "boundary_ensemble_experiment_dataset_a.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    print("\n  system                          P        R        F1", file=sys.stderr)
    for name, ev in systems.items():
        p = ev["pooled"]
        print(f"  {name:30s} {p['precision']:.4f}  {p['recall']:.4f}  {p['f1']:.4f}",
              file=sys.stderr)
    print(f"\n  complementarity: {comp['caught_by_hmm_only']} of {comp['n_gt_boundaries']} "
          f"GT boundaries caught by HMM only", file=sys.stderr)
    print(f"Wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
