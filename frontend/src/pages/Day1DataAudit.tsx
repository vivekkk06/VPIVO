import type { ReactNode } from "react";
import type { EagerBundle } from "../services/dataService";
import type { Navigate } from "../navigation";
import type { Day1Checks, Day1Dataset } from "../types";
import { PageHeader } from "../components/PageHeader";
import { Notice, ProvenancePanel } from "../components/common";
import { EvidenceBadge, EvidenceTrace, type EvidenceKind } from "../components/evidence";
import { formatInt, formatMinutes } from "../utils/format";

/**
 * Day 1 -- the raw-data audit. Shows what was wrong with the logs before any
 * segmentation was attempted, and which engineering decision each finding forced.
 * Every figure comes from investigation.json; figures that exist only in a written
 * report carry that report's path.
 */

interface Finding {
  id: string;
  kind: EvidenceKind;
  title: string;
  body: ReactNode;
  consequence: string;
  sources: string[];
  method: string;
  limitations: string;
}

function DatasetCard({ name, tagline, gt, d }: {
  name: string; tagline: string; gt: boolean; d: Day1Dataset;
}) {
  const rows: [string, ReactNode][] = [
    ["Sessions", formatInt(d.sessions)],
    ["Chunk files", <>{formatInt(d.chunks)} <span className="muted small">· {d.multi_chunk_sessions} of {d.sessions} sessions span 2+ files</span></>],
    ["Events", formatInt(d.events)],
    ["Screenshot references", formatInt(d.screenshot_events)],
    ["Ground truth", gt ? `${d.sessions_with_ground_truth} of ${d.sessions} sessions` : "None"],
    ["Session length", `${formatMinutes(d.session_duration_seconds.min)} – ${formatMinutes(d.session_duration_seconds.max)}`],
    ["Applications seen", formatInt(d.n_applications)],
  ];
  return (
    <article className={`dataset-card ${gt ? "has-gt" : "no-gt"}`}>
      <header className="dataset-card-head">
        <h4>{name}</h4>
        <span className={`gt-flag ${gt ? "yes" : "no"}`}>{gt ? "Ground truth available" : "No ground truth"}</span>
      </header>
      <p className="small muted">{tagline}</p>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd className="mono">{v}</dd></div>
        ))}
      </dl>
    </article>
  );
}

