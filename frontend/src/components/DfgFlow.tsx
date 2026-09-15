import type { DfgEdge } from "../types";
import { formatNumber } from "../utils/format";

/**
 * Lightweight directly-follows visualisation.
 *
 * Renders ONLY the edges present in the artifact — one row per recorded
 * transition, with the connector thickness proportional to that edge's own
 * count. No topology is inferred: no node is placed, merged, or connected
 * beyond what `top_edges` literally states, and no edge the artifact did not
 * persist is drawn.
 *
 * Text is HTML (so long Japanese system names wrap and stay selectable and
 * accessible); SVG is used only for the arrow itself.
 */
export function DfgFlow({
  edges,
  shown,
  total,
}: {
  edges: DfgEdge[];
  shown: number;
  total: number;
}) {
  if (!edges.length) return null;
  const maxCount = Math.max(...edges.map((e) => e.count));
  const isPartial = shown < total;

  return (
    <div className="dfg-flow">
      <p className="small muted" style={{ marginTop: 0 }}>
        {isPartial ? (
          <>
            Showing the <strong>{shown}</strong> transitions the artifact persisted, of{" "}
            <strong>{total}</strong> recorded. This is the available subset, not the complete
            graph.
          </>
        ) : (
          <>All {total} recorded transitions for this process.</>
        )}
      </p>

      <ul className="flow-list">
        {edges.map((e, i) => {
          const weight = 2 + Math.round((e.count / maxCount) * 8);
          return (
            <li key={`${e.source}->${e.target}-${i}`} className="flow-row">
              <span className="flow-node from" title={e.source}>
                {e.source}
              </span>

              <span className="flow-connector" aria-hidden="true">
                <svg width="100%" height="24" viewBox="0 0 120 24" preserveAspectRatio="none">
                  <line
                    x1="0"
                    y1="12"
                    x2="104"
                    y2="12"
                    stroke="var(--accent)"
                    strokeWidth={weight}
                    strokeLinecap="round"
                    opacity="0.75"
                  />
                  <polygon points="104,5 118,12 104,19" fill="var(--accent)" opacity="0.9" />
                </svg>
              </span>

              <span className="flow-node to" title={e.target}>
                {e.target}
              </span>

              <span className="flow-metric mono">
                {e.count}
                <span className="muted"> obs</span>
              </span>
              <span className="flow-metric mono">
                P {formatNumber(e.probability, 3)}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="small muted">
        Connector thickness is proportional to each transition&rsquo;s own observed count.
        Counts and probabilities are copied from the Day-3 artifact; nothing here is recomputed.
      </p>
    </div>
  );
}
