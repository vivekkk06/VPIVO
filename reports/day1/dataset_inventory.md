# Dataset Inventory

Generated from `discover_dataset()` walking the real directory trees (see
`dataset_inventory.json` for the machine-readable version, and
`profile_dataset_*.json` for event-level stats).

| | Dataset A | Dataset B |
|---|---|---|
| Sessions | 63 | 15 |
| Chunks | 117 | 20 |
| `events.jsonl` files | 117 (= chunk count, none missing) | 20 (= chunk count) |
| `manifest.json` files | 117 (= chunk count, none missing) | 20 (= chunk count) |
| `gt.jsonl` files | 63 (every session) | 0 (by design — no ground truth) |
| `gt_manifest.json` files | 63 (every session) | 0 |
| Screenshot directories found | 50 (fewer than 117 chunks — see below) | 20 |
| Empty files found | 0 | 0 |
| Missing expected files | 0 | 0 |
| On-disk size | 1.49 GB (741 MB JSONL + 752 MB JPEG) | 1.45 GB (86 MB JSONL + 1.36 GB JPEG) |
| Total events | 162,768 | 20,477 |
| Session duration | 9.5–46.8 min (mean 24.4) | see `profile_dataset_b.json` |

Every session, chunk, `events.jsonl`, and `manifest.json` that should exist,
does — no missing or empty files in either dataset. That's a clean baseline;
the real data-quality issues in this dataset are not "files are missing,"
they're inside the files (see `full_audit_dataset_a.json` and the other
reports in this directory).

## Chunk boundaries are not process boundaries

Repeating this explicitly because it shapes every design decision after this
point: a chunk is purely a recording-buffer artifact (DATA_SCHEMA.md, "chunk
... has nothing to do with where business processes begin or end"). Our own
data confirms this — GT process executions routinely span chunk boundaries
(`continues_from_prev`/`continues_to_next` in `gt_manifest.json` are `true`
for the majority of Dataset A's 2,009 reconstructed executions). Step 1 must
operate on the merged, session-level event stream (`load_session_events`),
never on a single chunk in isolation.

## The screenshot-directory count needs a caveat

50 screenshot directories were *found* for 117 chunks, but directory
presence isn't the same as coverage. The real number that matters is
**resolution rate** — of the `screenshot_smart` events that claim a capture
happened, how many actually have a JPEG on disk:

| | Dataset A | Dataset B |
|---|---|---|
| `screenshot_smart` events | 34,580 | 4,759 |
| JPEGs physically present | 2,489 | ~3,865 resolved |
| **Resolution rate** | **7.2%** | **81.2%** |

This is one of the most consequential findings from this audit — see
`day1_final_report.md` §10 and `failure_modes.md` for why the asymmetry
matters (an approach validated on A that assumes screenshots are mostly
unavailable would wrongly write off a signal that's actually mostly
*available* in B, the dataset that's actually being scored).
