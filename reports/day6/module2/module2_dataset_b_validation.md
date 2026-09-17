# Module 2 — Dataset-B blind review (H3): surrogate visual review completed, human review not performed

> **Surrogate visual review completed; human review not performed.** A vision model
> judged the 26 reviewable points blind, and its judgments were frozen before the answer
> key was read. Full results: `dataset_b_screenshot_review_results.md`.
> **Vision-model surrogate review — not ground truth.** This is not a validation result,
> not an accuracy measurement, and not human-labelled ground truth. The prepared human
> review sheet is unchanged, and its judgment columns are still blank.

> **Dataset B is used for operational validation, not supervised segmentation
> evaluation.** No accuracy, precision, recall or F1 is computed anywhere in this
> report or in the artifacts it describes, and none may be derived from them.

---

## 1. Observation

Dataset B has no ground truth. Module 1 nevertheless produces 645 executions from it,
and every downstream business conclusion — process ranking, the HR recommendation, the
automation prototype — rests on those executions being approximately right. Nothing so
far had looked at whether they *are*.

## 2. Hypothesis (H3)

Screenshot sampling can provide a useful qualitative sanity check on real segmentation
output even though no ground truth exists.

## 3. Method

**Population.** Two kinds of point, both Module 1 decisions, differing only in
direction:

| Point | Definition | Module 1's decision |
|---|---|---|
| Predicted boundary | midpoint of the gap between consecutive executions in a session | "different units of work" |
| Mid-execution control | temporal midpoint of a single execution (≥ 4 events) | "same unit of work" |

The population holds 630 boundaries and 599 controls.

**Sampling.** Deterministic. The population is sorted by `point_id`, then drawn with
`random.Random(20260918).sample`. Boundaries and controls are drawn separately and then
shuffled together, so re-running the command reproduces the identical sheet.

**Blinding.** The sheet mixes both kinds in shuffled order, so a reviewer who answered
"transition" every time would score no better than chance. Without the controls, the
exercise would measure agreeableness rather than judgement.

**Evidence.** For each point, the nearest `screenshot_smart` event in the same session
by |Δt|, resolved to its `file_reference.relative_path`.

**Human sheet vocabulary.** `LIKELY TRANSITION` · `LIKELY SAME TASK` · `AMBIGUOUS`.

**Surrogate review (completed later, on the same sample).**

- **Rubric.** `A_CLEAR_CONTINUITY` · `B_CLEAR_BOUNDARY` · `C_AMBIGUOUS` ·
  `D_UNAVAILABLE`, written down before any image was viewed.
- **What the reviewer saw.** Each point was shown as two frames, chosen by time only,
  from a blind manifest that withholds every answer-bearing field.
- **Freeze, then reveal.** The judgments were hashed before the reveal. Details are in
  `dataset_b_screenshot_review_results.md` §1.

## 4. Results

| Measure | Value |
|---|---:|
| Sampled points | 40 (20 boundaries / 20 controls) |
| Points with a nearest screenshot | **40 / 40** |
| Median \|Δt\| to nearest screenshot | **385 ms** |
| Nearest-screenshot file missing on disk | **14 / 40** (0 recovered) |
| Human review status | **NOT REVIEWED** |
| Surrogate review status | **Completed — vision model, not ground truth** |
| Surrogate labels (blind) | A 7 · B 6 · C 13 · D 14 |
| Visible context change, judgeable boundaries | **3 of 12** |
| Visible context change, judgeable controls | **3 of 14** |
| Surrogate decision | **IDENTIFIES CONCERNS** |

Artifacts:

- `module2_dataset_b_screenshot_sample.json` — the full record, with the answer key;
- `module2_dataset_b_review_sheet.md` — the blind human sheet, still blank;
- `dataset_b_visual_review_*.json` — the surrogate review: manifest, judgments, freeze
  record and results;
- `dataset_b_screenshot_gaps.json` — the missing-file diagnosis.

## 5. Interpretation

**The temporal pairing is good.** A median of 385 ms between the sampled point and the
nearest capture means each screenshot genuinely depicts the moment in question. No
boundary is paired with an image from thirty seconds away.

**The evidence base is incomplete, for a traceable reason.** 14 of 40 nearest
screenshots are referenced by an event but absent from the dataset, and none could be
recovered.

- **The 250-file pattern.** Across Dataset B, every capture chunk that references more
  than 250 screenshots holds exactly 250 files. All 14 missing sampled files sit in such
  chunks.
- **Cause.** Where between capture and delivery the files were dropped cannot be
  determined from the repository.
- **Effect.** 26 of 40 points are reviewable. The other 14 are reported as unavailable,
  not as evidence either way.

**What the surrogate review found.**

- **Boundaries and controls look alike.** Visible context changes were no more common
  at predicted boundaries (3 of 12 judgeable) than inside executions (3 of 14 judgeable
  controls), and 13 of the 26 reviewable points were ambiguous.
- **Continuous-looking boundaries follow Word lookups.** Three predicted boundaries sit
  in visibly continuous work on one record. Each comes right after an 8-event Word
  procedure lookup, which Module 1 made its own execution because it exceeds the
  5-event merge limit.
- **Controls span record completions.** Several controls span a record's completion,
  consistent with a boundary signal built on the active system.

**H3 is assessed by surrogate review only.** The sampling produced specific, checkable
concerns, which is the kind of sanity check H3 describes. But half of the reviewable
evidence was ambiguous, a third of the sample had no image, and the only reviewer was a
vision model. Human review is still outstanding.

## 6. Why the human sheet is still blank

The human judgments ship **empty by design**. The surrogate review was run separately,
under a freeze-then-reveal protocol:

- its labels live in their own files and carry the label *Vision-model surrogate review
  — not ground truth*;
- they were **not** written into the human sheet;
- they are not called ground truth;
- they are not turned into a segmentation metric;
- they change no canonical number.

**No human review was performed here, and that limitation is reported rather than
worked around.**

## 7. Limitations

- **Sample size.** 40 sampled points out of 1,229 candidates is enough to spot a
  systematic problem, not to quantify a rate.
- **Missing images.** 14 of 40 screenshots are missing from the dataset (a
  250-files-per-chunk pattern; the mechanism is not determinable).
- **What a frame can show.** A screenshot shows one monitor at one instant, so a
  transition spanning applications may not be visible in it. With sub-second gaps, both
  review frames can fall after the switch that Module 1 marked.
- **Only Module 1's decisions.** The sample is drawn from Module 1's output, so it can
  reveal where Module 1 looks wrong but cannot discover boundaries Module 1 never
  proposed.
- **One non-human reviewer.** There is no inter-rater agreement: one surrogate reviewer,
  and no human rater.
- **No agreed unit of work.** The rubric counts a switch to a different record as a
  context change. No ground truth says whether a Dataset-B unit of work is one record
  or a stretch of work in one system.

## 8. Decision

- **The framework.** The blind-review framework is **retained** and the human sheet is
  **reported as unreviewed**.
- **The surrogate review.** It is **completed** and recorded as **IDENTIFIES
  CONCERNS**: the visual evidence does not support the sampled boundary interpretations
  as a group. That is not a segmentation metric, and it is not evidence about
  segmentation quality in either direction.
- **H3.** Recorded as *assessed by surrogate review only: identifies concerns; human
  review not performed.*
- **Unchanged.** Nothing in the canonical pipeline changes as a result, no Dataset-B
  accuracy figure exists, and Module 2 remains **NOT PROMOTED**.
