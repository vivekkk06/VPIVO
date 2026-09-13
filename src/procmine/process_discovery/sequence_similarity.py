"""Problem 2 investigation: sequence similarity measures for variant
discovery.

Three methods, per instruction (test then select rather than assume
one is right): normalized Levenshtein (edit) distance, LCS-based
similarity, and Jaccard similarity on the SET of distinct tokens in
each trace (order-insensitive -- a cheap complement to the two
order-sensitive measures). All three are pure functions over tuples of
opaque, hashable tokens -- independent of any one trace-abstraction
level, so the same functions run against both `system_level_trace` and
`activity_level_trace` output.

Complexity, stated explicitly per instruction: both edit distance and
LCS are O(len(a) * len(b)) per pair, so comparing N traces pairwise is
O(N^2 * L^2) in the worst case. For Dataset B's HR/Payroll population
(122 traces, each at most ~10 tokens long at ACTIVITY_LEVEL) this is
trivially fast (see the reproducibility timing in the analysis
script); it would NOT be appropriate to pairwise-compare raw event
streams (hundreds of events each) or a much larger trace population
without pre-grouping, n-gram signatures, or MinHash/LSH first --
noted as a scaling option, not implemented, since Dataset B doesn't
need it.
"""

from __future__ import annotations


def levenshtein_distance(a: tuple, b: tuple) -> int:
    """Standard edit distance over sequences of arbitrary hashable
    tokens (not limited to characters) -- O(len(a) * len(b)) time and
    O(min(len(a), len(b))) space via the rolling-row formulation."""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    if n > m:
        a, b, n, m = b, a, m, n  # keep the rolling row as the shorter side
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[m]


def normalized_levenshtein_similarity(a: tuple, b: tuple) -> float:
    """1 - edit_distance / max(len(a), len(b)), in [0, 1]. Two empty
    traces are defined as identical (1.0), not undefined -- there is
    nothing to disagree about."""
    if not a and not b:
        return 1.0
    dist = levenshtein_distance(a, b)
    return 1.0 - dist / max(len(a), len(b))


def lcs_length(a: tuple, b: tuple) -> int:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


def lcs_similarity(a: tuple, b: tuple) -> float:
    """2 * LCS(a, b) / (len(a) + len(b)) -- a Dice-coefficient-style
    ratio over subsequence length, in [0, 1]. Two empty traces are
    defined as identical (1.0); one empty and one non-empty trace has
    zero shared subsequence (0.0)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 2 * lcs_length(a, b) / (len(a) + len(b))


def jaccard_similarity(a: tuple, b: tuple) -> float | None:
    """Order-INsensitive: the Jaccard index over the SETS of distinct
    tokens in each trace -- deliberately ignores sequence/repetition,
    unlike the two measures above, so it is reported as a complement to
    them, not a replacement. `None` (not 0.0) when both sets are empty
    -- no evidence either way, mirroring this project's established
    convention for an empty-vs-empty comparison elsewhere
    (`context_features._jaccard`)."""
    set_a, set_b = set(a), set(b)
    union = set_a | set_b
    if not union:
        return None
    return len(set_a & set_b) / len(union)