function findings(A: Day1Dataset, B: Day1Dataset, ca: Day1Checks, cb: Day1Checks,
                  doc: Record<string, { value: string; source: string }>): Finding[] {
  const tic = ca.text_input_complete;
  return [
    {
      id: "order", kind: "observed",
      title: "Raw event order is not chronological",
      body: <>
        <strong>{ca.sessions_with_out_of_order_pairs} of {A.sessions}</strong> Dataset-A sessions
        and <strong>{cb.sessions_with_out_of_order_pairs} of {B.sessions}</strong> Dataset-B sessions
        have events out of timestamp order in the raw files ({formatInt(ca.out_of_order_pairs)} and{" "}
        {formatInt(cb.out_of_order_pairs)} adjacent pairs). {doc.raw_order_screenshot_share.value} of
        the near-simultaneous inversions involve an asynchronous screenshot event.
      </>,
      consequence: "Every loader sorts by timestamp_ms. File order is never trusted.",
      sources: ["reports/day1/validation_dataset_a.json", "reports/day1/validation_dataset_b.json",
                doc.raw_order_screenshot_share.source],
      method: "Adjacent events compared in raw file order, session by session.",
      limitations: "Counts inverted pairs, not how far each event was displaced.",
    },
    {
      id: "chunks", kind: "observed",
      title: "Sessions are split across chunk files",
      body: <>
        <strong>{A.multi_chunk_sessions} of {A.sessions}</strong> Dataset-A sessions span two or more
        chunk files ({B.multi_chunk_sessions} of {B.sessions} in Dataset B). In one place an event
        names the wrong chunk ({ca.chunk_identity_issues} identity issue), and the same point
        carries the most negative gap in the data ({doc.negative_gap_minimum.value}).
      </>,
      consequence: "Chunks are joined per session. A chunk edge is never a process boundary.",
      sources: ["reports/day1/dataset_inventory.json", "reports/day1/full_audit_dataset_a.json",
                doc.negative_gap_minimum.source],
      method: "Chunk count per session from the inventory; correlation.chunk_id compared with the file each event was read from.",
      limitations: "The identity issue is a single event; its cause is not established.",
    },
    {
      id: "gaps", kind: "observed",
      title: "Recorded inter-event gaps can be negative",
      body: <>
        {doc.negative_gap_events.value} have <span className="mono">ms_since_last_event</span> below
        −1,000 ms. The field cannot be used as a pause signal.
      </>,
      consequence: "Pauses are recomputed from sorted timestamp_ms; ms_since_last_event is not used.",
      sources: [doc.negative_gap_events.source, "src/procmine/segmentation/features.py"],
      method: "Distribution of the logged field across all Dataset-A events.",
      limitations: "Reported for Dataset A, where the audit was run in full.",
    },
    {
      id: "app-switch", kind: "observed",
      title: "Most app_switch records are repeats",
      body: <>
        Dataset A has <strong>{formatInt(ca.sequential_duplicates)}</strong> sequential duplicate
        records; <strong>{formatInt(ca.sequential_duplicates_by_type.app_switch ?? 0)}</strong> of them
        are <span className="mono">app_switch</span> (about {doc.app_switch_duplication.value} of all
        app_switch events). Byte-identical duplicates: {ca.exact_duplicate_groups}. Dataset B has{" "}
        {formatInt(cb.sequential_duplicates)} sequential duplicates, {cb.sequential_duplicates_by_type.app_switch ?? 0} of
        them app_switch.
      </>,
      consequence: "Reported, not dropped. Collapsing repeats is a segmentation decision, made and tested on Day 2.",
      sources: ["reports/day1/full_audit_dataset_a.json", "reports/day1/full_audit_dataset_b.json",
                doc.app_switch_duplication.source],
      method: "Consecutive records with the same type and payload, per session.",
      limitations: "A repeat may still carry timing information; that is why nothing was deleted.",
    },
    {
      id: "browser-error", kind: "observed",
      title: "browser_error is double-logged",
      body: <>
        <strong>{ca.semantic_duplicate_groups}</strong> groups in Dataset A are the same event logged
        twice at the same millisecond under different event ids ({doc.semantic_duplicates_browser_error.value} of
        them <span className="mono">browser_error</span>). Dataset B: {cb.semantic_duplicate_groups} groups.
      </>,
      consequence: "Treated as a logging defect: never used as a feature without de-duplication.",
      sources: ["reports/day1/full_audit_dataset_a.json", doc.semantic_duplicates_browser_error.source],
      method: "Same session, timestamp, type and payload, but different event_id.",
      limitations: "Only exact semantic repeats are detected.",
    },
    {
      id: "screenshots", kind: "limitation",
      title: "Screenshot availability differs by dataset",
      body: <>
        Only <strong>{doc.screenshot_resolution_a.value}</strong> of Dataset-A screenshot references
        resolve to a file on disk ({doc.screenshots_resolved_a.value} of {formatInt(A.screenshot_events)}).
        In Dataset B it is <strong>{doc.screenshot_resolution_b.value}</strong> ({doc.screenshots_resolved_b.value} of{" "}
        {formatInt(B.screenshot_events)}).
      </>,
      consequence: "Screenshots are optional, dataset-specific evidence. No pipeline step requires one.",
      sources: [doc.screenshot_resolution_a.source, "src/procmine/paths.py"],
      method: "Each screenshot reference resolved against the chunk's own and sibling directories.",
      limitations: "The Dataset-B figure is approximate in the source report.",
    },
    {
      id: "text-input", kind: "limitation",
      title: "Typed and pasted text is not reliably recorded",
      body: <>
        {tic.with_content} of {tic.events} Dataset-A <span className="mono">text_input_complete</span> events
        carry content ({tic.missing_or_empty} empty). Clipboard events carry no text at all:{" "}
        {formatInt(ca.clipboard_change.empty_payload)} of {formatInt(ca.clipboard_change.events)} in
        Dataset A and {formatInt(cb.clipboard_change.empty_payload)} of {formatInt(cb.clipboard_change.events)} in
        Dataset B have an empty payload.
      </>,
      consequence: "Text is reconstructed cautiously. What an operator pastes is treated as unobservable, so the HR prototype takes the note from the operator.",
      sources: ["reports/day1/full_audit_dataset_a.json", "reports/day1/full_audit_dataset_b.json",
                "reports/day1/text_input_quality.md"],
      method: "Per-event content check and per-type payload emptiness, summed over sessions.",
      limitations: "Counts only. No text value is read into this view.",
    },
    {
      id: "ground-truth", kind: "observed",
      title: "Ground truth is consistent, with one gap",
      body: <>
        <strong>{doc.gt_executions.value}</strong> executions were rebuilt from the ground-truth event
        stream across {A.sessions} sessions, with {ca.gt_manifest_mismatches} mismatches against the
        manifest. One abandoned suspension ({doc.gt_abandoned_suspension.value}) appears only in the raw
        stream, not in the manifest. Timestamps: {ca.timestamp_iso_mismatches} ISO/epoch mismatches,{" "}
        {ca.non_utc_timestamps} non-UTC values.
      </>,
      consequence: "Ground truth is used as evidence to evaluate against, never as pipeline input.",
      sources: [doc.gt_executions.source, "reports/day1/validation_dataset_a.json"],
      method: "Executions rebuilt from gt.jsonl and compared field by field with gt_manifest.json.",
      limitations: "Consistency is not correctness: both files come from the same simulator.",
    },
    {
      id: "password", kind: "limitation",
      title: "Password fields were not redacted",
      body: <>
        <strong>{tic.password_fields_with_plaintext}</strong> Dataset-A text-input events from password
        fields (in {tic.sessions_with_plaintext_password_fields} sessions) contain the typed value in
        plain text, although the capture settings say password fields are redacted. Dataset B:{" "}
        {cb.text_input_complete.password_fields_with_plaintext}. The values are synthetic test
        credentials. None is shown, copied or stored anywhere in this project.
      </>,
      consequence: "Recorded as a governance risk for any real deployment. Only the count is carried.",
      sources: ["reports/day1/full_audit_dataset_a.json", "reports/day1/text_input_quality.md"],
      method: "Events flagged is_password_field with a non-empty final_text, counted per session.",
      limitations: "The count is all this view knows; the values never enter the bundle.",
    },
  ];
}

