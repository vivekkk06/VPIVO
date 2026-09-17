# Module 2 — Dataset-B screenshot review: results (H3)

> **Vision-model surrogate review — not ground truth.** One reviewer — a vision model
> (Claude) — judged the frames. **No human review was performed.** The results describe
> what the screenshots show at 26 sampled moments. They are not a segmentation metric:
> no accuracy, precision, recall or F1 is computed, and none can be derived from them.

> **Dataset B is used for operational validation, not supervised segmentation
> evaluation.** Nothing here changes Module 1, Module 2's segmentation results, any
> canonical Dataset-A number, the Opportunity scoring, or any Day-7 conclusion.

**Decision: IDENTIFIES CONCERNS.** The Dataset-B visual evidence **does not support**
the sampled boundary interpretations as a group. Where the frames could be judged, 3 of
12 predicted boundaries showed a visible context change, and so did 3 of 14
mid-execution controls. This says nothing about segmentation quality, which the review
cannot measure in either direction.

| Artifact | Contents |
|---|---|
| `module2_dataset_b_screenshot_sample.json` | the fixed sample and its answer key — **unchanged** |
| `module2_dataset_b_review_sheet.md` | the prepared human review sheet — **unchanged, still blank** |
| `dataset_b_visual_review_manifest.json` | the blind manifest: everything the reviewer was given |
| `dataset_b_visual_review_judgments.json` | 40 blind judgments, each with its visual reason |
| `dataset_b_visual_review_freeze.json` | SHA-256 of the judgments, recorded before the reveal |
| `dataset_b_visual_review_results.json` | the comparison after the reveal |
| `dataset_b_screenshot_gaps.json` | why screenshot files are missing |

Code: `src/procmine/module2/visual_review.py` (protocol rules);
`scripts/prepare_module2_visual_review.py` (blind manifest and review images);
`scripts/finalize_module2_visual_review.py` (`freeze`, then `reveal`);
`scripts/diagnose_dataset_b_screenshot_gaps.py`. Tests:
`tests/test_module2_visual_review.py`.

---

## 1. Review protocol

```
sample id → frames → blind visual judgment → FREEZE (SHA-256) → reveal → compare
```

1. **Blind manifest.** The reviewer saw five fields per point: review index, session,
   sampled time, sampled screenshot path, and that screenshot's time offset. Six fields
   of the sample carry the answer and were withheld by a whitelist:
   - `kind`;
   - `point_id` (its `::bnd` / `::mid` suffix);
   - `module1_decision`;
   - `gap_ms` (null only for controls);
   - the execution ids (one for a control, two for a boundary).

   `assert_blind` refuses any manifest or judgment file that carries one of them.
2. **Frames chosen by time only.** Each available point was shown as two frames:
   - the sampled (nearest) screenshot;
   - the nearest available screenshot on the other side of the sampled moment, from the
     same session and within 60 s.

   Frames were never chosen by execution span, which would have needed the execution
   ids. Each review image was labelled only with its review number and each frame's
   offset in seconds.
3. **Unavailable by rule.** A point whose sampled screenshot is missing was labelled
   `D_UNAVAILABLE` before any image was opened. No substitute frame was used, and
   nothing was inferred from event metadata.
4. **Freeze, then reveal.**
   - All 40 judgments were written with reasons and hashed (SHA-256 `9384c97d…`, frozen
     06:32:38 UTC).
   - The reveal refuses to run unless the file still matches that hash. It first ran at
     06:32:49 UTC, and re-running it reproduces the results byte for byte.
   - The answer key was not opened before the freeze.
5. **Corrections before the freeze.** Before freezing, every rationale was re-read
   against its image. Three corrections were made, all logged in the judgments file:
   - #15 and #20 moved from A to C, so that the completion-toast rule (§4) applies to
     them as it does elsewhere;
   - #37's confidence dropped from medium to low.
6. **Reviewer.** A single vision-model reviewer.
   - With no second reviewer, there is no inter-rater agreement and no disagreement to
     record.
   - Typed note text visible in frames was not transcribed.
   - Review images were built in a scratch directory outside the repository and are not
     committed.

## 2. Blind sampling

The existing sample was reused as written. **Nothing was re-drawn.**

