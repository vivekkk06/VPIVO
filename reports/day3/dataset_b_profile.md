# Dataset B Data Profile

First authorized inspection of Dataset B, per the assignment's own instruction to
understand the data completely before designing any process-discovery algorithm.
Every number below is freshly computed against Dataset B directly — nothing is
carried over from Dataset A's statistics. Where a Dataset-A finding is mentioned,
it is explicitly to show that the same check was re-run on B and produced a
**different** answer, not assumed to transfer.

Tools used: the existing dataset-agnostic Day-1 infrastructure
(`scripts/profile_dataset.py`, `scripts/audit_dataset.py`, `procmine.loaders`,
`procmine.paths.discover_dataset`) — these load/validate raw events and were
built to work on either dataset; nothing about the *segmentation architecture*
(V1/V2/Design 2/Combined) locked for Dataset A was reused here. Raw data was
only read, never modified.

## 1. Structure

- **15 sessions, 20 chunks, 20,477 events.** No `gt_manifest.json` anywhere in
  the tree — confirmed via `find dataset_b -iname "gt_manifest*"` (empty). No
  ground truth exists for Dataset B, by design; every downstream claim in this
  and later Day-3 reports must be evaluated on internal consistency and
  qualitative plausibility, never against a GT boundary or label.
- Session naming (`ses_<timestamp>-<machine_id>`) is a naming convention, not
  verified structure — the actual operator identity was pulled from each
  session's own `chunk_*/manifest.json` (`machine_id` + `firebase_uid`), not
  inferred from the folder name.
