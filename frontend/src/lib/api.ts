/**
 * A typed client for the QScope API.
 *
 * The interface never computes anything the engine could compute: every number on
 * screen comes from one of these calls, and every response keeps the provenance
 * the server attached to it (`mode`, `backend`, `plan`, `seed`, `shots`, timing,
 * memory).  That is what makes the "SIMULATED / NOISY SIMULATION / HARDWARE
 * ESTIMATE" labelling trustworthy rather than decorative.
 */

export type Mode = "SIMULATED" | "NOISY SIMULATION" | "REAL HARDWARE";
export type Backend = "auto" | "statevector" | "density_matrix" | "trajectory";
export type OptimizerLevel = "safe" | "standard" | "aggressive";

export interface CircuitSource {
  circuit?: CircuitDocument | Record<string, unknown> | null;
  qasm?: string | null;
  algorithm?: string | null;
  algorithm_kwargs?: Record<string, unknown>;
  num_qubits?: number | null;
  num_clbits?: number | null;
  name?: string | null;
}

export interface CircuitOperation {
  name: string;
  targets: number[];
  params: number[];
  controls: number[];
  control_values?: number[] | null;
  classical_targets?: number[];
  condition?: { clbit: number; value: number } | null;
  kind: string;
  label: string;
  opid: string;
  metadata?: Record<string, unknown>;
}

export interface Resources {
  num_qubits: number;
  num_clbits: number;
  operations: number;
  gates: number;
  two_qubit_gates: number;
  measurements: number;
  resets: number;
  barriers: number;
  depth: number;
  parameters: number[];
  histogram: Record<string, number>;
  is_clifford: boolean;
  [key: string]: unknown;
}

export interface CircuitDocument {
  format: string;
  version: string;
  name: string;
  num_qubits: number;
  num_clbits: number;
  operations: CircuitOperation[];
  resources: Resources;
  diagram: string;
  qasm: string;
  metadata: Record<string, unknown>;
}

export interface Plan {
  backend: string;
  backend_label: string;
  representation: string;
  exact: boolean;
  num_qubits: number;
  shots: number;
  estimated_bytes: number;
  estimated_mb: number;
  estimated_peak_mb: number;
  budget_mb: number;
  safe_max_qubits: number;
  blocked: boolean;
  warnings: string[];
  notes: string[];
  auto_selected: boolean;
  /** Where the memory budget came from: an explicit value, the environment, or the host. */
  budget?: { budget_mb: number; source: string };
}

export interface NoiseSpec {
  name?: string;
  params?: Record<string, number>;
  channels?: Array<{
    kind: string;
    params: Record<string, number>;
    scope?: string;
    qubits?: number[] | null;
    after_gates?: string[] | null;
    label?: string;
    approximate?: boolean;
  }>;
  readout_error?: number;
  one_qubit_gate_error?: number;
  two_qubit_gate_error?: number;
  multi_qubit_gate_error?: number;
  idle_error?: number;
  calibrated?: boolean;
  description?: string;
  scale?: number | null;
}

export interface EntanglementPair {
  a: number;
  b: number;
  concurrence: number;
  entanglement_of_formation: number;
  negativity: number;
}

export interface EntanglementReport {
  status: string;
  method: string;
  summary: string;
  pairs: EntanglementPair[];
  max_concurrence: number;
  per_qubit_entropy: Array<{ qubit: number; entanglement_entropy: number; entangled_with_rest: boolean }>;
  pairwise_concurrence_matrix?: number[][];
  limitations: string[];
  representation?: string;
  [key: string]: unknown;
}

export interface StateMetrics {
  num_qubits?: number;
  purity?: number;
  entropy?: number;
  max_entropy?: number;
  normalized_entropy?: number;
  linear_entropy?: number;
  participation_ratio?: number;
  support_size?: number;
  dominant_basis?: string;
  dominant_probability?: number;
  coherence_l1?: number;
  bloch?: Array<{ qubit: number; x: number; y: number; z: number; length?: number; theta?: number; phi?: number }>;
  pauli_expectations?: Record<string, number>;
  entanglement_status?: string;
  entangled?: boolean;
  entanglement?: EntanglementReport;
  entanglement_limitations?: string[];
  [key: string]: unknown;
}

