export type DatasetColumn = {
  name: string;
  original_name: string;
  duckdb_type: string;
  dtype: string;
  role: "numeric" | "categorical" | "date" | "boolean" | "text" | "id";
};

export type Dataset = {
  id: string;
  name: string;
  file_type: string;
  row_count: number;
  column_count: number;
  size_bytes: number;
  columns: DatasetColumn[];
  created_at: string;
};

export type ProfileColumn = {
  name: string;
  dtype: string;
  role: string;
  missing: number;
  missing_pct: number;
  unique: number;
  min?: number | string;
  max?: number | string;
  mean?: number;
  median?: number;
  top_values?: { value: string; count: number }[];
};

export type DatasetProfile = {
  rows: number;
  n_columns: number;
  duplicate_rows: number;
  columns: ProfileColumn[];
  numeric_columns: string[];
  categorical_columns: string[];
  date_columns: string[];
  sample_rows: Record<string, unknown>[];
};

export type TraceEvent = {
  agent: string;
  label: string;
  status: "completed" | "skipped" | "retry" | "partial" | "failed";
  message: string;
  elapsed_ms: number;
};

export type Evidence = { ref: string; claimed_value: number; unit: string; actual_value: number | string | null };
export type Finding = { statement: string; kind: "observed" | "calculated" | "interpretation"; verified: boolean; evidence: Evidence[] };
export type Report = {
  title: string;
  executive_summary: string;
  key_findings: Finding[];
  detailed_analysis: string;
  conclusion: string;
  methodology: string;
};

export type ChartResult = { id: string; title: string; source: string; spec: Record<string, unknown>; figure: { data: unknown[]; layout: Record<string, unknown> } };
export type QueryResult = { id: string; purpose: string; sql: string; columns: string[]; row_count: number; truncated: boolean; elapsed_ms: number; error: string | null; preview: Record<string, unknown>[] };
export type ToolResult = { id: string; tool: string; args: Record<string, unknown>; error: string | null; elapsed_ms: number };

export type AnalysisResultPayload = {
  status: "completed" | "partial" | "failed";
  error: string | null;
  question: string;
  resolved_question: string;
  plan: Record<string, unknown>;
  report: Report | null;
  charts: ChartResult[];
  queries: QueryResult[];
  tools: ToolResult[];
  validation: { valid: boolean; issues: { scope: string; index: number | null; message: string }[]; retries: { data: number; report: number } };
  warnings: string[];
  stats: { gemini_calls: number; elapsed_ms: number };
};

export type Analysis = {
  id: string;
  session_id: string;
  dataset_id: string;
  dataset_name?: string;
  question: string;
  status: "running" | "completed" | "partial" | "failed";
  summary: string;
  error: string | null;
  trace: TraceEvent[];
  created_at: string;
  completed_at: string | null;
  result?: AnalysisResultPayload;
};

export type GeminiSessionStatus = { connected: boolean; model?: string; expires_at?: number };
