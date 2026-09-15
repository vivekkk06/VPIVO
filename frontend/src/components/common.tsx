import type { ReactNode } from "react";
import { formatBytes } from "../utils/format";
import type { Meta } from "../types";

export function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="metric">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export function HealthBadge({ status }: { status: "healthy" | "degraded" | string }) {
  const degraded = status === "degraded";
  return (
    <span className={`badge ${degraded ? "bad" : "ok"}`}>
      {degraded ? "Instrumentation degraded" : "Healthy"}
    </span>
  );
}

export function Notice({
  kind,
  children,
}: {
  kind: "info" | "ok" | "warn" | "error";
  children: ReactNode;
}) {
  const role = kind === "error" ? "alert" : "status";
  return (
    <div className={`notice ${kind}`} role={role}>
      {children}
    </div>
  );
}

/**
 * Compact provenance panel. Every screen states which Day-1..Day-4
 * artifact its numbers came from, so a reviewer can trace any figure back
 * without reading the adapter.
 */
export function ProvenancePanel({
  meta,
  entries,
}: {
  meta: Meta | null;
  entries: { value: string; sourceKey: string }[];
}) {
  return (
    <details className="provenance">
      <summary>Data source / evidence</summary>
      <p className="small muted" style={{ marginTop: 10 }}>
        This screen renders values produced by the Day-1–Day-4 analytical
        pipeline and copied verbatim by <span className="mono">scripts/build_frontend_data.py</span>.
        Nothing shown here is recomputed in the browser.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Value shown</th>
              <th scope="col">Source artifact</th>
              <th scope="col" className="num">Size</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => {
              const src = meta?.canonical_sources?.[e.sourceKey];
              return (
                <tr key={e.value + e.sourceKey}>
                  <td>{e.value}</td>
                  <td className="mono small wrap-any">{src?.path ?? "Not available"}</td>
                  <td className="num small">{src ? formatBytes(src.bytes) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {meta ? (
        <p className="small muted" style={{ marginTop: 10 }}>
          Bundle generated {meta.generated_at} by <span className="mono">{meta.generator}</span>.
        </p>
      ) : null}
    </details>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="muted small">{children}</p>;
}
