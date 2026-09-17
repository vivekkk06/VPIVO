"""Module 2 · Step 3A — pre-flight variant routing (H7).

WHERE THIS SITS
---------------
    execution evidence
        ↓
    VARIANT ROUTING          <-- this module, BEFORE any automation runs
        ↓ eligible                    ↘ not eligible
    prepare → human review → confirm   human route, no automation

It runs **before** the Day-5 automation, and changes nothing inside it. Every existing
safety control — route allowlist, note validation, human checkpoint, confirm-time
re-verification, replay protection — still applies to whatever this layer admits. This
is an additional gate, never a replacement for one.

WHY IT IS DETERMINISTIC AND NOT A CLASSIFIER
--------------------------------------------
The discriminating evidence is already established by the Day-3 forensics and needs no
model:

* **Microsoft Word separates the detour perfectly.** Word appears in 24 of 24
  Word-detour executions and in 0 of 94 dominant-path executions.
* **Multi-system alternation marks the rare edge cases.** All 4 show a
  `variant_signature` alternating between HR and another system (Financial Accounting,
  Windows Explorer).

Fitting a classifier to reproduce a rule this clean would add opacity and a training
dependency for no gain.

THE GATE IS DELIBERATELY STRICTER THAN THE FORENSIC LABEL
----------------------------------------------------------
A measured consequence, stated up front because it is the interesting part: some
executions the Day-3 forensics label "dominant path" would still be **refused** here.

* 14 of the 94 dominant executions visited **no route at all** — nothing to verify.
* Dominant executions also touched `#/resident-tax` (4 visits) and `#/dashboard` (2),
  neither of which is in the four evidenced routes the automation supports.

Refusing those is correct. "Belongs to the dominant variant" is a descriptive finding
about observed behaviour; "is safe to automate" is a stronger claim requiring the
target surface to be evidenced. Where the two disagree, this layer takes the
conservative side and sends the execution to a human.

Consequently **`routing-eligible coverage` is a different, lower number than the
canonical 77.05% dominant share, and the two must never be reported as the same
quantity.** Neither is "automation accuracy"; both are observed coverage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES

DECISION_AUTOMATE = "AUTOMATE"
DECISION_HUMAN = "HUMAN"

REASON_DOMINANT_PATH_MATCH = "DOMINANT_PATH_MATCH"
REASON_UNKNOWN_ROUTE = "UNKNOWN_ROUTE"
REASON_DETOUR_APPLICATION = "DETOUR_APPLICATION"
REASON_MULTI_SYSTEM_VARIANT = "MULTI_SYSTEM_VARIANT"
REASON_NO_ROUTE_EVIDENCE = "NO_ROUTE_EVIDENCE"
REASON_AMBIGUOUS_ROUTE_SET = "AMBIGUOUS_ROUTE_SET"

#: The only application evidenced on the dominant path (Microsoft Edge on 94/94).
#: Notepad appears once and is tolerated as incidental rather than treated as a marker.
DOMINANT_APPLICATIONS = frozenset({"Microsoft Edge"})
INCIDENTAL_APPLICATIONS = frozenset({"Notepad"})
#: Present in 24/24 Word-detour executions and 0/94 dominant ones.
DETOUR_MARKER_APPLICATIONS = frozenset({"Microsoft Word"})

#: Above this many distinct evidenced routes an execution stops looking like the
#: single-route dominant path (median 1, p75 1 across the 94).
MAX_ROUTES_FOR_DOMINANT = 1

HR_SYSTEM = "system:HR人事給与システム"


@dataclass(frozen=True)
class RoutingDecision:
    decision: str
    reason_code: str
    rationale: str
    signals_used: dict = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return self.decision == DECISION_AUTOMATE

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reason_code": self.reason_code,
                "rationale": self.rationale, "eligible": self.eligible,
                "signals_used": dict(self.signals_used)}


def _human(reason: str, rationale: str, signals: dict) -> RoutingDecision:
    return RoutingDecision(DECISION_HUMAN, reason, rationale, signals)


def route_execution(
    *,
    routes_visited: list[str] | None = None,
    applications: list[str] | None = None,
    variant_signature: list[str] | None = None,
) -> RoutingDecision:
    """Decide whether one execution may enter the automation at all.

    Every branch that is not a positive, evidenced match returns `HUMAN`. There is no
    "probably fine" path: insufficient evidence is a refusal, not a default-allow.
    """
    routes = list(routes_visited or [])
    apps = list(applications or [])
    signature = list(variant_signature or [])
    distinct_routes = sorted(set(routes))
    signals = {
        "distinct_routes": distinct_routes,
        "applications": sorted(set(apps)),
        "n_systems_in_signature": len({s for s in signature}) if signature else None,
    }

    # 1. A detour marker is decisive on its own: Word never appears on the dominant path.
    detour = sorted(set(apps) & DETOUR_MARKER_APPLICATIONS)
    if detour:
        return _human(REASON_DETOUR_APPLICATION,
                      f"detour application present ({', '.join(detour)}); the dominant "
                      f"path was never observed using it",
                      signals)

    # 2. Alternation across systems is the rare-edge signature.
    systems = {s for s in signature if s.startswith(("system:", "app:"))}
    if len(systems) > 1:
        return _human(REASON_MULTI_SYSTEM_VARIANT,
                      f"execution alternates across {len(systems)} systems; the dominant "
                      f"path stays within {HR_SYSTEM}",
                      signals)

    # 3. No observed route means there is nothing to verify against the allowlist.
    if not distinct_routes:
        return _human(REASON_NO_ROUTE_EVIDENCE,
                      "no route was observed for this execution, so the automation "
                      "surface cannot be confirmed",
                      signals)

    # 4. Every observed route must be one of the four evidenced ones. This refuses
    #    #/resident-tax and #/dashboard even though they occur on the dominant path,
    #    because the automation has no evidenced handling for them.
    unknown = [r for r in distinct_routes if r not in KNOWN_ROUTE_PREFIXES]
    if unknown:
        return _human(REASON_UNKNOWN_ROUTE,
                      f"route(s) outside the evidenced set: {', '.join(unknown)}",
                      signals)

    # 5. The dominant path is single-route. More than one evidenced route is still a
    #    real pattern, but not the one the automation was built and verified against.
    if len(distinct_routes) > MAX_ROUTES_FOR_DOMINANT:
        return _human(REASON_AMBIGUOUS_ROUTE_SET,
                      f"{len(distinct_routes)} distinct routes visited; the dominant "
                      f"path was verified as single-route",
                      signals)

    # 6. Any application outside the evidenced set (ignoring known-incidental ones).
    unexpected = sorted(set(apps) - DOMINANT_APPLICATIONS - INCIDENTAL_APPLICATIONS)
    if unexpected:
        return _human(REASON_UNKNOWN_ROUTE,
                      f"unexpected application(s) for the dominant path: "
                      f"{', '.join(unexpected)}",
                      signals)

    return RoutingDecision(
        DECISION_AUTOMATE, REASON_DOMINANT_PATH_MATCH,
        f"single evidenced route {distinct_routes[0]} with no detour marker",
        signals)


def coverage(decisions: list[RoutingDecision]) -> dict:
    """Observed dominant-path coverage.

    **Not** automation accuracy: nothing here is scored against a correct answer. It
    reports what fraction of observed executions the gate would admit.
    """
    total = len(decisions)
    eligible = sum(1 for d in decisions if d.eligible)
    reasons: dict[str, int] = {}
    for d in decisions:
        reasons[d.reason_code] = reasons.get(d.reason_code, 0) + 1
    return {
        "total_executions": total,
        "routing_eligible": eligible,
        "observed_dominant_path_coverage": round(eligible / total, 4) if total else None,
        "refused": total - eligible,
        "reason_counts": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "metric_naming_note": (
            "This is observed dominant-path coverage, not automation accuracy. No "
            "prediction is scored against a ground-truth label anywhere in this metric."
        ),
    }