- **Seed and population.** Seed `20260918`. The population is 630 predicted boundaries
  and 599 mid-execution controls from Module 1's Dataset-B output. Twenty of each were
  drawn separately and then shuffled together.
- **Predicted boundary:** the midpoint of the gap between consecutive executions in a
  session. Module 1's decision there is *different units of work*.
- **Mid-execution control:** the temporal midpoint of an execution with at least 4
  events. Module 1's decision there is *same unit of work*.
- **Integrity checks (tested):**
  - the 40 manifest points match the sample row for row (session, time, screenshot,
    offset);
  - the sample still matches the prepared review sheet;
  - the review order interleaves the two kinds.

## 3. Screenshot availability

**26 of 40** sampled points could be reviewed.

| | Points |
|---|---:|
| Sampled | 40 |
| Sampled screenshot present | **26** |
| Sampled screenshot missing | **14** |
| Recovered from elsewhere in the repository | **0** |
| Reviewable points that also had a frame on the other side | 26 of 26 |

**Recovery.** I searched every JPG under `dataset_b/` for an exact filename match. A
match would count only if it came from the same session and had the byte size the
capture agent recorded. None of the 14 files exists anywhere in the dataset. No external
or private source was consulted, and no other screenshot was substituted.

**Why the files are missing** (descriptive; `dataset_b_screenshot_gaps.json`):

- **Totals.** The event logs reference 4,746 distinct screenshot files (4,759
  screenshot events). Of those, 3,860 are present and 886 are absent.
- **A 250-file pattern.**
  - Every capture chunk that references more than 250 screenshots holds exactly 250
    files. There are 11 such chunks.
  - The other 9 chunks reference at most 211 files each, and all of them are complete.
- **Spread through time.** Inside those 11 chunks the absent files are interleaved in
  time rather than forming a missing tail.
- **Manifests.** Each of the 11 chunk manifests declares the full count; one declares
  304 files where 250 are present. The capture agent therefore wrote more files than
  the dataset contains.
- **Upload records.**
  - The log has no upload-failure event type.
  - Five uploads are logged, and the four logged as completed were all for complete
    chunks.
  - The only capped chunk with an upload record (session 171614, chunk 1700, 401 files)
    shows a start and no completion.
  - The other ten capped chunks are each the last chunk of their session. Any upload
    record for them would have been logged in a later chunk, which the dataset does not
    contain.
- **The sample.** All 14 missing sampled screenshots sit in capped chunks.
- **Cause: not determinable from the repository.** The pattern is consistent with a
  250-files-per-chunk limit applied somewhere between capture and the dataset as
  delivered. The logs do not say where that happened, or how the kept files were chosen.

**Unavailable is not negative evidence.** The 14 points are reported as unavailable and
left out of every rate. They count neither for nor against Module 1.

## 4. Visual rubric

These definitions were written into the manifest before any image was viewed:

| Label | Meaning |
|---|---|
| `A_CLEAR_CONTINUITY` | Same business context on both sides of the moment: same application or system, same screen, form or document |
| `B_CLEAR_BOUNDARY` | A change of business context across the moment: a different system, application, document, or record screen |
| `C_AMBIGUOUS` | The visible evidence is not enough to decide |
| `D_UNAVAILABLE` | The sampled screenshot is missing or unreadable; nothing is inferred from metadata |

The following operational rules were written down during the review, before the reveal,
and applied to every point:

- **B** needs different business contexts: a different application with unrelated
  content, or a different record clearly opened after the previous one ended.
- **An application switch whose content continues the same topic** (a record, and the
  procedure or memo for that kind of work) is **C**, not B.
- **A** needs the same context on both sides with no completion or switch signal between
  the frames. Visible work on the same record strengthens it.
- **A completion toast or "open with" dialog between the frames** makes a point **C**
  unless a different record is visibly opened.
- **An identifier cut off at the frame edge** is not read.

One consequence matters for §5: the rubric counts opening a different record as a
context change. Nothing in the repository defines, as ground truth, whether a Dataset-B
unit of work is one record or a stretch of work in one system.

## 5. Results

**Blind judgments, recorded before the reveal:** A 7 · B 6 · C 13 · D 14.

**After the reveal:**