export interface SimulationResult {
  circuit_name: string;
  circuit: Record<string, unknown>;
  plan: Plan;
  mode: Mode;
  backend: string;
  shots: number;
  seed: number;
  counts: Record<string, number>;
  ideal_probabilities: Record<string, number>;
  reference_probabilities: Record<string, number> | null;
  sampled_probabilities: Record<string, number>;
  measured_qubits: number[];
  metrics: StateMetrics;
  ideal_metrics: StateMetrics | null;
  fidelity_vs_ideal: number | null;
  trace_distance_vs_ideal: number | null;
  noise: Record<string, unknown> & { name?: string; description?: string; channels?: unknown[] };
  timing: Record<string, number>;
  memory: Record<string, number>;
  warnings: string[];
  notes: string[];
  shot_records: Array<Record<string, unknown>>;
  timestamp: string;
  solution_register: string | null;
  extra: Record<string, unknown>;
  statevector?: Record<string, unknown> | null;
  density_matrix?: Record<string, unknown> | null;
}

export interface SimulationResponse {
  result: SimulationResult;
  circuit: CircuitDocument;
  plan: Plan;
  experiment_id: string | null;
}

export interface TraceStep {
  index: number;
  operation: Record<string, unknown>;
  kind: string;
  name: string;
  display: string;
  targets: number[];
  controls: number[];
  params: number[];
  layer: number;
  seconds: number;
  cumulative_seconds: number;
  state: {
    num_qubits: number;
    dimension: number;
    norm: number;
    is_normalized: boolean;
    amplitudes: Array<{ basis: string; real: number; imag: number; magnitude: number; probability: number; phase: number }>;
    probability_max: number;
    probability_min: number;
    probability_total: number;
    bloch: Array<{ qubit: number; x: number; y: number; z: number }>;
    purity: number;
    entropy: number;
    dominant_basis: string;
    entanglement_status: string;
  };
  state_before: TraceStep["state"];
  diff: Record<string, unknown>;
  metrics: StateMetrics;
  probabilities: Record<string, number>;
  measurement: Record<string, unknown> | null;
}

export interface TraceResponse {
  circuit_name: string;
  num_qubits: number;
  depth_mode: string;
  initial_state: TraceStep["state"];
  final_state: TraceStep["state"];
  total_seconds: number;
  n_operations: number;
  layers: number[][];
  steps: TraceStep[];
  truncated: boolean;
  summary: {
    steps: number;
    layers: number;
    total_seconds: number;
    slowest_operation: string | null;
    largest_state_change: string | null;
    entanglement_created_at: number | null;
    final_entanglement_status: string;
    [key: string]: unknown;
  };
  warnings: string[];
  notes: string[];
  circuit: CircuitDocument;
}

export interface OptimizationStep {
  rule: string;
  description: string;
  index: number;
  removed: string[];
  added: string[];
  verified: boolean;
  verification: Record<string, unknown>;
  reason?: string;
}

export interface OptimizationResult {
  before: Resources;
  after: Resources;
  improvements: Record<string, number>;
  steps: OptimizationStep[];
  verification: { status: string; method: string; reason?: string; max_deviation?: number; limitations?: string[] };
  passes_applied: string[];
  findings: Array<Record<string, unknown>>;
  qubit_map: Record<string, number> | null;
  seconds: number;
  notes: string[];
  original?: CircuitDocument;
  optimized?: CircuitDocument;
  opportunities: Array<Record<string, unknown>>;
  headline: string;
  level: OptimizerLevel;
  circuit: CircuitDocument;
  gate_histogram_before?: Record<string, number>;
  gate_histogram_after?: Record<string, number>;
}

