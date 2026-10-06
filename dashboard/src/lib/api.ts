import type {
  ActivityWeek,
  BusFactorTopic,
  ExpertiseMap,
  GapAnalytics,
  GraphResponse,
  Health,
  IngestionStatus,
  KnowledgeRequest,
  LeadershipOverview,
  QueryResponse,
  StatusResult,
  TeamPulse,
  TeamStatus,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    // A dead API is the most common failure in dev; say so plainly rather than
    // surfacing "Failed to fetch".
    throw new ApiError(`Cannot reach the Hive API at ${API_BASE}`, 0);
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail);
    } catch {
      detail = undefined;
    }
    throw new ApiError(
      response.status === 403
        ? "Your role cannot view this."
        : `Request failed (${response.status})`,
      response.status,
      detail,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const query = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
};

export const api = {
  health: () => request<Health>("/health"),

  overview: () => request<LeadershipOverview>("/api/dashboard/overview"),

  pulse: (windowDays = 7, teamId?: string) =>
    request<TeamPulse>(`/api/dashboard/pulse${query({ window_days: windowDays, team_id: teamId })}`),

  activity: (weeks = 8, teamId?: string) =>
    request<{ weeks: ActivityWeek[] }>(
      `/api/dashboard/activity${query({ weeks, team_id: teamId })}`,
    ),

  expertiseMap: (teamId?: string) =>
    request<ExpertiseMap>(`/api/dashboard/expertise-map${query({ team_id: teamId })}`),

  searchExperts: (topic: string) =>
    request<{ topic: string; experts: import("./types").Expert[] }>(
      `/api/expertise/search${query({ topic, limit: 8 })}`,
    ),

  teamStatus: (week?: string, refresh = false) =>
    request<TeamStatus>(`/api/status/team${query({ week, refresh })}`),

  myStatus: (week?: string, refresh = false) =>
    request<StatusResult>(`/api/status/me${query({ week, refresh })}`),

  ask: (q: string, scope: "team" | "org" = "team") =>
    request<QueryResponse>("/api/query", {
      method: "POST",
      body: JSON.stringify({ query: q, scope }),
    }),

  knowledgeRequests: (params: { status?: string; search?: string; tag?: string } = {}) =>
    request<{ items: KnowledgeRequest[]; count: number }>(
      `/api/knowledge-requests${query({ ...params, limit: 100 })}`,
    ),

  createKnowledgeRequest: (question: string, context?: string) =>
    request<KnowledgeRequest>("/api/knowledge-requests", {
      method: "POST",
      body: JSON.stringify({ question, context }),
    }),

  answerKnowledgeRequest: (id: string, answer: string) =>
    request<KnowledgeRequest>(`/api/knowledge-requests/${id}/answer`, {
      method: "PUT",
      body: JSON.stringify({ answer }),
    }),

  rerouteKnowledgeRequest: (id: string) =>
    request<{ routed_to: string | null; reason: string }>(
      `/api/knowledge-requests/${id}/route`,
      { method: "POST" },
    ),

  gapAnalytics: () => request<GapAnalytics>("/api/knowledge-requests/analytics"),

  graph: () => request<GraphResponse>("/api/graph/overview"),

  busFactor: () => request<{ at_risk: BusFactorTopic[] }>("/api/graph/bus-factor"),

  ingestionStatus: () => request<IngestionStatus>("/api/admin/ingestion-status"),

  triggerGitIngestion: () =>
    request<{ runs: Record<string, unknown>[] }>("/api/admin/ingest/git", { method: "POST" }),
};
