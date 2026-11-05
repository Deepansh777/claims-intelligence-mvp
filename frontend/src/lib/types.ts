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

export type Meta = {
  dataset_version: { id: number; created_at: string } | null;
  retention_days: number;
  model: string;
  efforts: string[];
  default_effort: string;
  networks: string[];
  default_network: string;
  is_admin: boolean;
};