export interface Comparison {
  circuit_a: { name: string; num_qubits: number; num_clbits: number; resources: Resources };
  circuit_b: { name: string; num_qubits: number; num_clbits: number; resources: Resources };
  resource_rows: Array<{ metric: string; a: unknown; b: unknown; delta: number | null }>;
  metric_rows: Array<{ metric: string; a: unknown; b: unknown; delta: number | null }>;
  a: SimulationResult;
  b: SimulationResult;
  output_total_variation: number;
  verdict: string[];
  shots: number;
  seed: number;
  noise: Record<string, unknown>;
  mode_a: Mode;
  mode_b: Mode;
  diagram_a: string;
  diagram_b: string;
  limitations: string[];
}

export interface WhatIf {
  question: string;
  baseline: Record<string, unknown> & { circuit?: Resources; counts?: Record<string, number>; metrics?: StateMetrics };
  variant: Record<string, unknown> & { circuit?: Resources; counts?: Record<string, number>; metrics?: StateMetrics };
  deltas: Record<string, { baseline: number | null; variant: number | null; delta: number | null; unit?: string; support?: string }>;
  verdict: string[];
  observations: string[];
  seconds: number;
  warnings: string[];
  limitation: string;
  headline: string;
  catalog: Array<{ kind: string; label: string; shape: Record<string, unknown> }>;
}

export interface HardwareReport {
  hardware: {
    name: string;
    num_qubits: number;
    topology: { num_qubits: number; edges: number[][]; connected: boolean; diameter: number; avg_degree: number };
    native_one_qubit: string[];
    native_two_qubit: string[];
    source: string;
    [key: string]: unknown;
  };
  required_qubits: number;
  available_qubits: number;
  fits: boolean;
  connectivity_violations: Array<{ index: number; gate: string; wires: number[]; issue: string; distance?: number }>;
  unsupported_gates: Array<{ name: string; count: number }>;
  estimate_before_routing: NoiseEstimate;
  estimate_after_routing?: NoiseEstimate;
  routing?: {
    logical_to_physical: Record<string, number>;
    swaps_inserted: number;
    swaps: Array<Record<string, unknown>>;
    depth_before: number;
    depth_after: number;
    depth_overhead_percent: number;
    gates_before: number;
    gates_after: number;
    violations_before: unknown[];
    violations_after: unknown[];
    notes: string[];
    circuit?: CircuitDocument;
  };
  limitations: string[];
  circuit?: CircuitDocument;
  devices?: Array<Record<string, unknown>>;
}

export interface NoiseEstimate {
  label: string;
  estimated_success_probability: number;
  estimated_error_rate: number;
  gate_survival: number;
  readout_survival: number;
  coherence_factor: number;
  contributors: Record<string, number>;
  dominant_contributor: string;
  one_qubit_gates: number;
  two_qubit_gates: number;
  multi_qubit_gates: number;
  circuit_duration_us: number;
  circuit_depth: number;
  assumptions: string[];
  hardware: string;
  source: string;
}

export interface ExperimentRow {
  index: number;
  params: Record<string, number | string>;
  label: string;
  qubits: number;
  gates: number;
  depth: number;
  two_qubit_gates: number;
  runtime_seconds: number;
  memory_mb: number;
  backend: string;
  mode: Mode;
  success_probability: number | null;
  success_definition: string;
  top_outcome: string | null;
  top_count: number | null;
  counts: Record<string, number>;
  ideal_probabilities: Record<string, number>;
  sampled_probabilities: Record<string, number>;
  distribution_distance: number;
  fidelity_vs_ideal: number | null;
  purity: number | null;
  entropy: number | null;
  entanglement_status: string | null;
  max_concurrence: number | null;
  analytic_success: number | null;
  analytic_deviation: number | null;
  estimated_error_budget: number | null;
  observation: string;
  extra: Record<string, unknown>;
  circuit?: CircuitDocument | null;
  experiment_id: string | null;
}

export interface ExperimentOutcome {
  spec: Record<string, unknown> & { key: string; name: string; kind: string; seed: number; shots: number };
  rows: ExperimentRow[];
  series: Record<string, unknown>;
  aggregates: Record<string, unknown>;
  observations: string[];
  warnings: string[];
  seconds: number;
  started_at: string;
  finished_at: string;
  experiment_ids: string[];
  headline: string;
  plan_note?: string;
}

