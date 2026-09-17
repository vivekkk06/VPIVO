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

// --- Day-6 Module 1 vs Module 2 comparison --------------------------------
// Every field is copied verbatim by scripts/build_frontend_data.py from a Module 2
// artifact. React renders these; it never recomputes them.

export interface PooledMetrics {
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
}

export interface ModuleComparisonFile {
  module1: {
    name: string;
    status: string;
    canonical_pooled: PooledMetrics;
    control_matched: PooledMetrics;
    control_locked: PooledMetrics;
  };
  module2: {
    name: string;
    status: string;
    decision: string;
    best_candidate_key: string;
    best_matched: PooledMetrics;
    best_locked: PooledMetrics;
    f1_vs_canonical_locked: number;
    feature_sets: Record<string, {
      extra_features: string[];
      matched: PooledMetrics;
      locked: PooledMetrics;
    }>;
    content_drift_coverage: {
      transitions_with_drift_available: number;
      transitions_total: number;
      fraction: number;
      note: string;
    };
  };
  gate: {
    registered_before_candidates_were_scored: boolean;
    thresholds: Record<string, number | boolean>;
    source: string;
    checks: Record<string, boolean>;
    failed_gates: string[];
    deltas: Record<string, number>;
    robustness: {
      sessions_improved: number;
      sessions_degraded: number;
      sessions_unchanged: number;
      delta_f1_distribution: Record<string, number>;
    };
    concentration_check: {
      gain_survives_removing_top3: boolean;
      mean_session_f1_excluding_top3_baseline: number;
      mean_session_f1_excluding_top3_candidate: number;
    };
    machine_dominance_check: {
      gain_survives_removing_most_improved_operator: boolean;
      most_improved_operator: string;
      mean_delta_f1_overall: number;
      mean_delta_f1_excluding_most_improved_operator: number;
      n_operators: number;
    };
  };
  automation: {
    coverage: {
      total_executions: number;
      routing_eligible: number;
      observed_dominant_path_coverage: number;
      refused: number;
      reason_counts: Record<string, number>;
      metric_naming_note: string;
    };
    canonical_dominant_share: number;
    canonical_dominant_n: number;
    by_canonical_variant: Record<string, Record<string, number>>;
    dominant_refused: { n: number; reasons: Record<string, number>; explanation: string };
    post_action_expected_state_passed: boolean;
    post_action_detects_route_drift: boolean;
  };
  process_analysis: {
    effort_table: {
      process_id: string;
      readable_name: string;
      executions_F_p: number;
      total_observed_time_hours: number;
      average_duration_ms_AD_p: number;
      time_share_TS_p: number;
      cost_input_available: boolean;
      estimated_cost: null;
      missing_inputs: string[];
    }[];
    total_observed_time_hours: number;
    monetary_roi_statement: string;
    operator_table: {
      operator: string;
      executions: number;
      dominant: number;
      word_detour: number;
      rare_edge: number;
      dominant_path_share: number;
      dominant_share_95ci: [number, number];
      ci_contains_pooled_share: boolean;
    }[];
    operator_dispersion: {
      spread: number;
      chi_square: number;
      dof: number;
      chi_square_0_05_critical: number;
      differs_beyond_chance_at_0_05: boolean;
    };
    pareto_frontier: string[];
    pareto_matches_canonical: boolean;
    pareto_table: {
      process_id: string;
      readable_name: string;
      rank_canonical: number;
      impact: number;
      feasibility: number;
      opportunity_canonical: number;
      on_pareto_frontier: boolean;
      executions: number | null;
      time_share: number | null;
    }[];
    sensitivity: {
      n_scenarios: number;
      n_scenarios_hr_first: number;
      weighted_view: Record<string, { hr_rank: number; top_candidate_changed: boolean }>;
      pareto_view: { frontier: string[]; invariant_across_scenarios: boolean; why: string };
      comparison_note: string;
    };
  };
  dataset_b_review: {
    sampling: {
      deterministic: boolean;
      seed: number;
      blinded: boolean;
      blinding_note: string;
      population_boundaries: number;
      population_controls: number;
      sampled: number;
      sampled_boundaries: number;
      sampled_controls: number;
    };
    screenshot_availability: {
      points_with_a_nearest_screenshot: number;
      points_without: number;
      nearest_screenshot_file_missing_on_disk: number;
      delta_ms_distribution: { median: number | null };
    };
    review_status: string;
    dataset_b_rule: string;
  };
  /** Surrogate (vision-model) visual review of the same sample. Descriptive counts, not
   *  metrics; null when the review artifact is absent. */
  dataset_b_visual_review: DatasetBVisualReview | null;
}

