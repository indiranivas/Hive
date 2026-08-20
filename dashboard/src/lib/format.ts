export const ARTIFACT_LABELS: Record<string, string> = {
  commit: "Commit",
  pull_request: "Pull request",
  work_item: "Work item",
  email_thread: "Email",
  meeting_transcript: "Meeting",
  comment: "Comment",
  pr_review: "PR review",
};

export const SOURCE_LABELS: Record<string, string> = {
  git: "Git",
  task: "Azure DevOps",
  email: "Email",
  call: "Meetings",
};

/** Series order is fixed: slot assignment must never depend on which streams
 *  happen to have data, or a filter would repaint the survivors. */
export const ACTIVITY_SERIES = [
  { key: "commits", label: "Commits", color: "var(--series-1)" },
  { key: "prs", label: "Pull requests", color: "var(--series-2)" },
  { key: "tickets", label: "Tickets", color: "var(--series-3)" },
  { key: "emails", label: "Emails", color: "var(--series-4)" },
  { key: "meetings", label: "Meetings", color: "var(--series-5)" },
] as const;

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function relativeDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30)}mo ago`;
  return `${Math.round(days / 365)}y ago`;
}

export function hours(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 24) return `${Math.round(value)}h`;
  return `${(value / 24).toFixed(1)}d`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/** Deterministic avatar tint from the person's name -- identity, not data, so it
 *  sits outside the series palette. */
export function avatarTint(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return `oklch(0.62 0.11 ${hash})`;
}

export const LEVEL_COPY: Record<string, { label: string; tone: string }> = {
  high: { label: "High volume", tone: "text-ink-secondary" },
  normal: { label: "Steady", tone: "text-ink-secondary" },
  low: { label: "Light", tone: "text-ink-muted" },
  quiet: { label: "No tracked activity", tone: "text-ink-muted" },
  flagged: { label: "Needs a look", tone: "text-ink-secondary" },
};