export interface BenchmarkPoint {
  qubits: number;
  status: string;
  gates?: number;
  depth?: number;
  median_seconds?: number;
  spread_seconds?: number;
  memory_mb?: number;
  ops_per_second?: number;
  label?: string;
  reason?: string;
}

export interface BenchmarkPayload {
  kind: string;
  points?: BenchmarkPoint[];
  rows?: Array<Record<string, unknown>>;
  fit?: {
    available: boolean;
    reason?: string;
    model?: string;
    /** Empirical runtime multiplier per added qubit, fitted from the measurements. */
    multiplier_per_added_qubit?: number;
    doubling_qubits?: number | null;
    r_squared?: number;
    a?: number;
    measurements?: Array<{ qubits: number; measured_seconds: number; predicted_seconds: number }>;
    extrapolations?: Array<{ qubits: number; predicted_seconds: number; predicted_memory_mb?: number; label: string }>;
    note?: string;
  };
  method?: string;
  caveats?: string[];
  environment?: Record<string, string>;
  backends?: Array<Record<string, unknown>> | Record<string, unknown>;
  memory?: Record<string, unknown>;
  external?: Array<Record<string, unknown>>;
  budget_bytes?: number;
  budget_mb?: number;
  backend_tables?: Record<
    string,
    Array<{ qubits: number; amplitudes?: number; bytes: number; mb: number; human?: string; fits_budget?: boolean }>
  >;
  safe_max_qubits?: Record<string, number>;
  detected?: Array<{ module: string; name: string; available: boolean; version?: string | null; note?: string }>;
  results?: Array<{
    backend: string;
    available: boolean;
    median_seconds?: number;
    spread_seconds?: number;
    shots?: number;
    exact?: boolean;
    note?: string;
    reason?: string;
    agreement_with_qscope?: { total_variation: number; sampling_floor: number; consistent: boolean; note: string };
  }>;
  circuit?: string;
  gates?: number;
  num_qubits?: number;
  scaling?: BenchmarkPayload;
  mode?: Mode;
  mode_label?: string;
  notes?: string[];
  disclaimer?: string;
  request?: Record<string, unknown>;
  available?: boolean;
  reason?: string;
  engines?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface AIAnswer {
  question: string;
  intent: string;
  title: string;
  body: string;
  bullets: string[];
  citations: Array<{ label: string; value: unknown; source: string; kind?: string }>;
  confidence: string;
  limitations: string[];
  suggestions: string[];
  narrative: string | null;
  narrative_provider: string | null;
  narrative_violations: string[];
  narrative_error: string | null;
  sources_available: string[];
  llm_configured: boolean;
  grounding: string;
}

export interface Meta {
  version: string;
  platform: Record<string, string>;
  modes: Array<{ key: string; label: string; description: string }>;
  workflow: Array<{ key: string; label: string; endpoint: string }>;
  algorithms: Array<{
    key: string;
    name: string;
    description: string;
    category: string;
    difficulty: string;
    parameters: Record<string, unknown>;
    tags: string[];
    complexity: string;
    /** Size and cost of the catalogue's own default circuit — what gets loaded on selection. */
    qubits: number;
    gates: number;
    depth: number;
  }>;
  hardware: Array<{
    key: string;
    name: string;
    num_qubits: number;
    topology: string;
    edges: number;
    connected: boolean;
    two_qubit_gate_error: number;
    source: string;
    notes: string;
  }>;
  experiments: Array<{ key: string; name: string; kind: string; description: string; factory: string; defaults: Record<string, unknown> }>;
  backends: Array<{
    key: string;
    label: string;
    representation: string;
    exact: boolean;
    supports_noise: boolean;
    supports_midcircuit_measurement: boolean;
    max_practical_qubits: number;
    safe_max_qubits: number;
    description: string;
    tradeoff: string;
    bytes_per_qubit_expression: string;
  }>;
  noise_models: Array<{ kind: string; params: string[]; description: string; defaults: Record<string, number> }>;
  optimizer_levels: Array<{ key: string; label: string; description: string; passes: string[] }>;
  whatif: Array<{ kind: string; label: string; shape: Record<string, unknown> }>;
  ai_suggestions: Array<{ intent: string; question: string }>;
}

export interface StoredExperiment {
  experiment_id: string;
  name: string;
  created_at: string;
  tags: string[];
  circuit_name: string;
  num_qubits: number;
  num_clbits: number;
  gate_count: number;
  depth: number;
  backend: string;
  representation: string;
  mode: Mode;
  shots: number;
  seed: number;
  noise_name: string;
  runtime_seconds: number;
  memory_bytes: number;
  counts: Record<string, number>;
  metrics: StateMetrics;
  algorithm: string;
  optimizer: string;
  qscope_version: string;
  python_version: string;
  circuit?: CircuitDocument;
  reproducibility?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ReportPayload {
  report: {
    title: string;
    subtitle: string;
    objective: string;
    generated_at: string;
    mode: string;
    sections: Array<{ heading: string; kind: string; body: unknown; note: string; caption: string }>;
    observations: string[];
    limitations: string[];
    conclusion: string;
    reproducibility: Record<string, unknown>;
  };
  markdown: string;
  html: string;
  files?: Record<string, string>;
  dir?: string;
}

export interface WhatIfCatalog {
  modifications: Array<{ kind: string; label: string; shape: Record<string, unknown> }>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly hint: string;
  constructor(message: string, status: number, hint = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.hint = hint;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text;
  }
  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail ?? payload;
    const message =
      typeof detail === "string"
        ? detail
        : (detail as { detail?: string } | null)?.detail ??
          (detail as { error?: string } | null)?.error ??
          `request failed with ${response.status}`;
    const hint = (detail as { hint?: string } | null)?.hint ?? "";
    throw new ApiError(String(message), response.status, hint);
  }
  return payload as T;
}

const post = <T,>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });
const get = <T,>(path: string) => request<T>(path);
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