export type VisualReviewLabelCounts = {
  A_CLEAR_CONTINUITY: number;
  B_CLEAR_BOUNDARY: number;
  C_AMBIGUOUS: number;
  D_UNAVAILABLE: number;
};

export interface DatasetBVisualReview {
  label: string;
  status: string;
  reviewer: string;
  human_review: string;
  seed: number;
  hash_verified_at_reveal: boolean;
  sample_size: number;
  screenshots_available: number;
  screenshots_unavailable: number;
  screenshots_recovered: number;
  counts: VisualReviewLabelCounts;
  counts_by_sample_type: {
    boundary_sample: VisualReviewLabelCounts;
    control_sample: VisualReviewLabelCounts;
  };
  boundary_samples_judgeable: number;
  control_samples_judgeable: number;
  boundary_sample_visual_support_rate: number | null;
  control_sample_visual_continuity_rate: number | null;
  ambiguous_total: number;
  not_metrics_note: string;
  decision: { outcome: string; statement: string; basis: string[]; module2_promotion: string };
  missing_cause: string | null;
}

export type ActionLogEntry = { step: string; detail: string; timestamp: string };

/** The execution state machine, mirrored from
 *  `procmine.integrations.execution_state`. UNKNOWN is not a failure: it means the
 *  outcome exists but this process does not know it, which is what a status lookup
 *  resolves. */
export type ExecutionStatus =
  | "PREPARED" | "AWAITING_CONFIRMATION" | "CONFIRMING"
  | "CONFIRMED" | "FAILED" | "UNKNOWN" | "REPLAYED";

/** Every mode is LOCAL. None of them reaches a real HR system. `http` is real HTTP to
 *  the separate local HR API simulator — a local integration, not a real target. */
export type IntegrationMode = "mock" | "browser" | "api_simulator" | "http";

/** Day-5 integration fields are optional throughout: the screens must still render
 *  against a response that does not carry them, rather than crashing on a field. */
export interface CheckpointPayload {
  checkpoint_token: string;
  route: string;
  note_field_id: string;
  note_text: string;
  confirm_button_id: string;
  confirmed: boolean;
  action_log: ActionLogEntry[];
  execution_id?: string;
  status?: ExecutionStatus;
  integration_mode?: IntegrationMode;
  integration_mode_label?: string;
}

export interface AutomationResultPayload {
  route: string;
  confirmed: boolean;
  action_log: ActionLogEntry[];
  execution_id?: string;
  status?: ExecutionStatus;
  integration_mode?: IntegrationMode;
  /** Present when the outcome is UNKNOWN or the integration failed. */
  error_type?: string;
  message?: string;
  status_url?: string;
}

export interface ApiSafeStop {
  error_type: string;
  message: string;
  action_log: ActionLogEntry[];
  execution_id?: string;
  status?: ExecutionStatus;
  integration_mode?: IntegrationMode;
}

/** `GET /api/executions/{execution_id}/status`. Carries note *length*, never the
 *  note itself -- the server does not persist the content. */
export interface ExecutionStatusPayload {
  execution_id: string;
  request_id: string;
  actor: string;
  process: string;
  route: string;
  integration_mode: IntegrationMode;
  status: ExecutionStatus;
  note_length: number;
  idempotency_key: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  history: { from: string; to: string; at: string }[];
  resolved_from_unknown: boolean;
  terminal: boolean;
  /** What the target itself recorded — `http` executions only; null otherwise. */
  target?: TargetStatusView | null;
}

/** The local HR API's own record of an execution, read-only. `lookup_error` is set
 *  when the status source could not be reached, in which case nothing else is. */
