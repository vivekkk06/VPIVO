/**
 * Presentation-level formatting only. Nothing here derives an analytical
 * value -- these functions reshape numbers already present in the bundle.
 */

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "Not available";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)} s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Offset from an execution's own start, for the replay timeline. */
export function formatOffset(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const mm = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const ss = String(totalSeconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** `value` is already a 0..1 share in the source artifacts. */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "Not available";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value == null || !Number.isFinite(value)) return "Not available";
  return value.toFixed(digits);
}

/** Integer with thousands separators, fixed to en-US so the output never depends on
 *  the viewer's locale. */
export function formatInt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Not available";
  return Math.round(value).toLocaleString("en-US");
}

/** A 0..100 percentage that the artifact already stores as a percentage. */
export function formatPct100(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

/** Seconds shown as minutes, one decimal. */
export function formatMinutes(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "Not available";
  return `${(seconds / 60).toFixed(1)} min`;
}

export function formatTimestamp(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "Not available";
  return new Date(ms).toISOString().replace("T", " ").replace(".000Z", "Z");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