/** POSTs a body and keeps the response as bytes — used for report exports. */
async function postBlob(path: string, body: unknown): Promise<Blob> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    let detail: unknown = text;
    try {
      detail = JSON.parse(text);
    } catch {
      /* the body was not JSON; keep the raw text */
    }
    const payload = detail as { detail?: unknown } | null;
    const inner = payload?.detail as { detail?: string; error?: string } | undefined;
    throw new ApiError(
      typeof payload?.detail === "string" ? payload.detail : inner?.detail ?? inner?.error ?? `export failed with ${response.status}`,
      response.status,
    );
  }
  return response.blob();
}

/** Hands a blob to the browser as a download. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export const REPORT_FORMATS = ["html", "pdf", "json", "csv", "markdown"] as const;
export type ReportFormat = (typeof REPORT_FORMATS)[number];

export interface ReportRequest {
  kind: string;
  title?: string | null;
  objective?: string | null;
  save?: boolean;
  payload: Record<string, unknown>;
}

export interface SimulateRequest {
  source: CircuitSource;
  backend?: Backend;
  shots?: number;
  seed?: number | null;
  noise?: NoiseSpec;
  measure_all?: boolean;
  compare_ideal?: boolean;
  memory_budget_mb?: number | null;
  store?: boolean;
  include_state?: boolean;
  label?: string;
}

export const api = {
  health: () =>
    get<{
      status: string;
      version: string;
      python: string;
      numpy: string;
      database: string;
      database_ok: boolean;
      experiments_stored: number;
      reports_dir: string;
      llm_configured: boolean;
      offline: boolean;
    }>("/api/health"),
  meta: () => get<Meta>("/api/meta"),
  metaGates: () => get<{ gates: Array<Record<string, unknown>> }>("/api/meta/gates"),
  metaMetrics: () => get<{ metrics: Array<{ key: string; [key: string]: string }> }>("/api/meta/metrics"),

  validate: (source: CircuitSource) =>
    post<{ valid: boolean; errors: string[]; warnings: string[]; resources: Resources | Record<string, never> }>(
      "/api/circuit/validate",
      source,
    ),
  document: (source: CircuitSource) => post<CircuitDocument>("/api/circuit/document", source),
  fromQasm: (qasm: string) => post<CircuitDocument>("/api/circuit/from-qasm", { qasm }),
  circuitText: (source: CircuitSource, kind: "qasm" | "diagram") =>
    request<string>(`/api/circuit/${kind}`, { method: "POST", body: JSON.stringify(source) }),

  plan: (body: { source: CircuitSource; backend?: Backend; shots?: number; noise?: NoiseSpec; memory_budget_mb?: number | null }) =>
    post<Plan & { circuit: CircuitDocument; budget: { budget_mb: number; source: string } }>("/api/plan", body),

  simulate: (body: SimulateRequest) => post<SimulationResponse>("/api/simulate", body),

  trace: (body: { source: CircuitSource; depth?: "fast" | "standard" | "full"; term_limit?: number; max_steps?: number | null; analyze_last_only?: boolean }) =>
    post<TraceResponse>("/api/trace", body),

  optimize: (body: { source: CircuitSource; level?: OptimizerLevel; verify?: boolean }) =>
    post<OptimizationResult>("/api/optimize", body),
  opportunities: (source: CircuitSource) =>
    post<{ findings: Array<Record<string, unknown>>; levels: Meta["optimizer_levels"]; resources: Resources }>(
      "/api/optimize/opportunities",
      source,
    ),

  metrics: (body: { source: CircuitSource; keys?: string[]; include_entanglement?: boolean }) =>
    post<{
      circuit: CircuitDocument;
      state: StateMetrics;
      circuit_metrics: Record<string, unknown>;
      plan: Plan;
      mode: Mode;
      mode_label: string;
      shots: number;
      seed: number;
      warnings: string[];
      glossary: Array<{ key: string; [key: string]: string }>;
    }>("/api/metrics", body),

  compare: (body: { a: CircuitSource; b: CircuitSource; shots?: number; seed?: number; noise?: NoiseSpec; backend?: Backend }) =>
    post<Comparison>("/api/compare", body),

  whatIf: (body: { source: CircuitSource; modification: Record<string, unknown>; shots?: number; seed?: number; backend?: Backend; noise?: NoiseSpec; store?: boolean }) =>
    post<WhatIf>("/api/whatif", body),

  hardware: (body: { source: CircuitSource; device?: string; model?: Record<string, unknown> | null; route?: boolean }) =>
    post<HardwareReport>("/api/hardware", body),

  evolve: (body: { source: CircuitSource; generations?: number; population?: number; seed?: number; hardware?: string | null; target?: string }) =>
    post<{
      target: string;
      candidates: Array<{
        label: string;
        source: string;
        gate_count: number;
        depth: number;
        two_qubit_gates: number;
        fidelity: number;
        process_fidelity: number;
        score: number;
        estimated_success: number | null;
        noise_score: number | null;
        verified: boolean;
        verification: Record<string, unknown>;
        circuit?: CircuitDocument;
        notes: string[];
      }>;
      best: {
        label: string;
        source: string;
        gate_count: number;
        depth: number;
        two_qubit_gates: number;
        fidelity: number;
        process_fidelity: number;
        score: number;
        estimated_success: number | null;
        verified: boolean;
        verification: Record<string, unknown>;
        circuit?: CircuitDocument;
        notes: string[];
      } | null;
      generations: Array<Record<string, number>>;
      seconds: number;
      search_log: string[];
      seed: number;
      notes: string[];
      comparison: Array<Record<string, unknown>>;
      headline: string;
      reference: CircuitDocument;
    }>("/api/evolve", body),

  runExperiment: (body: Record<string, unknown>) => post<ExperimentOutcome>("/api/experiments/run", body),
  benchmark: (body: { kind: string; qubits?: number[]; depth?: number; shots?: number; trials?: number; backends?: Backend[]; seed?: number }) =>
    post<BenchmarkPayload>("/api/benchmark", body),

  report: (body: ReportRequest) => post<ReportPayload>("/api/report", body),
  /** Renders the same report to a downloadable artifact (POST, returned as bytes). */
  reportExport: (body: ReportRequest, format: ReportFormat | string) =>
    postBlob(`/api/report/export?format=${format}`, body),
  listReports: () => get<{ dir: string; files: Array<{ name: string; bytes: number; modified: string; format: string }> }>("/api/reports"),
  /** A saved report is served back from the reports directory by name. */
  reportFileUrl: (name: string) => `/api/reports/${encodeURIComponent(name)}`,

  ask: (body: Record<string, unknown>) => post<AIAnswer>("/api/ai/ask", body),
  aiSuggestions: () =>
    get<{ questions: Array<{ intent: string; question: string }>; llm_configured: boolean; offline_note: string }>(
      "/api/ai/suggestions",
    ),

  history: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    ).toString();
    return get<{
      total: number;
      experiments: StoredExperiment[];
      tags: Array<{ tag: string; count: number }>;
      stats: Record<string, unknown>;
    }>(`/api/history${query ? `?${query}` : ""}`);
  },
  historyGet: (id: string) => get<StoredExperiment>(`/api/history/${id}`),
  historyDelete: (id: string) => del<{ deleted: boolean; experiment_id: string }>(`/api/history/${id}`),
  historyCompare: (ids: string[]) => post<{ experiments: StoredExperiment[]; [key: string]: unknown }>("/api/history/compare", { ids }),
  historyReproduce: (id: string) =>
    get<{
      experiment_id: string;
      original: { counts: Record<string, number>; metrics: StateMetrics; backend: string; mode: Mode; runtime_seconds: number; created_at: string };
      rerun: { counts: Record<string, number>; metrics: StateMetrics; backend: string; mode: Mode; runtime_seconds: number };
      distribution_distance: number;
      expected_shot_noise: number;
      verdict: string;
      note: string;
    }>(`/api/history/reproduce/${id}`),
};

