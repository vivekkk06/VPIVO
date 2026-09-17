import type { ReactNode } from "react";
import type { ExperimentStatus } from "../types";

/**
 * The evidence vocabulary used across every screen. A reader should be able to tell,
 * without reading the paragraph around a number, what kind of claim it is:
 *
 *   CANONICAL     read from a locked, canonical artifact
 *   OBSERVED      counted directly in the logs
 *   INFERRED      a reasoned interpretation, not a recorded fact
 *   EXPERIMENTAL  from an experiment that did not change the canonical result
 *   NOT PROMOTED  an experiment that failed its pre-registered gate
 *   PROTOTYPE     a working local prototype, not a deployed system
 *   LIMITATION    a known weakness, stated rather than hidden
 *
 * The label is always text, so the meaning never depends on colour alone.
 */
export type EvidenceKind =
  | "canonical" | "observed" | "inferred" | "experimental"
  | "not-promoted" | "prototype" | "limitation";

const DEFAULT_LABEL: Record<EvidenceKind, string> = {
  canonical: "CANONICAL",
  observed: "OBSERVED",
  inferred: "INFERRED",
  experimental: "EXPERIMENTAL",
  "not-promoted": "NOT PROMOTED",
  prototype: "PROTOTYPE",
  limitation: "LIMITATION",
};

export function EvidenceBadge({ kind, label }: { kind: EvidenceKind; label?: string }) {
  return <span className={`evb evb-${kind}`}>{label ?? DEFAULT_LABEL[kind]}</span>;
}

/** Expandable provenance for one figure: where it comes from, what it measures, how it
 *  was produced, and what it cannot tell you. Collapsed by default so paths never
 *  crowd the page. */
export function EvidenceTrace({
  source,
  metric,
  method,
  limitations,
  summary = "View evidence",
}: {
  source: string | string[];
  metric?: ReactNode;
  method?: ReactNode;
  limitations?: ReactNode;
  summary?: string;
}) {
  const sources = Array.isArray(source) ? source : [source];
  return (
    <details className="trace">
      <summary>{summary}</summary>
      <dl>
        <div>
          <dt>Canonical source</dt>
          <dd>
            {sources.map((s) => (
              <span key={s} className="mono small wrap-any trace-src">{s}</span>
            ))}
          </dd>
        </div>
        {metric ? (<div><dt>Metric</dt><dd>{metric}</dd></div>) : null}
        {method ? (<div><dt>Method</dt><dd>{method}</dd></div>) : null}
        {limitations ? (<div><dt>Limitations</dt><dd>{limitations}</dd></div>) : null}
      </dl>
    </details>
  );
}

const STATUS_KIND: Record<ExperimentStatus, string> = {
  REFERENCE: "reference",
  FAILED: "rejected",
  REJECTED: "rejected",
  PROMISING: "promising",
  "NOT SELECTED": "neutral",
  LOCKED: "locked",
  "NOT PROMOTED": "rejected",
  PASSED: "neutral",
};

/** Outcome of one experiment in the reconstruction record. */
export function StatusTag({ status }: { status: ExperimentStatus }) {
  return <span className={`status-tag st-${STATUS_KIND[status] ?? "neutral"}`}>{status}</span>;
}
