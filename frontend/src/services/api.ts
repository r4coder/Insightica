import type { Analysis, AnalysisResultPayload, Dataset, DatasetProfile, GeminiSessionStatus } from "../types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let code = "unknown", message = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      code = body.code ?? code;
      message = body.message ?? message;
    } catch {
      // response had no JSON body
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const configApi = {
  test: (apiKey?: string) => request<{ valid: boolean; message: string }>("/api/v1/config/test-gemini", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  }),
  createSession: (apiKey: string) => request<{ connected: boolean; model: string; expires_at: number; ttl_minutes: number }>(
    "/api/v1/config/session",
    { method: "POST", body: JSON.stringify({ api_key: apiKey }) },
  ),
  status: () => request<GeminiSessionStatus>("/api/v1/config/session"),
  logout: () => request<{ connected: boolean }>("/api/v1/config/logout", { method: "POST" }),
};

export const datasetApi = {
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Dataset>("/api/v1/datasets", { method: "POST", body: form });
  },
  list: () => request<Dataset[]>("/api/v1/datasets"),
  get: (id: string) => request<Dataset>(`/api/v1/datasets/${id}`),
  profile: (id: string) => request<DatasetProfile>(`/api/v1/datasets/${id}/profile`),
  remove: (id: string) => request<void>(`/api/v1/datasets/${id}`, { method: "DELETE" }),
};

export const analysisApi = {
  start: (datasetId: string, question: string, sessionId?: string) =>
    request<Analysis>("/api/v1/analysis", {
      method: "POST",
      body: JSON.stringify({ dataset_id: datasetId, question, session_id: sessionId }),
    }),
  history: (params?: { datasetId?: string; sessionId?: string }) => {
    const qs = new URLSearchParams();
    if (params?.datasetId) qs.set("dataset_id", params.datasetId);
    if (params?.sessionId) qs.set("session_id", params.sessionId);
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<Analysis[]>(`/api/v1/analysis${suffix}`);
  },
  get: (id: string) => request<Analysis>(`/api/v1/analysis/${id}`),
};

export type { AnalysisResultPayload };