/** Streams a gate-by-gate trace from the server. */
export function streamTrace(
  body: Record<string, unknown> & { delay_ms?: number },
  handlers: {
    onStart?: (event: { circuit: CircuitDocument; diagram: string; total_steps: number }) => void;
    onStep?: (step: TraceStep, index: number) => void;
    onDone?: () => void;
    onError?: (message: string) => void;
  },
): { close: () => void; socket: WebSocket } {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/trace`);
  let index = 0;
  socket.onopen = () => socket.send(JSON.stringify(body));
  socket.onmessage = (message) => {
    const event = JSON.parse(message.data as string) as Record<string, unknown>;
    if (event.type === "start") {
      index = 0;
      handlers.onStart?.(event as unknown as { circuit: CircuitDocument; diagram: string; total_steps: number });
    } else if (event.type === "step") {
      handlers.onStep?.(event.step as TraceStep, index++);
    } else if (event.type === "done") {
      handlers.onDone?.();
    } else if (event.type === "error") {
      handlers.onError?.(String(event.detail ?? event.error ?? "stream failed"));
    }
  };
  socket.onerror = () => handlers.onError?.("the debugger stream could not connect");
  return { close: () => socket.close(), socket };
}

/** Streams experiment progress, one message per parameter point. */
export function streamExperiment(
  body: Record<string, unknown>,
  handlers: {
    onStart?: (event: { spec: Record<string, unknown>; total: number }) => void;
    onProgress?: (event: { index: number; total: number; label: string }) => void;
    onDone?: (outcome: ExperimentOutcome) => void;
    onError?: (message: string) => void;
  },
): { close: () => void; socket: WebSocket } {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/experiment`);
  socket.onopen = () => socket.send(JSON.stringify(body));
  socket.onmessage = (message) => {
    const event = JSON.parse(message.data as string) as Record<string, unknown>;
    if (event.type === "start") handlers.onStart?.(event as unknown as { spec: Record<string, unknown>; total: number });
    else if (event.type === "progress") handlers.onProgress?.(event as unknown as { index: number; total: number; label: string });
    else if (event.type === "done") handlers.onDone?.(event.outcome as ExperimentOutcome);
    else if (event.type === "error") handlers.onError?.(String(event.detail ?? event.error ?? "stream failed"));
  };
  socket.onerror = () => handlers.onError?.("the experiment stream could not connect");
  return { close: () => socket.close(), socket };
}
