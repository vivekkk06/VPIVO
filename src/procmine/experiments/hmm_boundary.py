"""Day-6 experiment: a Gaussian HMM over the existing per-transition feature
sequence, used as an *alternative* candidate-boundary detector.

This is an isolated experiment. It does not import, modify, or influence the
locked segmentation path (`reconstruction.py`, `protected_boundary.py`) and
nothing in the locked pipeline imports this module. It consumes the same
per-transition representation the locked V1 model consumes
(`segmentation.model.feature_vector`, 9 dimensions) so the comparison is
against the same information, not a different feature set.

Why an HMM at all: the locked detector scores each transition more or less
independently, while a business-process boundary is a sequential
phenomenon — whether a transition ends a unit of work depends on the
activity mode before and after it. An HMM makes that latent mode explicit:
hidden states stand for activity modes, and a *change of state* is a natural
candidate boundary. It is deliberately chosen over a neural sequence model
because Dataset A has only 63 sessions, which is far too little to learn
transferable boundary semantics for a Dataset B drawn from different
departments and applications.

Deliberate methodological choices:

* **Unsupervised, fitted per session.** The model never sees a ground-truth
  label, so there is no leakage to control for and no train/test split to
  argue about. GT is used only to score the output afterwards.
* **Hidden states are latent activity modes, not business processes.** The
  state count is swept rather than equated with the number of processes, and
  sensitivity across the sweep is reported instead of one favourable value.
* **Diagonal-covariance Gaussian emissions** with a variance floor. Several
  input features are boolean and can be constant within a session, which
  would otherwise drive the variance to zero and the likelihood to infinity.
* **Deterministic.** Initialisation is quantile-based with a fixed seed, so
  a rerun reproduces the same states and the same boundaries.

No new third-party dependency: this is plain numpy, which also keeps the
model auditable rather than hidden behind a library default.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

VARIANCE_FLOOR = 1e-3
LOG_ZERO = -1e30


def _log_sum_exp(a: np.ndarray, axis: int | None = None):
    """Numerically stable log-sum-exp. Returns a scalar when axis is None."""
    if axis is None:
        m = np.max(a)
        if not np.isfinite(m):
            m = 0.0
        return float(m + np.log(np.sum(np.exp(a - m))))
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    out = m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True))
    return np.squeeze(out, axis=axis)


@dataclass
class HmmFit:
    """A fitted model plus the decoded state path for one session."""

    n_states: int
    start_log: np.ndarray      # (K,)
    trans_log: np.ndarray      # (K, K)
    means: np.ndarray          # (K, D)
    variances: np.ndarray      # (K, D)
    states: np.ndarray         # (T,) Viterbi path
    log_likelihood: float
    n_iter: int
    converged: bool


def _init_params(x: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Quantile-based, deterministic initialisation.

    Seeding the means at evenly spaced quantiles of the data spreads the
    initial states across the observed range without the run-to-run variation
    a random init would introduce.
    """
    rng = np.random.default_rng(seed)
    qs = np.linspace(0.1, 0.9, k)
    means = np.stack([np.quantile(x, q, axis=0) for q in qs])
    # break exact ties (constant columns) so states are distinguishable
    means = means + rng.normal(0.0, 1e-6, size=means.shape)
    variances = np.maximum(np.var(x, axis=0, keepdims=True), VARIANCE_FLOOR)
    variances = np.repeat(variances, k, axis=0)
    return means, variances


