/** Response shapes from the Hive API. Kept hand-written and narrow: these mirror
 *  the FastAPI routes rather than a generated client, so a drift shows up as a
 *  type error at the call site. */

export type Severity = "info" | "warn" | "error";
export type ActivityLevel = "high" | "normal" | "low" | "quiet" | "flagged";

export interface Alert {
  severity: Severity;
  title: string;
  detail: string;
}

export interface Contributor {
  person_id: string;
  name: string;
  email: string;
  role: string;
  commits: number;
  prs: number;
  total: number;
  level: ActivityLevel;
  last_seen: string | null;
}

export interface Highlight {
  title: string;
  author: string | null;
  date: string | null;
  type: string;
  reference: string | null;
}

export interface TeamPulse {
  window_days: number;
  generated_at: string;
  weekly_activity: Record<string, number>;
  totals: Record<string, number>;
  on_track_percent: number | null;
  blocked_count: number | null;
  stale_count: number;
  open_prs: number;
  merged_prs: number;
  contributors: Contributor[];
  highlights: Highlight[];
  alerts: Alert[];
  data_coverage: Record<string, boolean>;
}

export interface ActivityWeek {
  week: string;
  commits: number;
  prs: number;
  tickets: number;
  emails: number;
  meetings: number;
  total: number;
}

export interface EvidenceItem {
  artifact_id: string;
  type: string;
  title: string;
  reference: string | null;
  date: string | null;
  excerpt: string;
}

export interface StatusResult {
  person_id: string;
  person_name: string;
  role: string;
  period_start: string;
  period_end: string;
  summary: string;
  evidence: EvidenceItem[];
  activity_level: ActivityLevel;
  generated_at: string;
  model: string;
}

export interface TeamStatus {
  team_id: string;
  period_start: string;
  period_end: string;
  statuses: StatusResult[];
}

export interface Source {
  artifact_id: string;
  type: string;
  title: string;
  author: string | null;
  date: string | null;
  relevance: number;
  excerpt: string;
  reference: string | null;
}

export interface QueryResponse {
  answer: string;
  sources: Source[];
  has_gap: boolean;
  latency_ms: number;
  model: string;
  /** Graded-retrieval trace: how many passes it took and what it re-searched. */
  attempts: number;
  rewrites: string[];
}

export interface Expert {
  person_id: string;
  display_name: string;
  email: string;
  topics: string[];
  score: number;
  evidence_count: number;
  last_seen: string | null;
}

export interface ExpertiseLink {
  person_id: string;
  person: string;
  topic: string;
  score: number;
  evidence_count: number;
  last_seen: string | null;
}

export interface ExpertiseMap {
  people: { id: string; name: string; email: string; role: string; topics: number }[];
  topics: { topic: string; people: number; links: number }[];
  links: ExpertiseLink[];
  solo_topics: string[];
}

export interface KnowledgeRequest {
  id: string;
  question: string;
  context: string | null;
  status: string;
  answer: string | null;
  tags: string[];
  requester: string | null;
  routed_to: string | null;
  answered_by: string | null;
  created_at: string | null;
  answered_at: string | null;
  resolution_hours: number | null;
}

export interface GapAnalytics {
  open_krs: number;
  answered_krs: number;
  avg_resolution_hours: number | null;
  top_requested_topics: { topic: string; count: number }[];
  bus_factor: {
    person: string;
    solo_topics: string[];
    solo_topic_count: number;
    routed_krs: number;
  }[];
  trend: { week: string; new: number; resolved: number }[];
}

export interface ConnectorStatus {
  connector: string;
  last_status: string;
  last_run_at: string | null;
  cursor_at: string | null;
  artifacts_ingested: number;
  last_error: string | null;
}

export interface IngestionStatus {
  connectors: ConnectorStatus[];
  artifact_count: number;
  chunk_count: number;
  people_count: number;
}

export interface Health {
  status: string;
  environment: string;
  llm_provider: string;
  embedding_provider: string;
  vector_provider: string;
  database: string;
}