export interface TargetStatusView {
  source: string;
  found?: boolean;
  confirmation_state?: "PENDING" | "IN_PROGRESS" | "CONFIRMED" | null;
  state?: string | null;
  in_progress?: boolean;
  commit_count?: number | null;
  audit_ref?: string | null;
  last_error_type?: string | null;
  lookup_error?: string;
}

export interface IntegrationModeOption {
  id: IntegrationMode;
  label: string;
}

export interface IntegrationModesPayload {
  modes: IntegrationModeOption[];
  default: IntegrationMode;
  /** Deterministic failures for the in-process API simulator. */
  failure_modes: string[];
  /** Deterministic failures for the local HTTP integration (absent on older APIs). */
  http_failure_modes?: string[];
  note: string;
}

// --- Day 1-4 investigation views -------------------------------------------
// Built by scripts/build_frontend_data.py from the Day-1..Day-7 artifacts. Totals are
// copied, per-session rows are only counted or summed, and report-only figures carry
// the report they come from. React formats these values; it never derives them.

/** The six headline boundary metrics. `null` where an artifact does not carry one
 *  (the temporal baselines have no fragmentation figure). */
export interface BoundaryMetrics {
  precision: number | null;
  recall: number | null;
  f1: number | null;
  pct_gt_executions_fragmented: number | null;
  under_segmentation_rate: number | null;
  over_segmentation_rate: number | null;
}

export interface Day1Dataset {
  sessions: number;
  chunks: number;
  events: number;
  screenshot_dirs: number;
  ground_truth_files: number;
  sessions_with_ground_truth: number;
  multi_chunk_sessions: number;
  events_by_layer: Record<string, number>;
  screenshot_events: number;
  session_duration_seconds: { min: number; max: number; mean: number };
  n_applications: number;
}

export interface Day1Checks {
  sessions_with_out_of_order_pairs: number;
  out_of_order_pairs: number;
  malformed_json_lines: number;
  duplicate_event_ids: number;
  gt_manifest_mismatches: number;
  exact_duplicate_groups: number;
  semantic_duplicate_groups: number;
  sequential_duplicates: number;
  sequential_duplicates_by_type: Record<string, number>;
  chunk_identity_issues: number;
  timestamp_iso_mismatches: number;
  non_utc_timestamps: number;
  text_input_complete: {
    events: number;
    with_content: number;
    missing_or_empty: number;
    password_fields_with_plaintext: number;
    sessions_with_plaintext_password_fields: number;
  };
  clipboard_change: { events: number; empty_payload: number };
}

export type ExperimentStatus =
  | "REFERENCE" | "FAILED" | "PROMISING" | "REJECTED" | "NOT SELECTED"
  | "LOCKED" | "NOT PROMOTED" | "PASSED";

export interface ExperimentRecord {
  id: string;
  day: string;
  stage: string;
  name: string;
  approach: string;
  status: ExperimentStatus;
  result: string;
  failure_mode: string;
  decision: string;
  metrics: BoundaryMetrics | null;
  metrics_source: string;
}

export interface Day7Candidate {
  id: string;
  name: string;
  method: string;
  metrics: BoundaryMetrics;
  passes_all_gates: boolean;
  failed_gates: string[];
  failed_gate_labels: string[];
}

export interface Distribution5 {
  n: number;
  median: number;
  mean: number;
  min: number;
  max: number;
}