def _log_emissions(x: np.ndarray, means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """(T, K) log N(x_t | mu_k, diag(var_k)) for a diagonal-covariance Gaussian."""
    var = np.maximum(variances, VARIANCE_FLOOR)
    # (T, K, D)
    diff = x[:, None, :] - means[None, :, :]
    quad = np.sum((diff ** 2) / var[None, :, :], axis=2)
    logdet = np.sum(np.log(var), axis=1)
    d = x.shape[1]
    return -0.5 * (quad + logdet[None, :] + d * np.log(2.0 * np.pi))


def fit_hmm(
    x: np.ndarray,
    n_states: int,
    *,
    max_iter: int = 30,
    tol: float = 1e-4,
    seed: int = 0,
) -> HmmFit:
    """Fit a diagonal-covariance Gaussian HMM by Baum-Welch and decode with
    Viterbi. Operates on standardised observations; the caller standardises."""
    t, d = x.shape
    k = int(n_states)
    means, variances = _init_params(x, k, seed)
    start_log = np.full(k, -np.log(k))
    trans_log = np.full((k, k), -np.log(k))

    prev_ll = -np.inf
    converged = False
    it = 0

    for it in range(1, max_iter + 1):
        log_b = _log_emissions(x, means, variances)  # (T, K)

        # --- forward ---
        log_alpha = np.empty((t, k))
        log_alpha[0] = start_log + log_b[0]
        for i in range(1, t):
            log_alpha[i] = log_b[i] + _log_sum_exp(
                log_alpha[i - 1][:, None] + trans_log, axis=0
            )
        ll = float(_log_sum_exp(log_alpha[-1]))

        # --- backward ---
        log_beta = np.zeros((t, k))
        for i in range(t - 2, -1, -1):
            log_beta[i] = _log_sum_exp(
                trans_log + log_b[i + 1][None, :] + log_beta[i + 1][None, :], axis=1
            )

        # --- posteriors ---
        log_gamma = log_alpha + log_beta
        log_gamma -= _log_sum_exp(log_gamma, axis=1)[:, None]
        gamma = np.exp(log_gamma)

        # --- expected transitions ---
        log_xi_acc = np.full((k, k), LOG_ZERO)
        for i in range(t - 1):
            m = (
                log_alpha[i][:, None]
                + trans_log
                + log_b[i + 1][None, :]
                + log_beta[i + 1][None, :]
            )
            m -= _log_sum_exp(m.reshape(-1))
            stacked = np.stack([log_xi_acc, m])
            log_xi_acc = _log_sum_exp(stacked, axis=0)

        # --- M step ---
        start_log = log_gamma[0] - _log_sum_exp(log_gamma[0])
        trans_log = log_xi_acc - _log_sum_exp(log_xi_acc, axis=1)[:, None]

        w = gamma.sum(axis=0) + 1e-12            # (K,)
        means = (gamma.T @ x) / w[:, None]
        diff = x[:, None, :] - means[None, :, :]
        variances = np.einsum("tk,tkd->kd", gamma, diff ** 2) / w[:, None]
        variances = np.maximum(variances, VARIANCE_FLOOR)

        if abs(ll - prev_ll) < tol * max(1.0, abs(prev_ll)):
            prev_ll = ll
            converged = True
            break
        prev_ll = ll

    # --- Viterbi ---
    log_b = _log_emissions(x, means, variances)
    delta = np.empty((t, k))
    psi = np.zeros((t, k), dtype=int)
    delta[0] = start_log + log_b[0]
    for i in range(1, t):
        scores = delta[i - 1][:, None] + trans_log
        psi[i] = np.argmax(scores, axis=0)
        delta[i] = log_b[i] + np.max(scores, axis=0)
    states = np.zeros(t, dtype=int)
    states[-1] = int(np.argmax(delta[-1]))
    for i in range(t - 2, -1, -1):
        states[i] = psi[i + 1, states[i + 1]]

    return HmmFit(
        n_states=k,
        start_log=start_log,
        trans_log=trans_log,
        means=means,
        variances=variances,
        states=states,
        log_likelihood=float(prev_ll),
        n_iter=it,
        converged=converged,
    )


def boundaries_from_states(states: np.ndarray) -> list[bool]:
    """A change of latent state is a candidate boundary.

    Returns a list aligned with the transition sequence, in the same
    `list[bool]` shape the locked evaluation already consumes, so
    `boundary_metrics` / `execution_metrics` can score it unchanged.

    Index 0 is never a boundary: the first transition has no preceding state
    to differ from, and the locked pipeline treats session start the same way.
    """
    if len(states) == 0:
        return []
    out = [False]
    for i in range(1, len(states)):
        out.append(bool(states[i] != states[i - 1]))
    return out


def standardize(x: np.ndarray) -> np.ndarray:
    """Zero-mean unit-variance per feature, with a floor for constant columns."""
    mu = x.mean(axis=0, keepdims=True)
    sd = x.std(axis=0, keepdims=True)
    sd = np.where(sd < 1e-8, 1.0, sd)
    return (x - mu) / sd