| Sample type | A continuity | B boundary | C ambiguous | D unavailable | Judgeable |
|---|---:|---:|---:|---:|---:|
| Predicted boundaries (20) | 3 | 3 | 6 | 8 | 12 |
| Mid-execution controls (20) | 4 | 3 | 7 | 6 | 14 |
| **All (40)** | **7** | **6** | **13** | **14** | **26** |

Descriptive rates, computed over judgeable points only:

- **Boundary-sample visual support rate: 0.25.** 3 of 12 judgeable predicted boundaries
  show a visible context change (#7, #8, #34).
- **Control-sample visual continuity rate: 0.2857.** 4 of 14 judgeable controls show
  clear continuity (#11, #12, #31, #32).
- **Disagreements, reported rather than hidden:**
  - 3 of 12 judgeable boundaries look clearly continuous (#16, #18, #40);
  - 3 of 14 judgeable controls show a visible change (#1, #2, #27).

The labels fall almost identically across the two sample types. **On this sample and
under this rubric, the screenshots do not separate Module 1's predicted boundaries from
the middle of its executions.**

These are counts from one reviewer, who is not human, over 26 moments. They are not
metrics: no accuracy, precision, recall or F1 is computed, and the rubric is not a
ground-truth definition of a unit of work.

### What the disagreements have in common

Everything below comes after the reveal. It uses Module 1's own execution records,
stored per point in `dataset_b_visual_review_results.json`, and none of it was used to
set a label.

- **Reference lookups are cut out or kept by length alone.** Module 1 absorbs a detour
  of at most 5 events into the surrounding execution (`merge_max_away_events = 5`) and
  makes a longer one its own execution. The Word procedure-document visits in the
  sample follow that rule exactly:
  - visits of 4–5 events sit inside business-system executions (#1, #15, #19, #27, #37);
  - visits of 8 events became executions of their own, just before #7, #16, #18 and #40.
- **Continuous-looking boundaries all follow such a lookup.** In #16, #18 and #40, both
  frames show one record open and being worked on, and the Word document just before
  matches that record's topic:
  - nursing-care leave rules, then a nursing-care leave application (#16);
  - the new-contract procedure, then a contract record whose own reference field names
    that document (#18);
  - expense rules, then an expense record (#40).

  This is consistent with a lookup inside one task being split off as a separate
  execution. In #7, the other 8-event case, the topic did change (contract termination,
  then a new contract), and the frames show it.
- **Controls with a visible change.**
  - In #1, one onboarding record finishes and the next one is opened inside a single
    HR execution.
  - In #27, a 5-event Word visit to the new-business-partner registration procedure
    sits inside a Financial Accounting execution, followed by an unrelated purchase
    order.
  - In #2, the earlier frame shows a Notepad inventory memo in front, although Module 1
    attributes every step at that moment to the HR system. Here the logged context and
    the visible screen disagree.
- **Record completions inside executions.** In 5 of 14 judgeable controls (#1, #4, #10,
  #15, #20), a record is completed (a toast) in the middle of one Module-1 execution.
  This fits the documented Dataset-B boundary signal: it is built on the active system
  (from window titles), so it does not separate consecutive records handled in one
  system.
- **Boundaries at non-business screens.**
  - Three sampled boundaries (#13, #35, #36) sit where an "open with" file dialog
    closes. The execution before each is the `app:OpenWith` context, which the ranking
    already excludes.
  - One boundary (#21) comes just before a Windows Explorer execution.
- **Agreement can be coincidental.** #34 counts as visual support, but both of its
  frames show the Financial Accounting system. The B label rests on a new record being
  selected. The HR → Financial switch that Module 1 marked happened before the earlier
  frame.

**A question for human review, not a conclusion.** Suppose Dataset-B executions often
span several records and sometimes split one record around a lookup. Then count-based
quantities (executions per process, duration per execution) depend on that granularity
more than time totals do. This review does not measure that effect, and no canonical
number is changed.

## 6. Ambiguous and unavailable cases

**Ambiguous: 13 of 26 reviewable points.** `C` was chosen when the frames could not
decide. It is not a hidden A or B.

| What left it open | Points | Sample type (revealed) |
|---|---|---|
| A completion toast between the frames, and no different record visibly opened | #4, #10, #15, #20, #21 | control ×4, boundary ×1 |
| An "open with" dialog in the earlier frame, closed in the later one; no spreadsheet visible yet | #13, #35, #36 | boundary ×3 |
| An application switch whose content continues the same topic | #6, #14, #19, #23, #37 | boundary ×2, control ×3 |

- In #10, a detail panel was opening, but its record identifier is cut off even at full
  resolution.
- #37 is the least certain judgment (low confidence): the selected contract's vendor
  already has approved contracts in the list, and its detail panel is cut off.
- That half of the reviewable points are ambiguous is itself a finding. Two frames a
  second or two apart often cannot show whether a new unit of work began.

**Unavailable: 14 of 40 points.** #3, #5, #9, #17, #22, #24, #25, #26, #28, #29, #30,
#33, #38, #39.

- These are 8 predicted boundaries and 6 controls.
- #25 and #28 point to the same missing file.
- Every one of these files is absent from a capped chunk (§3). None is treated as
  evidence either way.

## 7. What this review can and cannot establish

**It can:**

- describe what the screen showed around 26 sampled moments, under a rubric fixed before
  viewing, without knowing which moments were predicted boundaries;
- show that, in this sample, visible context changes are no more frequent at Module 1's
  predicted boundaries than in the middle of its executions;
- point human reviewers at specific patterns they can check:
  - reference lookups split off as their own executions purely by length;
  - executions that span record completions;
  - boundaries at "open with" dialogs;
- establish why 14 sampled screenshots cannot be reviewed.

**It cannot:**

- **Establish segmentation quality in either direction.** No accuracy, precision, recall
  or F1 exists for Dataset B, and these counts do not imply one.
- **Generalise.** Only 40 of 1,229 candidate points were sampled and 26 judged. That is
  enough to raise a pattern, not to estimate a rate for the 645 executions.
- **Say anything about the 14 unavailable points.**
- **Replace human review.** There is one reviewer, it is a vision model, and no
  inter-rater agreement exists.
- **Decide what a Dataset-B unit of work should be.** The rubric counts a record switch
  as a context change; Module 1's Dataset-B boundary signal does not.
- **See between frames.** Frames here are 0.1–6 s from the sampled moment, and with a
  gap under a second both can fall after the switch Module 1 marked. The three
  continuous-looking boundaries have gaps of 336–480 ms.
- **Judge business correctness.** A screenshot shows what the UI displayed, not whether
  the work was right.
- **Find boundaries Module 1 never proposed.** The sample is drawn from Module 1's own
  decisions.

## 8. Decision

Options: useful corroborating evidence · inconclusive · identifies concerns.

**IDENTIFIES CONCERNS — not a segmentation metric.**

- **As a group, the sampled boundaries are not visually supported.** The Dataset-B
  visual evidence does not support them: 3 of 12 judgeable boundaries visibly change
  context, and so do 3 of 14 judgeable controls. Individually, the frames support three
  boundaries (#7, #8, #34; #34 only coincidentally, see §5) and run against three (#16,
  #18, #40).
- **Segmentation quality is untouched either way.** This review provides no evidence
  about it in either direction.
- **The concerns are leads, not conclusions.** 13 of 26 reviewable points are ambiguous,
  14 of 40 have no image, and there is only one surrogate reviewer.

**H3** asked whether screenshot sampling can give a useful qualitative sanity check on
real segmentation output without ground truth. **It has been assessed by surrogate
review only.**

- **What it produced:** specific, checkable concerns — the kind of sanity check H3
  describes.
- **The limits:** half of the reviewable evidence was ambiguous, and a third of the
  sample had no image.
- **Outstanding:** human review has still not been done.

**What does not change.**

- **Module 1** stays canonical and locked.
- **Module 2** segmentation stays **NOT PROMOTED**. This review is not a basis for
  promotion, and it did not evaluate Module 2's segmentation.
- **Canonical artifacts:** no canonical Dataset-A metric, Dataset-B execution, process
  profile, Opportunity score or Day-7 conclusion was modified.
- **The review sheet:** the prepared sheet is kept, and its human-judgment columns
  remain blank.

**Next step.** Run a human review of the same frozen sample, starting from the patterns
in §5, and ask the data provider for the 886 files missing from the 11 capped chunks.
