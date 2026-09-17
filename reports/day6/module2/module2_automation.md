# Module 2 — Automation: pre-flight routing and post-action audit (H7, H8)

**No existing safety control was modified.** Route allowlist, note validation, the
mandatory human checkpoint, confirm-time re-verification, replay protection, audit
logging and redaction all remain exactly as Day 5 left them. Module 2 adds one gate
*before* the flow and one evidence step *after* it.

```
execution evidence
    ↓
VARIANT ROUTING            ← new, before anything runs
    ↓ eligible                        ↘ not eligible
prepare → human review → confirm       human route, no automation
    ↓
POST-ACTION EVIDENCE AUDIT ← new, after the action
```

---

## 3A · Pre-flight variant routing (H7)

### Signals — deterministic, no classifier

| Signal | Evidence |
|---|---|
| `applications` contains Microsoft Word | Present in **24/24** Word-detour executions, **0/94** dominant |
| `variant_signature` spans >1 system | All **4** rare-edge cases alternate HR ↔ another system |
| `routes_visited` ⊆ the 4 evidenced routes | The automation is only built for those |
| exactly 1 distinct route | Dominant path median 1, p75 1 |

Fitting a classifier to reproduce a rule this clean would add opacity and a training
dependency for no gain, so none was used.

### Results over the 122 canonical HR executions

| Outcome | n | Reason |
|---|---:|---|
| **Eligible** | **62** | `DOMINANT_PATH_MATCH` |
| Refused | 24 | `DETOUR_APPLICATION` |
| Refused | 14 | `NO_ROUTE_EVIDENCE` |
| Refused | 12 | `AMBIGUOUS_ROUTE_SET` |
| Refused | 6 | `UNKNOWN_ROUTE` |
| Refused | 4 | `MULTI_SYSTEM_VARIANT` |

**Observed dominant-path coverage = 62 / 122 = 0.5082.**

### The two numbers that must not be conflated

| Quantity | Value | Meaning |
|---|---:|---|
| Canonical dominant share | **0.7705** (94/122) | a descriptive forensic finding about observed behaviour |
| Routing-eligible coverage | **0.5082** (62/122) | what the conservative gate will actually admit |

**Neither is automation accuracy.** Nothing here is scored against a correct answer.

### Why the gate is stricter than the forensic label — the interesting result

32 executions the Day-3 forensics label *dominant path* are still refused:

| Reason | n | Why refusing is correct |
|---|---:|---|
| `NO_ROUTE_EVIDENCE` | 14 | no route was observed at all — there is nothing to verify |
| `AMBIGUOUS_ROUTE_SET` | 12 | 2–3 distinct routes; the automation was verified single-route |
| `UNKNOWN_ROUTE` | 6 | touched `#/resident-tax` or `#/dashboard`, outside the 4 evidenced routes |

This was not anticipated. "Belongs to the dominant variant" is a weaker claim than "is
safe to automate": the first describes observed behaviour, the second requires the
target surface to be evidenced. Where they disagree the gate takes the conservative
side. **The cost of that conservatism is 26 percentage points of coverage, and it is
worth stating plainly rather than hiding in a ratio.**

### Safety property — the gate's actual job

**Zero non-dominant executions were admitted.** All 24 Word-detour and all 4 rare-edge
executions were refused, each with a specific reason code. A gate that leaked even one
would have failed at the only thing it exists to do.

**H7: supported as a safety mechanism, at a measured coverage cost.**

---

## 3B · Post-action evidence audit (H8)

### Why it is different from pre-action safety

Every Day-5 control runs *before* the click and answers *"is it safe to act?"* None of
them can answer *"did the intended end state actually occur?"* — a question that only
exists afterwards.

### Checks — structural, not pixel-perfect

| Check | What it establishes |
|---|---|
| `expected_route_is_current` | the page did not move under us |
| `confirm_target_still_resolves_uniquely` | the target is still exactly one element |
| `note_field_still_present` | the field survived the action |
| `submitted_note_reads_back` | the submitted note is still there (length compared; content never logged) |
| `post_action_screenshot_captured` | SHA-256 recorded as verifiable evidence |

### Results

| Scenario | Outcome |
|---|---|
| Expected end state | **passed** — all checks PASS |
| Deliberately broken end state (route drifts to `#/onboarding` after confirm) | **detected** — `expected_route_is_current` FAIL |

### Deliberate non-features

- **No pixel-perfect assertion.** A UI that legitimately repaints would fail constantly,
  and a check that cries wolf gets switched off.
- **The pixel-difference ratio is defined but never asserted on.**
  `pixel_difference_ratio = changed_pixels / total_pixels`, reported as context only —
  no evidence supports any particular threshold constant for this UI.
- **`UNAVAILABLE` never counts as a pass.** Missing evidence is not good news.
- **No retry, no remediation.** A failed audit is reported, never acted on. Acting on an
  uncertain post-state is how a duplicate submission happens.
- **No claim of business success.** A screenshot showing the expected state is evidence
  the UI reached that state. It is **not proof the payroll record was written.**

**H8: supported, with its interpretive ceiling stated.**

---

## Module 1 vs Module 2 automation

| Dimension | Module 1 | Module 2 |
|---|---|---|
| Flow | prepare → review → confirm | **routing** → prepare → review → confirm → **audit** |
| Executions admitted | not gated by variant | 62/122 admitted, 60 routed to a human |
| Non-dominant admitted | not evaluated pre-flight | **0 of 28** |
| Post-action evidence | none | 5 structural checks + screenshot hash |
| Safety controls | 8 | same 8, **unchanged**, plus 2 layers |
| Manual work remaining | note authoring, review, approval | the same, **plus 60 routed executions** |

Module 2 does **not** automate more. It automates a smaller, better-evidenced subset
and produces evidence afterwards. **No claim of complete automation is made.**
