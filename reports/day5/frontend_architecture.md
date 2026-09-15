# Day-5 Frontend Architecture

**Status:** data bridge implemented and tested. No frontend code exists yet.

Working hypothesis for Day 5: *an interactive deterministic replay and
process-exploration layer can improve observability and explainability of
the existing operation-log analysis without changing the underlying
segmentation, instrumentation-health, process-ranking, or automation
decisions.*

The architecture below exists to make that testable — specifically, to make
it **structurally impossible** for the dashboard to drift from the analysis
it visualises.

---

## Data flow

```
Days 1-4 artifacts (reports/day1..day4/)          [READ-ONLY]
    |
    |  scripts/build_frontend_data.py             [no analytical logic]
    v
frontend/public/data/*.json                       [generated, gitignored]
    |
    v
React dashboard
    |
    +-- Dashboard          static
    +-- Session Replay     static (lazy per-session)
    +-- Process Explorer   static
    +-- Opportunities      static
    +-- HR Automation Demo ---> small local Python API  [only stateful piece]
```

Eleven of the fourteen surveyed features are served by static JSON. The
only component needing a backend is the HR automation demo, because its
safety model is stateful (see below).

## The rule this architecture enforces

**The frontend must never reimplement analytical logic.** It must not
compute segmentation, execution boundaries, instrumentation-health
thresholds, impact/feasibility/opportunity scores, variant entropy, or
directly-follows edges. Those are owned by `src/procmine/` and already
materialised on disk.

The bridge enforces this by construction: `build_frontend_data.py` only
reads, selects, renames, joins, splits and writes. Its docstring states
that if a formula ever appears in the file, the change is wrong. Every
derived field (six in total) is a count, a dict lookup, or a key lifted
from a mapping, and each is enumerated in `data_contract.md`.

## Canonical-source decisions, and why

Three ranking artifacts exist in `reports/day3/` with **different values
for the same processes**. This is the single largest correctness hazard in
the Day-5 work.

| Artifact | HR Opportunity | Status |
|---|---:|---|
| `automation_priority_dataset_b.json` | n/a (8-factor `score`) | superseded by the Impact/Feasibility split |
| `problem2_process_metrics.json` | 0.4186 | **pre-entropy-fix — buggy** |
| `problem2_process_mining_full_results.json` | 0.4186 | **pre-entropy-fix — buggy** |
| `problem2_audit_results.json` | **0.4401** | **CANONICAL** |

Day 3's own audit found and fixed a real mathematical error: cross-process
variant entropy was unnormalised, so processes with more variants got a
higher ceiling and were not comparable. The fix moved HR's Feasibility
0.4532 → 0.4765 and Opportunity 0.4186 → 0.4401.

A dashboard reading the wrong file would display numbers the work log
explicitly records as a fixed bug. Two tests guard this: the HR row must
equal the audit artifact exactly, and `0.4186` must appear nowhere in the
bundle. `problem2_process_mining_full_results.json` is still read, but
**only** for `hr_payroll_dfg` and the similarity investigation, which the
audit file does not contain.

Remaining canonical choices:

| Concern | Canonical source |
|---|---|
| Dataset-A segmentation quality | `day2/protected_boundary_experiment_dataset_a.json` |
| Dataset-B executions | `day3/process_executions_dataset_b.json` |
| Process profiles | `day3/process_profiles_dataset_b.json` |
| Variants | `day3/process_variants_dataset_b.json` |
| HR DFG / similarity | `day3/problem2_process_mining_full_results.json` |
| Opportunity ranking | `day3/problem2_audit_results.json` |
| HR dominant-path evidence | `day3/hr_payroll_dominant_path_dataset_b.json` |
| Instrumentation health | `day4/instrumentation_health_dataset_{a,b}.json` |

Where a value exists in both a `.md` report and a `.json` artifact, the
**JSON is canonical** — the prose is narrative, the JSON is generated.

## Loading strategy

Measured from a real build: the full bundle is 4.9 MB, of which **4.4 MB
is execution `ordered_steps`**.

- **Eager (465 KB total):** `meta`, `sessions`, `executions-index`,
  `processes`, `variants`, `opportunities`, `instrumentation`,
  `hr-payroll`, `dataset-a-metrics`. Load all of these at startup — this
  is small enough that splitting it would be premature optimisation.
- **Lazy:** `executions/<session_id>.json`, fetched only when a session is
  selected for replay (~300 KB each, 15 files).

`executions-index.json` (284 KB, all 645 executions minus `ordered_steps`)
backs every list, filter and timeline view without touching the lazy
files at all.

## Day-5 V1 scope decisions

**Dataset B only for replay.** Dataset A appears on the Dashboard as
aggregate quality metrics (F1 0.3440, precision 0.2358, recall 0.6355,
79.05% fragmented, under-segmentation 0.1412, over-segmentation 1.603) and
as instrumentation health. It gets **no replay view**, because the locked
Day-2 pipeline never serialises its predicted boundaries — only pooled and
per-session metrics. Building that capability would mean adding an export
path through the locked segmentation architecture, which is risk the
dashboard does not justify.

**"Execution Step Replay", not "Event Replay".** The finest persisted
granularity is `ordered_steps` (system, interaction category, event count,
start/end, dominant event types). Individual raw events live only in the
gitignored 2.8 GB dataset directories. Naming the feature honestly keeps
the UI from implying a fidelity the data does not have.

**Process count.** `processes.json` carries 29 rows: 21 ranked candidates
plus 8 marked `excluded_from_ranking`. The "21 processes" headline is the
ranked subset.

## HR automation demo — why it needs a backend

The prototype's safety model is deliberately stateful and must not be
reimplemented in JavaScript:

```
prepare_note_submission(app, route, note_text)
    -> validates route against KNOWN_ROUTE_PREFIXES
    -> validates non-empty note
    -> navigates, verifies exactly one note field, inserts note
    -> verifies exactly one confirm button
    -> returns ReviewCheckpoint   (button NOT yet clicked)

            [ human review happens here ]

confirm_submission(app, checkpoint)
    -> refuses if already confirmed (non-re-entrant)
    -> refuses if the app is no longer on the reviewed route
    -> RE-LOCATES the confirm button rather than using a cached reference
    -> clicks, returns AutomationResult
```

The confirm-time re-verification exists precisely because the DOM may
change during the human review pause. A stateless REST design that
reconstructed the application between calls would silently defeat it.

**Minimal future boundary:** `POST /prepare` returns a checkpoint token
plus the reviewable payload; `POST /confirm` takes that token. The
`MockHRApplication` and `ReviewCheckpoint` are held **server-side**, keyed
by the token, for the life of one short-lived session. The frontend
renders the review and collects the human decision; it never constructs a
checkpoint, never clicks on the model's behalf, and never bypasses
validation.

This API does not exist yet and was not built as part of the data bridge.

## What Day 5 has not touched

No file under `src/procmine/segmentation/`, `src/procmine/process_discovery/`,
`src/procmine/automation/`, or `src/procmine/instrumentation_health.py`.
No file under `reports/day1..day4/`. No raw dataset. No existing test.
`segments.jsonl` unchanged. The Days 1-4 pipeline is a read-only input to
Day 5 and remains fully reproducible on its own.