- 5 of 15 sessions (33%) span 2 chunks; the rest are single-chunk. (Dataset A
  was 53/63 = 84% multi-chunk — B's sessions are shorter and rarely split.)

## 2. Operators

Four distinct `(machine_id, firebase_uid)` pairs across all 15 sessions:

| machine_id | firebase_uid (truncated) | sessions |
|---|---|---|
| NEELA9BAF | BIW0iSqq... | 5 |
| LAPTOP-76QMG9DE | ZkqKHLUy... | 5 |
| SIDDHIGUPTAB00B | F2C4UuAU... | 3 |
| CHAITANYA0BCF | 4kky8yQ7... | 2 |

**Sessions from different operators are interleaved in real time, not
sequential blocks** — e.g. between 17:32 and 19:36 (2026-07-01), sessions from
all four operators overlap chronologically (verified directly from each
chunk's `manifest.json` `time_range`). This looks like several parallel,
independently-scripted work streams recorded on the same day, not one person's
single continuous workday. **Assumption recorded**: execution/process
discovery below treats each session as belonging to exactly one operator and
never merges activity across two different sessions — consistent with how
Dataset A's GT executions were always session-scoped, and the only defensible
default given no evidence connects work across a session boundary here either.

Within one operator's own sessions, gaps between sessions range from ~4 to
~28 minutes (e.g. NEELA9BAF: session ends 17:47:03, next starts 18:09:23, a
22-minute gap) — plausible break/setup time between recording runs, not
investigated further since it falls **between** sessions, out of scope for
within-session execution discovery.

## 3. Session timing and density

- Session duration: **min 429s (7.2 min), max 987s (16.4 min), mean 705s
  (11.75 min)** — noticeably shorter than Dataset A's sessions (which averaged
  ~2,584 events/session; B averages 1,365 events/session).
- **Inter-event gap distribution (the single most important, and most
  surprising, finding for Section 2's method choice)**, computed from
  20,462 sorted-timestamp transitions across all 15 sessions:

  | Percentile | Gap (ms) |
  |---|---|
  | median (p50) | 62 |
  | p75 | 373 |
  | p90 | 1,885 |
  | p95 | 2,744 |
  | p99 | 5,971 |
  | p99.9 | 9,940 |
  | **max** | **64,117 (≈1.1 minutes)** |

  Dataset A's equivalent distribution (Day 1) had a median of 44ms but a
  **maximum of ~2.4 hours** and a well-populated tail of multi-minute and
  multi-hour gaps — those large gaps were the entire basis for Design 2's
  "isolated candidate" reasoning and the original temporal-gap hypothesis.
  **Dataset B has no such gaps anywhere in the entire dataset.** Per-session
  median gaps range only 21.5–92ms — every session is a dense, essentially
  uninterrupted stream of activity.

  **Implication, stated now because it changes the Section-2 strategy**: a
  pure time-gap-threshold method (Dataset A's original V0 baseline, and the
  temporal signal Rule 4/V1/V2 leaned on heavily) has **no large-gap evidence
  to work with in Dataset B** — the biggest gap in the whole dataset (1.1
  minutes) is smaller than Dataset A's own *median same-execution* gap
  regime in some sessions. Whatever produced Dataset B's session boundaries
  (chunk splits, recording start/stop) already removed the idle periods; what
  remains inside a session is dense, continuous work. This means candidate
  execution boundaries inside a Dataset B session are much more likely to be
  found via **context change** (application switch, window/system change) than
  via any gap-size signal — the opposite of how Dataset A's investigation
  started. This needs to shape Section 2's method choice directly, not be
  discovered after building a gap-based baseline that has nothing to detect.

## 4. Applications actually used

| Application | Events |
|---|---|
| Microsoft Edge | 13,300 |
| Microsoft Word | 3,704 |
| Microsoft Excel | 1,201 |
| OpenWith (Windows file-open dialog) | 757 |
| Notepad | 599 |
| WindowsTerminal | 407 |
| procmine-desktop-agent (recording tool itself) | 205 |
| Windows Explorer | 78 |
| ms-teams | 73 |
| prl_cc (Parallels control center — VM artifact) | 28 |

`procmine-desktop-agent` and `prl_cc` are the recording infrastructure and a
virtualization artifact respectively — not business activity; excluded from
process content in later sections the same way Day 1 excluded the agent's own
windows from Dataset A analysis.

## 5. What the window titles reveal about the actual work (real evidence, not inferred)

Window titles are literal strings the agent captured — this is the strongest,
most direct evidence available about what business processes Dataset B
contains, and it names them explicitly:

- **財務会計システム** ("Financial Accounting System") — a browser-based
  system, seen in 12+ sessions.
- **HR人事給与システム** ("HR Personnel & Payroll System") — browser-based,
  the single most common non-terminal window title.
- **受発注在庫管理システム** ("Order Receiving/Placement & Inventory
  Management System") — browser-based.
- Multiple **Word documents in Compatibility Mode**, each an administrative
  procedure document, e.g. `shinkuitorihikisaki_touroku_tetsuzuki` ("new
  trading-partner registration procedure"), `keiyaku_kaijo_tetsuzuki`
  ("contract termination procedure"), `ikuji_kyuugyou_kitei` ("childcare
  leave regulations"), `kanrisya_kengen_shinsei_tetsuzuki` ("administrator
  authority request procedure"), `nyusha_checklist_shinsotsu_batch` ("new
  employee checklist, new-graduate batch"), `gyomu_itaku_keihi_kitei`
  ("outsourcing expense regulations"), `getsujitsu_teigaku_torihikisaki_ichiran`
  ("monthly fixed-amount trading-partner list"), `shinkui_keiyaku_tetsuzuki`
  ("new contract procedure").
- **Excel**: `budget_analysis.xlsx` window title observed directly.
- **Notepad memos**: `在庫調整メモ` ("inventory adjustment memo"), `IT申請メモ`
  ("IT request memo"), `精算確認メモ` ("expense settlement confirmation memo").
- **Microsoft Teams** (Chat, Settings) — communication, low volume (73 events).
- The three browser systems all run on **localhost, on three different ports**
  (`127.0.0.1:5132/5133/5134`) — the exact same "one portal, several local
  services on different ports" pattern Stage 5 of the Dataset-A investigation
  found and explicitly tested (and rejected stripping the port for). One
  incidental external domain, `app.slack.com` (32 events).
- "Restore pages", "Turn off extensions in developer mode", and "Translate
  page from Japanese?" are **Edge's own dialogs**, not business content —
  excluded from process-content analysis.

**Per instruction #2 ("do not invent process names before examining the
data")**: the process names used from Section 3 onward will be grounded in
these literal, observed strings (the three system names, the named Word
procedures, "budget analysis") — not invented labels. This is genuinely
strong, direct evidence, not an inference from statistical clustering alone,
and later sections will cross-check any sequence-similarity-derived process
grouping against whether it corresponds to a single one of these named
systems/documents, flagging disagreement rather than hiding it.

## 6. Data-quality findings specific to Dataset B (not inherited from A)

- **Raw event order is not reliably chronological here either** — 2,923 of
  20,477 events (14.3%) are out of order before sorting by `timestamp_ms`,
  confirming the same discipline (always sort explicitly, never trust
  `sequence_number`/file order) applies to B independently.
- **Screenshot resolution: 3,860/4,759 (81.1%)** files actually found on disk
  — matches the ad hoc 81.2% figure noted in Day 1, now confirmed via the full
  audit tool rather than a spot check. Much higher than Dataset A's 7.2%.
- **`extracted_text` present on only 4.59%** of events (939/20,477) — a
  different rate than Dataset A's; not yet compared in detail, flagged for
  Section 2/7 if OCR/text evidence becomes relevant to a specific process.
- **Duplication pattern is genuinely different from Dataset A, not absent —
  just a different signal.** Dataset A's dominant issue was `app_switch`
  duplication (65% of all app_switch events). In Dataset B, `app_switch` shows
  **zero** sequential duplication. Instead: `mouse_scroll` (110 sequential
  duplicate pairs), `extension_disconnected`/`extension_connected` churn
  (20/17 — likely a browser-extension reconnect artifact), and a small amount
  of `clipboard_change` (3). **This means the Dataset-A cleaning step
  (`deduplicate_consecutive` keyed on `app_switch_payload_key`) does not
  address Dataset B's actual duplication problem** — if `mouse_scroll` volume
  is used anywhere as an activity-density signal, it needs its own
  deduplication pass first, or density estimates will be inflated by this
  specific artifact.
- 0 exact-duplicate-ID groups, 0 malformed manifests, 0 chunk-linkage issues,
  0 session/chunk machine-id inconsistencies — the dataset is otherwise clean
  by the same checks Day 1 built.
- Event-type vocabulary present in B: `session_start/end, mouse_click,
  app_switch, screenshot_smart, keystroke, window_state_change, browser_error,
  window_title_change, browser_navigation, extension_connected/disconnected,
  browser_click, shortcut, mouse_scroll, clipboard_change, browser_form_input,
  text_input_complete, upload_started/completed, mouse_double_click` — no
  `dialog_opened/closed`, `browser_alert`, `browser_tab_event`, or
  `mouse_drag_drop` observed in B at all (present in A). Not treated as a
  defect — just a real, dataset-specific difference in what got triggered.

## 7. What this means for Section 2 (stated now, before any method is built)

1. A pure time-gap-threshold approach — the natural first instinct carried
   from Dataset A's own V0 baseline — has essentially no signal to work with
   inside a Dataset B session (max gap 1.1 minutes, most sessions have
   sub-100ms median gaps). It should still be *tested* (per instruction, "test
   several reasonable approaches"), but the evidence above predicts it will
   perform poorly, and that prediction should be checked, not skipped.
2. Context-change signals (application switch; the three named systems'
   window-title changes; browser navigation between the three localhost
   services) are the more promising starting point, precisely because B's own
   data shows dense, gapless activity punctuated by real system/application
   switches — the opposite profile from A.
3. The window-title evidence (Section 5) gives an unusually strong, literal
   grounding for what "process" should mean in Dataset B — this should be used
   as a cross-check on any statistical/sequence-based process discovery in
   Section 4, not discarded in favor of a purely unsupervised method.
4. `mouse_scroll` deduplication is a prerequisite before this event type is
   used in any density or repetition measurement.

## 8. Explicit assumptions recorded

- Executions never cross a session boundary (no evidence connects work across
  sessions; consistent with Dataset A's convention).
- `procmine-desktop-agent` and `prl_cc` activity is recording/VM infrastructure,
  not business work, and will be excluded from process-content analysis
  (205 + 28 = 233 events, 1.1% of the dataset).
- Edge's own dialogs ("Restore pages", "Turn off extensions...", "Translate
  page from Japanese?") are browser chrome, not business content.
- Window-title-derived process names (Section 5) are treated as strong
  evidence for grounding, not as ground truth — Dataset B has no GT to
  validate against, so every later claim about a "process" remains a
  data-driven hypothesis, reported with its supporting evidence, not asserted
  as fact.

## 9. Explicitly not yet done

No execution boundaries, no process/variant discovery, no time-consumption
analysis, no automation scoring. This report is Section 1 only, per the
assignment's own instruction to inspect and report before any algorithm
design.
