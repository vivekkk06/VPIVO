/**
 * Types mirroring reports/day5/data_contract.md.
 *
 * Every field here is either copied verbatim from a Day-1..Day-4 artifact
 * by scripts/build_frontend_data.py, or is a field that script marks as
 * DERIVED (a count, a dict lookup, or a key lifted from a mapping).
 * Nothing in the frontend computes an analytical value.
 */

export interface Meta {
  generated_at: string;
  generator: string;
  canonical_sources: Record<string, { path: string; bytes: number }>;
  outputs: Record<string, number>;
  not_available: string[];
}

export interface SessionRow {
  session_id: string;
  dataset: "dataset_a" | "dataset_b"; // DERIVED
  operator: string; // DERIVED
  n_events: number;
  n_events_with_browser_domain: number;
  browser_domain_coverage: number;
  n_distinct_browser_domains: number;
  status: "healthy" | "degraded";
  warnings: string[];
  n_executions: number | null; // DERIVED; null for Dataset A (not measured)
}

/**
 * A persisted step inside an execution. This is NOT an individual raw
 * event -- `n_events` says how many raw events the step covers. The raw
 * per-event stream is not part of the frontend bundle.
 */
export interface OrderedStep {
  system: string | null;
  interaction_category: string;
  n_events: number;
  start_ms: number;
  end_ms: number;
  dominant_event_types: [string, number][];
}

export interface ExecutionIndexRow {
  execution_id: string;
  session_id: string;
  operator: string;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  event_count: number;
  dominant_context: string;
  applications?: string[];
  process_readable_name?: string; // DERIVED
}

export interface Execution extends ExecutionIndexRow {
  ordered_steps: OrderedStep[];
}

export interface Distribution {
  n?: number;
  mean?: number;
  median?: number;
  p25?: number;
  p75?: number;
  min?: number;
  max?: number;
}

export interface ProcessRow {
  process_id: string;
  readable_name: string;
  excluded_from_ranking: boolean;
  execution_count: number;
  n_variants: number;
  dominant_variant_share: number;
  frequency_by_operator: Record<string, number>;
  event_count_distribution: Distribution;
  duration_ms_distribution: Distribution;
  total_duration_ms: number;
  total_human_hours: number;
  avg_manual_event_share: number;
  n_distinct_interaction_categories: number;
  avg_systems_touched_per_execution: number;
}

export interface VariantRow {
  process_id: string; // DERIVED (lifted from source dict key)
  readable_name: string; // DERIVED
  signature: string[];
  frequency: number;
  avg_duration_ms: number;
}

export interface OpportunityRow {
  rank: number;
  process_id: string;
  readable_name: string;
  impact: number;
  feasibility: number;
  opportunity: number;
  pareto_status: string | null;
  median_rank: number | null;
  best_rank: number | null;
  worst_rank: number | null;
  rank_range: number | null;
}

export interface SensitivityScenario {
  hr_rank: number;
  top5: string[];
  spearman_vs_default: number;
  top_candidate_changed: boolean;
}

export interface RankingComparisonRow {
  process_id: string;
  readable_name: string;
  rank_case_a: number;
  rank_case_b: number | null;
  rank_delta: number | null;
  impact_a: number; impact_b: number | null;
  feasibility_a: number; feasibility_b: number | null;
  opportunity_a: number; opportunity_b: number | null;
  present_in_case_b: boolean;
}

export interface InstrumentationSensitivityFile {
  question: string;
  method: string;
  no_ground_truth_note: string;
  excluded_sessions: string[];
  executions_total: number;
  executions_removed: number;
  executions_kept: number;
  top_candidate_case_a: string;
  top_candidate_case_b: string;
  top_candidate_unchanged: boolean;
  pareto_case_a: boolean;
  pareto_case_b: boolean;
  sensitivity_summary_case_a: { n_scenarios: number; n_hr_first: number; mean_kendall_tau_vs_default: number };
  sensitivity_summary_case_b: { n_scenarios: number; n_hr_first: number; mean_kendall_tau_vs_default: number };
  ranking_comparison: RankingComparisonRow[];
  note: string;
}

export interface OpportunitiesFile {
  canonical_source: string;
  canonical_note: string;
  pareto_frontier: {
    processes: string[]; // readable_names, not process_ids
    n_frontier: number;
    n_total: number;
    hr_on_frontier: boolean;
  };
  sensitivity_summary?: {
    n_scenarios: number;
    n_hr_first: number;
    mean_kendall_tau_vs_default: number;
  };
  /** Per-scenario detail, verbatim from problem2_audit_results.json. */
  sensitivity_scenarios?: Record<string, SensitivityScenario>;
  ranking: OpportunityRow[];
}

export interface HealthPerSession {
  session_id: string;
  n_events: number;
  n_events_with_browser_domain: number;
  browser_domain_coverage: number;
  n_distinct_browser_domains: number;
  status: "healthy" | "degraded";
  warnings: string[];
}

export interface HealthFile {
  dataset: string;
  summary: {
    n_sessions: number;
    n_healthy: number;
    n_degraded: number;
    degraded_session_ids: string[];
    thresholds: {
      min_distinct_browser_domains: number;
      min_browser_domain_coverage: number;
    };
  };
  per_session: HealthPerSession[];
  by_machine: Record<string, { n: number; n_degraded: number; sessions: string[] }>;
}

export interface InstrumentationFile {
  dataset_a: HealthFile;
  dataset_b: HealthFile;
  note: string;
}

export interface DatasetAMetrics {
  strategy: string;
  pooled: {
    precision: number;
    recall: number;
    f1: number;
    n_gt_boundaries: number;
    n_predicted: number;
    over_segmentation_rate: number;
    under_segmentation_rate: number;
    n_gt_executions_total: number;
    n_gt_executions_fragmented: number;
    pct_gt_executions_fragmented: number;
  };
  per_session: Record<string, Record<string, number>>;
  note: string;
}

export interface DfgEdge {
  source: string;
  target: string;
  count: number;
  probability: number;
}

export interface HrDominantVariantAnalysis {
  n_executions?: number;
  form_input_method_distribution?: Record<string, number>;
  click_target_frequency?: Record<string, number>;
  form_field_frequency?: Record<string, number>;
  route_visit_frequency?: Record<string, number>;
  n_distinct_routes_per_execution?: { mean?: number; max?: number; median?: number };
  [key: string]: unknown;
}

export interface HrPayrollFile {
  dominant_path: {
    hr_process_id: string;
    n_hr_executions_total: number;
    variant_split: Record<string, { n: number; share: number }>;
    route_id_prefix_correspondence?: Record<string, string>;
    dominant_variant_analysis?: HrDominantVariantAnalysis;
    word_detour_documents_opened?: Record<string, number>;
    [key: string]: unknown;
  };
  variant_split: Record<string, { n: number; share: number }>;
  dfg: {
    n_edges: number;
    top_edges: DfgEdge[];
    self_loops: DfgEdge[];
    start_activities: Record<string, number>;
  };
  similarity_investigation: Record<string, unknown>;
  note: string;
}

// --- HR automation API ----------------------------------------------------

export interface CheckpointPayload {
  checkpoint_token: string;
  route: string;
  note_field_id: string;
  note_text: string;
  confirm_button_id: string;
  confirmed: boolean;
  action_log: { step: string; detail: string; timestamp: string }[];
}

export interface AutomationResultPayload {
  route: string;
  confirmed: boolean;
  action_log: { step: string; detail: string; timestamp: string }[];
}

export interface ApiSafeStop {
  error_type: string;
  message: string;
  action_log: { step: string; detail: string; timestamp: string }[];
}
