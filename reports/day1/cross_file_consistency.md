# Cross-File Consistency

Checking agreement between `events.jsonl`, `manifest.json`, `gt.jsonl`, and
`gt_manifest.json` for the same session. Each finding below is marked
**EXPECTED** (a real difference that's by design, not a defect) or
**INCONSISTENCY** (something that shouldn't disagree but does).

## `machine_id`: manifest vs. `gt.jsonl` run_config — EXPECTED difference

`manifest.json.machine_id` and `source.machine_id` on every event carry the
**real recording hostname** (e.g. `LAPTOP-R36BQBTE`, `CHAITANYA0BCF`).
`gt.jsonl`'s first line (`run_config`) carries a **different** `machine_id`
— a synthetic scenario code (e.g. `NB-M1-05`, `PC-M1-02`). Verified across
multiple sessions; the two never overlap and the synthetic codes look like
they come from the scenario generator's own machine-role naming, not the
physical machine. **Do not join across files on `machine_id`** — it's two
different namespaces that happen to share a field name. Documenting this
explicitly because it's exactly the kind of thing that silently breaks a
join if you don't check first.

## `split_id`: real inconsistency between `gt.jsonl` and `gt_manifest.json`

Found via the `ses_20260701-051820-CHAITANYA0BCF` case study (see
`session_case_studies.md`): process B is suspended via a `process_suspended`
event in `gt.jsonl` carrying `split_id: "M1-B-split-1"`, and never resumed
within the session. In `gt_manifest.json`, the corresponding execution
(`case_id: PI-101000-002`) is recorded with **`split_id: null`** and
`continues_to_next: false` — `gt_manifest.json`'s summary does not surface
that this execution was, in fact, suspended.

**This is a real cross-file disagreement, not just a naming quirk.**
`gt_manifest.json`'s `split_id` field only gets populated for splits that
*did* get a matching resume; an abandoned suspension is invisible in the
manifest and only visible in the raw `gt.jsonl` stream. Anyone using
`gt_manifest.json` alone as "the" ground truth would miss this case
entirely. Our `parse_gt_executions` (reading `gt.jsonl` directly) is the
one place this is caught — which is the reason the loaders reconstruct from
both sources rather than trusting the ready-made summary exclusively.

**Also confirmed**: `split_id` values like `M1-B-split-1` are **not globally
unique** — the same literal string appears in `gt.jsonl` across 25 different
sessions (`grep -rl "M1-B-split-1" dataset_a/*/gt.jsonl`). It's a
per-scenario template label ("process B's first defined split point"),
reused every time that scenario template runs, not a cross-session linking
key. Scoping `split_id` matching to within a single session (as our parser
does) is required for correctness.

## `correlation.chunk_id` vs. the file an event was actually read from — 1 INCONSISTENCY

In `ses_20260701-115141-SIDDHIGUPTAB00B`, one event's own
`correlation.chunk_id` field says `chunk_20260701-1130-SIDDHIGUPTAB00B`, but
the event was physically read from
`chunk_20260701-1200-SIDDHIGUPTAB00B/events.jsonl`. Likely explanation: the
event was captured right at a chunk-transition boundary and got flushed to
the next chunk's file while its own metadata still reflects the chunk it
was logically part of when captured. Rate: 1 event out of 162,768 (effectively
noise), but worth having a check for (`session_chunk_identity_checks`) since
a segmentation approach that trusts `correlation.chunk_id` as authoritative
chunk membership would be wrong for this event.

## GT execution counts: `gt.jsonl` reconstruction vs. `gt_manifest.json` — 0 mismatches

`cross_check_against_manifest` compares, per process code, the number of
executions our own `gt.jsonl` state-machine reconstructs against
`gt_manifest.json`'s own `executions[]` list. **0 mismatches across all 63
Dataset A sessions, 2,009 total executions.** The two sources agree at the
count level everywhere except the `split_id` field-level gap described
above (which a count-only check can't see — it's the same execution counted
correctly by both sides, just described differently).

## Session boundaries: `gt.jsonl`'s `session_ended` vs. `manifest.json`'s `time_range` — consistent

Spot-checked; `gt.jsonl`'s reported `duration_seconds` and the manifest's
own `time_range.start_ms`/`end_ms` for the session's first/last chunk agree
within normal end-of-session logging lag (a few hundred ms — the
`session_ended` line in `gt.jsonl` is written after the corresponding
`session_end` event in `events.jsonl`).
