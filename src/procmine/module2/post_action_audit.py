"""Module 2 · Step 3B — post-action evidence audit (H8).

WHY THIS IS DIFFERENT FROM THE EXISTING PRE-ACTION SAFETY
---------------------------------------------------------
Day-5's controls all run **before** the click: validate the route, validate the note,
locate exactly one note field and one confirm button, hold a human checkpoint, then
re-verify the target immediately before clicking. Together they answer *"is it safe to
act?"*

None of them answers *"did the intended end state actually occur?"* — a question that
can only be asked afterwards. That is this module's only job, and it runs **after** the
existing flow, changing nothing inside it:

    prepare → human review → confirm → [ post-action audit ] → recorded evidence

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* **No pixel-perfect assertion.** A UI that legitimately repaints — a timestamp, a
  caret, antialiasing — would fail such a check constantly, and a check that cries wolf
  gets switched off. Evidence checks are structural.
* **No claim of business success.** A screenshot showing the expected state is evidence
  that the UI reached that state. It is not proof the payroll record was written. The
  audit records evidence; it does not certify an outcome.
* **No retry, no remediation.** A failed audit is reported, never acted on
  automatically. Acting on an uncertain post-state is how a duplicate submission
  happens.

The pixel-difference ratio is defined below but **not used as a pass/fail criterion**:

    pixel_difference_ratio = changed_pixels / total_pixels

For the local mock application the before/after screens differ only in a confirmation
banner, so a threshold on this ratio would encode an arbitrary constant with no
evidence behind it. It is computed only when two images are supplied, and reported as
context.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CHECK_PASS = "PASS"
CHECK_FAIL = "FAIL"
CHECK_UNAVAILABLE = "UNAVAILABLE"


@dataclass
class EvidenceCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class PostActionEvidence:
    execution_id: str | None
    route: str
    checks: list[EvidenceCheck] = field(default_factory=list)
    screenshot_sha256: str | None = None
    screenshot_path: str | None = None
    pixel_difference_ratio: float | None = None
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def passed(self) -> bool:
        """UNAVAILABLE never counts as a pass. Missing evidence is not good news."""
        return bool(self.checks) and all(c.status == CHECK_PASS for c in self.checks)

    @property
    def conclusive(self) -> bool:
        return all(c.status != CHECK_UNAVAILABLE for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id, "route": self.route,
            "checks": [c.to_dict() for c in self.checks],
            "passed": self.passed, "conclusive": self.conclusive,
            "screenshot_sha256": self.screenshot_sha256,
            "screenshot_path": self.screenshot_path,
            "pixel_difference_ratio": self.pixel_difference_ratio,
            "captured_at": self.captured_at,
            "interpretation_note": (
                "Evidence that the UI reached the expected state. NOT proof that the "
                "business record was written."
            ),
        }


def sha256_of(path: str | Path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pixel_difference_ratio(before: bytes, after: bytes) -> float | None:
    """changed_pixels / total_pixels over raw bytes of equal-length buffers.

    Byte-level rather than decoded-pixel-level so no image dependency is introduced.
    Returns None when the buffers differ in length, because the comparison would then
    be meaningless rather than merely imprecise. Reported as context, never asserted on.
    """
    if not before or not after or len(before) != len(after):
        return None
    changed = sum(1 for a, b in zip(before, after) if a != b)
    return round(changed / len(before), 6)


def audit_post_action(
    app,
    checkpoint,
    *,
    execution_id: str | None = None,
    screenshot_path: str | Path | None = None,
) -> PostActionEvidence:
    """Collect structural evidence that the intended end state was reached.

    `app` is any `HRApplication` adapter; `checkpoint` is the `ReviewCheckpoint` that
    was confirmed. Nothing here mutates the target — every call is a read.
    """
    evidence = PostActionEvidence(execution_id=execution_id, route=checkpoint.route)

    # 1. Still on the reviewed route.
    try:
        current = app.current_route
        evidence.checks.append(EvidenceCheck(
            "expected_route_is_current",
            CHECK_PASS if current == checkpoint.route else CHECK_FAIL,
            f"current route {current!r}, expected {checkpoint.route!r}"))
    except Exception as exc:  # noqa: BLE001 - an audit must never mask the outcome
        evidence.checks.append(EvidenceCheck(
            "expected_route_is_current", CHECK_UNAVAILABLE, f"could not read: {exc}"))

    # 2. The confirm target still resolves to exactly one element.
    try:
        buttons = app.find_confirm_button()
        matching = [b for b in buttons if b.element_id == checkpoint.confirm_button_id]
        ok = len(buttons) == 1 and len(matching) == 1
        evidence.checks.append(EvidenceCheck(
            "confirm_target_still_resolves_uniquely",
            CHECK_PASS if ok else CHECK_FAIL,
            f"found {[b.element_id for b in buttons]}, "
            f"expected exactly [{checkpoint.confirm_button_id!r}]"))
    except Exception as exc:  # noqa: BLE001
        evidence.checks.append(EvidenceCheck(
            "confirm_target_still_resolves_uniquely", CHECK_UNAVAILABLE,
            f"could not read: {exc}"))

    # 3. The note field still exists, and the submitted note is still readable there.
    #    Read-back is the strongest structural evidence available without asserting on
    #    business semantics the log never evidenced.
    try:
        fields = [f for f in app.find_note_field()
                  if f.element_id == checkpoint.note_field_id]
        if not fields:
            evidence.checks.append(EvidenceCheck(
                "note_field_still_present", CHECK_FAIL,
                f"{checkpoint.note_field_id!r} not found after the action"))
        else:
            evidence.checks.append(EvidenceCheck(
                "note_field_still_present", CHECK_PASS,
                f"{checkpoint.note_field_id!r} present"))
            value = getattr(fields[0], "value", None)
            if value is None:
                evidence.checks.append(EvidenceCheck(
                    "submitted_note_reads_back", CHECK_UNAVAILABLE,
                    "adapter does not expose a readable value"))
            else:
                evidence.checks.append(EvidenceCheck(
                    "submitted_note_reads_back",
                    CHECK_PASS if value == checkpoint.note_text else CHECK_FAIL,
                    # The note itself is never written into the evidence record.
                    f"read-back length {len(value)}, "
                    f"expected {len(checkpoint.note_text)}"))
    except Exception as exc:  # noqa: BLE001
        evidence.checks.append(EvidenceCheck(
            "note_field_still_present", CHECK_UNAVAILABLE, f"could not read: {exc}"))

    # 4. Screenshot, stored as a hash so the evidence is verifiable without retaining
    #    a potentially sensitive image in the audit record.
    if screenshot_path is not None:
        digest = sha256_of(screenshot_path)
        evidence.screenshot_path = str(screenshot_path)
        evidence.screenshot_sha256 = digest
        evidence.checks.append(EvidenceCheck(
            "post_action_screenshot_captured",
            CHECK_PASS if digest else CHECK_UNAVAILABLE,
            "captured and hashed" if digest else "no readable screenshot at that path"))

    return evidence