export interface InvestigationFile {
  day1: {
    datasets: { dataset_a: Day1Dataset; dataset_b: Day1Dataset };
    checks: { dataset_a: Day1Checks; dataset_b: Day1Checks };
  };
  day2: {
    problem: { n_sessions: number; n_transitions: number; n_gt_boundaries: number; n_gt_executions: number };
    locked_strategy: string;
    systems: Record<string, BoundaryMetrics>;
    protection: Record<string, {
      false_to_true_protection_ratio: number;
      gates_total: number;
      gates_failed: string[];
    }>;
    temporal_baselines: {
      tau_ms: number;
      temporal_only: BoundaryMetrics;
      temporal_and_context: BoundaryMetrics;
      temporal_or_context: BoundaryMetrics;
      temporal_or_context_predicted: number;
    };
    learned_classifier: { n_features: number; threshold: number; precision: number; recall: number; f1: number };
    v1_threshold_curve: (BoundaryMetrics & { threshold: number })[];
    day6: {
      hmm_only: BoundaryMetrics;
      ensemble_or: BoundaryMetrics;
      ensemble_and: BoundaryMetrics;
      complementarity: Record<string, number | string>;
      locked_reproduced_f1: number;
    };
    day7: {
      question: string;
      validation: string;
      decision: string;
      baseline_reproduced: boolean;
      gates: Record<string, number | boolean>;
      candidates: Day7Candidate[];
    };
    experiments: ExperimentRecord[];
    module2: {
      metrics: BoundaryMetrics;
      control_f1: number;
      f1_gain: number;
      required_gain: number;
      status: string;
    } | null;
  };
  day3: {
    process_metrics: Record<string, {
      execution_count: number;
      time_share: number;
      frequency_share: number;
      variant_count: number;
      dominant_variant_share: number;
      variant_entropy: number;
      automation_surface: number;
      user_count: number;
    }>;
    entropy_note: string;
  };
  day4: {
    question: string;
    thresholds: { min_distinct_browser_domains: number; min_browser_domain_coverage: number };
    summary: Record<"dataset_a" | "dataset_b", { n_sessions: number; n_healthy: number; n_degraded: number }>;
    agreement: {
      note: string;
      interpretation_caveat: string;
      poor_performance_cut_f1: number;
      poor_cut_derivation: string;
      flagged_f1: Distribution5;
      healthy_f1: Distribution5;
      flagged_under_segmentation: Distribution5;
      healthy_under_segmentation: Distribution5;
      flagged_over_segmentation: Distribution5;
      healthy_over_segmentation: Distribution5;
      flagged_pct_fragmented: Distribution5;
      healthy_pct_fragmented: Distribution5;
      confusion: { tp: number; fp: number; fn: number; tn: number };
      sensitivity: number;
      specificity: number;
    };
    flagged_sessions_a: {
      machine: string;
      coverage: number;
      distinct_domains: number;
      baseline_f1: number;
      baseline_under_segmentation: number;
    }[];
    machines_a: { label: string; sessions: number; flagged: number }[];
    machines_b: { label: string; sessions: number; flagged: number }[];
    limitations: string[];
  };
  /** Figures that exist only in a written report, with that report's path. */
  documented: Record<string, { value: string; source: string }>;
  note: string;
}

/** Day-7 engineering upgrade: model signal, browser status, production boundary.
 *  Every field is copied from a reports/day7 artifact by the adapter; the frontend
 *  computes none of it. */
export interface EngineeringUpgradeFile {
  model: {
    status: string;
    task: string;
    why_not_circular: string;
    leakage_control: string;
    n_executions: number;
    n_classes: number;
    behavioural_only_macro_f1: number;
    with_system_identity_macro_f1: number;
    stratified_baseline_macro_f1: number;
    identity_uplift: number;
    top_features: { feature: string; importance: number }[];
    finding: string;
    prohibited_use: string;
  };
  browser: {
    status: string;
    status_detail: string;
    target: string;
    not_connected_to_real_hr_system: boolean;
    confirmed: boolean | null;
    note_reached_dom: boolean | null;
    replay_refused: boolean | null;
    invalid_route_refused: boolean | null;
    empty_note_refused: boolean | null;
    prepare_seconds: number | null;
    confirm_seconds: number | null;
    automation_logic_unchanged: boolean;
  };
  production_boundary: {
    implemented: string[];
    requires_production_integration: string[];
  };
  segmentation_challenge: {
    decision: string;
    candidates_tested: number;
    validation: string;
    baseline_f1: number;
    baseline_fragmentation_pct: number;
    baseline_under_segmentation: number;
    best_candidate_key: string;
    best_candidate_label: string;
    best_candidate_f1: number;
    best_candidate_fragmentation_pct: number;
    best_candidate_under_segmentation: number;
    note: string;
  };
}
