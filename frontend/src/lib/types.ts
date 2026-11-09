// Mirrors backend/app/llm/schemas.py and the payloads in backend/app/services/*.

export type Format =
  | "usd"
  | "usd2"
  | "int"
  | "number"
  | "pct"
  | "pct_ratio"
  | "rate"
  | "text"
  | "date";

export type Kpi = {
  type: "kpi";
  label: string;
  value: unknown;
  format: Format;
  sub: string | null;
};
export type SeriesChart = {
  type: "line" | "bar";
  title: string;
  query: string;
  x: string;
  y: string[];
  format: Format;
};
export type HBar = {
  type: "hbar";
  title: string;
  query: string;
  label: string;
  value: string;
  format: Format;
  top_n: number;
};
export type Scatter = {
  type: "scatter";
  title: string;
  query: string;
  x: string;
  y: string;
  label: string | null;
  tooltip: string[];
  x_format: Format;
  y_format: Format;
};
export type TableColumn = { column: string; label: string; format: Format };
export type Table = {
  type: "table";
  title: string;
  query: string;
  columns: TableColumn[];
  sort_column: string | null;
  sort_desc: boolean;
  filter_columns: string[];
};
export type Callout = { type: "callout"; tone: "info" | "warn"; text: string };
export type Component = Kpi | SeriesChart | HBar | Scatter | Table | Callout;

export type Dataset = {
  columns: string[];
  types: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
};

export type ExecutedQuery = {
  name: string;
  purpose: string;
  attempt: number;
  sql: string;
  status: "succeeded" | "failed";
  duration_ms: number;
  row_count: number | null;
};

export type Outcome =
  | "answered"
  | "no_results"
  | "unsupported"
  | "explained"
  | "clarify"
  | "declined"
  | "failed"
  | "cancelled";

export type Usage = {
  latency_ms: number | null;
  cost_usd: number | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  cache_write_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
};

export type Answer = {
  run_id: string;
  network: string;
  effort: string;
  model?: string;
  dataset_version_id: number | null;
  rerun_of: string | null;
  outcome: Outcome;
  text: string;
  narrative?: string; // absent on answers saved before it existed
  interpretation: Record<string, string> | null;
  options: string[];
  components: Component[];
  assumptions: string[];
  limitations: string[];
  followups: string[];
  queries: ExecutedQuery[];
  datasets: Record<string, Dataset>;
  // Only on answers loaded from a saved conversation:
  stale?: boolean;
  dataset_loaded_at?: string | null;
  usage?: Usage;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string;
  created_at: string;
  expires_at: string;
  answer?: Answer;
};

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  preview: string | null;
  network: string | null;
  last_activity: string;
  expires_at: string;
  stale: boolean;
};

export type Conversation = ConversationSummary & { messages: Message[] };

// Mirrors backend/app/services/dashboard_export.py payload().
export type DashboardWidget = { id: string; component: Component };
export type DashboardFinding = {
  finding: string;
  evidence: string[];
  clinical_context: string;
  review_opportunity: string;
  limitation: string;
};
export type DashboardInsight = {
  id: string;
  status: "adverse" | "favorable" | "neutral";
  label: string;
  finding: string;
  next_step: string;
  evidence: string[];
};
type DashboardTabBase = {
  id: string;
  name: string;
  question: string;
  outcome: "answered" | "no_results" | "unsupported";
  widgets: DashboardWidget[];
  assumptions: string[];
  limitations: string[];
  methodology: {
    interpretation: Record<string, string> | null;
    queries: { name: string; purpose: string; sql: string }[];
  };
};
// Saved before the KPI, grid and narrative layout.
export type LegacyDashboardTab = DashboardTabBase & { takeaway: string; findings: DashboardFinding[] };
export type GridDashboardTab = DashboardTabBase & {
  narrative: string;
  insights: DashboardInsight[];
  grid: string[][];
};
export type DashboardTab = LegacyDashboardTab | GridDashboardTab;
export type DashboardScope = {
  level: "pcp" | "pcp_group";
  provider_name: string;
  provider_npi: string | null;
  provider_tin: string;
  network: string;
  population: string;
  period: string;
};
export type DashboardPayload = {
  title: string;
  scope: DashboardScope;
  version: number;
  generated_at: string;
  dataset_loaded_at: string | null;
  tabs: DashboardTab[];
  datasets: Record<string, Record<string, Dataset>>;
};

// Mirrors backend/app/llm/dashboard_schemas.py and routes/dashboards.py.
export type TabOutline = { id: string; name: string; question: string; metrics: string[]; visuals: string[] };
export type DashboardOutline = { title: string; filename: string; scope: DashboardScope; tabs: TabOutline[] };
export type OutlineResult = {
  action: "outline" | "clarify" | "decline";
  message: string | null;
  options: string[];
  outline: DashboardOutline | null;
};
export type TabOutcome = { name: string; outcome: DashboardTab["outcome"] };
export type DashboardSummary = {
  id: string;
  title: string;
  current_version: number;
  created_at: string;
  updated_at: string;
  scope: DashboardScope;
  tabs: TabOutcome[];
  created_by: string;
  // Null when the dashboard predates usage capture.
  model: string | null;
  effort: string | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  has_python: boolean;
};
export type DashboardQuery = {
  tab: string;
  name: string;
  purpose: string;
  sql: string;
  row_count: number | null;
  duration_ms: number | null;
};
export type DashboardScript = {
  tab: string;
  purpose: string;
  code: string;
  status: "succeeded" | "failed";
  output: string;
  duration_ms: number;
};
export type DashboardMethodology = { markdown: string; queries: DashboardQuery[]; scripts: DashboardScript[] };
export type BuildStatus = "running" | "built" | "failed" | "cancelled";
export type DashboardBuild = {
  id: string;
  title: string;
  request: string;
  outline: DashboardOutline;
  effort: string;
  status: BuildStatus;
  steps_done: number;
  steps_total: number;
  events: { at: string; message: string }[];
  dashboard_id: string | null;
  error: string | null;
  failed_step: string | null;
  created_at: string;
  finished_at: string | null;
  seen_at: string | null;
  elapsed_ms: number;
};
export type SavedDashboard = {
  dashboard_id: string;
  title: string;
  version: number;
  updated_at: string;
  created_at: string;
  dataset_loaded_at: string | null;
  request: string;
  outline: DashboardOutline;
  spec: { title: string; tabs: TabOutcome[] };
};

export type Meta = {
  dataset_version: { id: number; created_at: string } | null;
  retention_days: number;
  dashboard_retention_days: number;
  model: string;
  efforts: string[];
  default_effort: string;
  networks: string[];
  default_network: string;
  is_admin: boolean;
};

export type UsageRow = {
  key: string | null;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  unpriced_calls: number;
  active_days: number;
};

export type LlmUsageReport = {
  period: "day" | "month" | "year";
  label: string;
  total: UsageRow;
  previous: UsageRow | null;
  series: UsageRow[];
  by_model: UsageRow[];
  by_user: UsageRow[];
  by_feature: UsageRow[];
};
