import type { ReactNode } from "react";
import { screenMeta, type ScreenId, type ScreenScope } from "../navigation";
import { useBundle } from "./BundleContext";
import type { EagerBundle } from "../services/dataService";

/** The page top bar: where the reader is, what the page is for, which data it shows,
 *  and what kind of evidence it is.
 *
 *  Keeps the `<header><h2>/<p class="lede">/<p class="page-context">` structure the
 *  pages always had. The stage label and the status chips on the right come from the
 *  navigation metadata and the loaded bundle, so no page restates them by hand.
 */
export function PageHeader({
  screen,
  title,
  purpose,
  context,
}: {
  /** Navigation id; drives the stage label and the status chips. */
  screen?: ScreenId;
  title: string;
  purpose: ReactNode;
  /** Dataset / scope / status, e.g. "Dataset B · 21 ranked processes". */
  context?: ReactNode;
}) {
  const bundle = useBundle();
  const meta = screen ? screenMeta(screen) : null;
  const chips = meta ? statusChips(meta.scope, meta.mode, bundle) : [];

  return (
    <header className="topbar">
      <div className="topbar-main">
        {meta ? (
          <p className="eyebrow">
            <span className="mono">{meta.number}</span>
            <span aria-hidden="true"> · </span>
            <span>{meta.group}</span>
          </p>
        ) : null}
        <h2 id="page-title" tabIndex={-1}>{title}</h2>
        <p className="lede">{purpose}</p>
        {context ? <p className="small muted page-context">{context}</p> : null}
      </div>
      {chips.length ? (
        <dl className="topbar-status" aria-label="What this page shows">
          {chips.map((c) => (
            <div className="status-chip" key={c.label}>
              <dt>{c.label}</dt>
              <dd>{c.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </header>
  );
}

function statusChips(scope: ScreenScope, mode: string, bundle: EagerBundle | null) {
  const a = bundle?.instrumentation.dataset_a.summary.n_sessions;
  const b = bundle?.instrumentation.dataset_b.summary.n_sessions;
  const executions = bundle?.executionsIndex.length;
  const n = (v: number | undefined) => (v === undefined ? "—" : String(v));

  const data =
    scope === "A" ? { label: "Dataset A", value: `${n(a)} sessions · ground truth` }
      : scope === "B" ? { label: "Dataset B", value: `${n(b)} sessions · ${n(executions)} executions` }
        : scope === "AB" ? { label: "Datasets", value: `A ${n(a)} · B ${n(b)} sessions` }
          : { label: "Target", value: "Local HR prototype page" };
  const evidence = scope === "API"
    ? { label: "Mode", value: "Interactive · local only" }
    : { label: "Evidence", value: `${mode} · read-only` };
  return [data, evidence];
}
