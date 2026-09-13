"""Stage 8.4: small, reusable primitives for the Rule-4 error forensics
investigation (`scripts/analyze_rule4_errors.py`).

Diagnostic only — no reconstruction rule is defined or changed here.
`hostname_only` mirrors `context_features._hostname_only`'s exact logic
(host, port stripped) rather than importing that module-private helper
across module boundaries; `port_only` is the natural complement, needed
here because Stage 8.4 explicitly asks whether the 296 Rule-4 mistakes
are disproportionately "same host, different port" — a distinction
Stage 5's host-vs-port experiment did not separately test.
"""

from __future__ import annotations

from urllib.parse import urlparse


def hostname_only(url: str | None) -> str | None:
    """Same logic as `context_features._hostname_only`: hostname with
    port and scheme stripped, or None if absent/unparseable."""
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def port_only(url: str | None) -> int | None:
    """The port component of a browser URL, or None if absent,
    unparseable, or not specified (e.g. default-port URLs carry no
    explicit port)."""
    if not url:
        return None
    try:
        return urlparse(url).port
    except ValueError:
        return None


def classify_candidate_source(v1_flagged: bool, v2_flagged: bool) -> str:
    """Which model(s) originally placed this transition in the candidate
    set C = V1 UNION V2 -- purely descriptive, not a reconstruction
    input."""
    if v1_flagged and v2_flagged:
        return "both"
    if v1_flagged:
        return "v1_only"
    if v2_flagged:
        return "v2_only"
    return "neither"