const DECISIONS: { from: string; to: string; why: string }[] = [
  { from: "Chunk boundary", to: "Not treated as a process boundary",
    why: "Sessions are joined across chunk files before any segmentation." },
  { from: "Event order", to: "Always sorted by timestamp",
    why: "Raw order is wrong in every session; original sequence numbers are kept." },
  { from: "Screenshots", to: "Dataset-specific, optional evidence",
    why: "Availability differs by an order of magnitude between the datasets." },
  { from: "Text input", to: "Reconstructed cautiously",
    why: "final_text is a hint, and pasted content is not recorded at all." },
  { from: "Duplicates", to: "Reported, not deleted",
    why: "Collapsing repeats changes what one operation means, so it belongs in Day 2." },
  { from: "Ground truth", to: "Evidence, not an unquestionable oracle",
    why: "Cross-checked file against file, and used only to evaluate." },
  { from: "Sensitive values", to: "Never copied",
    why: "The password finding is carried as a count only." },
];

export default function Day1DataAudit({ bundle, navigate }: { bundle: EagerBundle; navigate: Navigate }) {
  const { investigation, meta } = bundle;
  const { datasets, checks } = investigation.day1;
  const doc = investigation.documented;
  const A = datasets.dataset_a;
  const B = datasets.dataset_b;
  const ca = checks.dataset_a;
  const cb = checks.dataset_b;
  const cards = findings(A, B, ca, cb, doc);

  const timeline: [string, string, string, string][] = [
    ["The raw files look time-ordered.",
     "Compare neighbouring timestamps in file order, in every session.",
     `${ca.sessions_with_out_of_order_pairs}/${A.sessions} sessions contain inverted pairs; most involve screenshot capture latency.`,
     "Sort by timestamp_ms in every loader."],
    ["Sessions are stored as several chunk files.",
     "Count chunks per session; check each event's chunk id against its file.",
     `${A.multi_chunk_sessions}/${A.sessions} sessions span 2+ files; one event names the wrong chunk.`,
     "Join chunks per session. Chunk edges never become boundaries."],
    ["The logged gap field looks like a ready pause signal.",
     "Check its distribution against sorted timestamps.",
     `${doc.negative_gap_events.value} are below −1,000 ms.`,
     "Recompute pauses from sorted timestamps."],
    ["text_input_complete looks like a clean record of what was typed.",
     "Check content presence and the password flag on every event.",
     `${ca.text_input_complete.with_content}/${ca.text_input_complete.events} carry content; ${ca.text_input_complete.password_fields_with_plaintext} password-field values are in plain text.`,
     "Treat text as a hint; carry the password finding as a count only."],
    ["Ground truth comes as two files that should agree.",
     "Rebuild executions from the stream and compare with the manifest.",
     `${doc.gt_executions.value} executions, ${ca.gt_manifest_mismatches} mismatches, one suspension missing from the manifest.`,
     "Use ground truth to evaluate only, with the gap documented."],
  ];

  return (
    <>
      <PageHeader
        screen="data-audit"
        title="Day 1 · Data Audit"
        purpose="Before building anything on the logs, check what they actually contain: ordering, duplicates, missing evidence, ground-truth consistency and sensitive fields. Each finding below changed a later engineering decision."
        context="Dataset A (with ground truth) + Dataset B (without) · raw-data audit"
      />

      <section className="panel" aria-labelledby="d1-overview">
        <div className="panel-head">
          <h3 id="d1-overview">A · Dataset overview</h3>
          <EvidenceBadge kind="observed" />
        </div>
        <div className="grid cols-2">
          <DatasetCard name="Dataset A" gt d={A}
            tagline="Used to design and measure segmentation, because every session has labelled executions." />
          <DatasetCard name="Dataset B" gt={false} d={B}
            tagline="Used for process discovery and the automation decision. Its segments are never scored as correct or incorrect." />
        </div>
        <EvidenceTrace
          source={["reports/day1/dataset_inventory.json", "reports/day1/profile_dataset_a.json",
                   "reports/day1/profile_dataset_b.json", "reports/day1/full_audit_dataset_a.json",
                   "reports/day1/full_audit_dataset_b.json"]}
          metric="Session, chunk, event and screenshot-reference counts per dataset."
          method="Inventory of the files on disk plus a full parse of every event."
          limitations="The raw datasets are not part of the repository or of this bundle; only these totals are."
        />
      </section>

      <section className="panel" aria-labelledby="d1-findings">
        <div className="panel-head">
          <h3 id="d1-findings">B · Data quality findings</h3>
          <p className="small muted">Stated as measured. No value from a sensitive field is shown.</p>
        </div>
        <ul className="finding-grid">
          {cards.map((f) => (
            <li key={f.id} className={`finding finding-${f.kind}`}>
              <div className="finding-head">
                <EvidenceBadge kind={f.kind} />
                <h4>{f.title}</h4>
              </div>
              <p className="finding-body">{f.body}</p>
              <p className="finding-consequence"><span className="k">Consequence</span> {f.consequence}</p>
              <EvidenceTrace source={f.sources} method={f.method} limitations={f.limitations} />
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="d1-changed">
        <h3 id="d1-changed">C · What changed because of this</h3>
        <ul className="decision-grid">
          {DECISIONS.map((d) => (
            <li key={d.from} className="decision-card">
              <span className="decision-from">{d.from}</span>
              <span className="decision-arrow" aria-hidden="true">→</span>
              <span className="decision-to">{d.to}</span>
              <span className="decision-why small muted">{d.why}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="d1-timeline">
        <h3 id="d1-timeline">D · Investigation timeline</h3>
        <p className="small muted">
          How each finding was reached: an assumption, the check that tested it, what the check
          found, and the engineering decision it forced.
        </p>
        <div className="table-scroll">
          <table className="otfd" aria-label="Observation, test, finding and decision">
            <thead>
              <tr>
                <th scope="col">Observation</th>
                <th scope="col">Test</th>
                <th scope="col">Finding</th>
                <th scope="col">Engineering decision</th>
              </tr>
            </thead>
            <tbody>
              {timeline.map((row) => (
                <tr key={row[0]}>
                  {row.map((cell, i) => (
                    <td key={i} data-label={["Observation", "Test", "Finding", "Engineering decision"][i]}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Notice kind="info">
        <strong>Where this leads.</strong> With ordering, chunking and text evidence understood, Day 2
        builds the segmentation on sorted timestamps and context changes, and measures it against
        Dataset A&rsquo;s ground truth.{" "}
        <button className="linkish" onClick={() => navigate("reconstruction")}>
          Continue to Day 2 · Reconstruction
        </button>
      </Notice>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Dataset inventory", sourceKey: "day1_inventory" },
          { value: "Per-session audit (Dataset A)", sourceKey: "day1_audit_a" },
          { value: "Per-session audit (Dataset B)", sourceKey: "day1_audit_b" },
          { value: "Validation checks (Dataset A)", sourceKey: "day1_validation_a" },
          { value: "Validation checks (Dataset B)", sourceKey: "day1_validation_b" },
        ]}
      />
    </>
  );
}
