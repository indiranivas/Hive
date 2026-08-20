"use client";

import { useState } from "react";
import { ActivityBars } from "@/components/charts";
import {
  Avatar,
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  Metric,
  PageHeader,
  SeverityBadge,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import {
  ARTIFACT_LABELS,
  LEVEL_COPY,
  SOURCE_LABELS,
  avatarTint,
  initials,
  relativeDate,
} from "@/lib/format";
import { useApi } from "@/lib/hooks";

const WINDOWS = [
  { days: 7, label: "7 days" },
  { days: 14, label: "14 days" },
  { days: 30, label: "30 days" },
];

export default function PulsePage() {
  const [windowDays, setWindowDays] = useState(7);
  const pulse = useApi(() => api.pulse(windowDays), [windowDays]);
  const activity = useApi(() => api.activity(8), []);

  return (
    <>
      <PageHeader
        title="Team pulse"
        subtitle="What the team actually shipped, straight from the work trail."
        action={
          <div className="flex items-center gap-1 rounded-lg border border-hairline p-0.5">
            {WINDOWS.map((option) => (
              <button
                key={option.days}
                onClick={() => setWindowDays(option.days)}
                className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                  windowDays === option.days
                    ? "bg-accent-soft font-medium text-accent"
                    : "text-ink-secondary hover:text-ink"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      />

      {pulse.error ? (
        <ErrorState message={pulse.error} detail={pulse.detail} onRetry={pulse.reload} />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {pulse.loading && !pulse.data ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-3 h-7 w-16" />
            </Card>
          ))
        ) : pulse.data ? (
          <>
            <Metric
              label={`Activity · ${windowDays}d`}
              value={Object.values(pulse.data.weekly_activity).reduce((a, b) => a + b, 0)}
              hint={`${pulse.data.weekly_activity.commits ?? 0} commits · ${
                pulse.data.weekly_activity.prs ?? 0
              } PRs`}
            />
            <Metric
              label="Open pull requests"
              value={pulse.data.open_prs}
              hint={
                pulse.data.stale_count
                  ? `${pulse.data.stale_count} open over 5 days`
                  : `${pulse.data.merged_prs} merged all-time`
              }
            />
            <Metric
              label="On track"
              value={pulse.data.on_track_percent ? `${pulse.data.on_track_percent}%` : "—"}
              unavailable={
                pulse.data.on_track_percent === null
                  ? "Needs the Azure DevOps connector"
                  : undefined
              }
            />
            <Metric
              label="Open knowledge gaps"
              value={pulse.data.totals.open_knowledge_requests ?? 0}
              hint="Questions the team could not answer"
            />
          </>
        ) : null}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Activity by week"
            hint="Stacked by source, last 8 weeks"
            action={
              activity.data ? (
                <span className="tabular text-xs text-ink-muted">
                  {activity.data.weeks.reduce((sum, week) => sum + week.total, 0)} artifacts
                </span>
              ) : null
            }
          />
          {activity.error ? (
            <ErrorState message={activity.error} onRetry={activity.reload} />
          ) : activity.loading && !activity.data ? (
            <Skeleton className="h-48 w-full" />
          ) : activity.data && activity.data.weeks.some((week) => week.total > 0) ? (
            <ActivityBars weeks={activity.data.weeks} />
          ) : (
            <EmptyState
              title="No activity ingested yet"
              hint="Run an ingestion to populate the work trail: hive.cli ingest-git --repo <path>"
            />
          )}
        </Card>

        <Card>
          <CardHeader title="Needs attention" hint="Derived from connectors and open work" />
          {pulse.loading && !pulse.data ? (
            <Skeleton className="h-24 w-full" />
          ) : pulse.data?.alerts.length ? (
            <ul className="space-y-3">
              {pulse.data.alerts.map((alert) => (
                <li key={alert.title} className="border-b border-hairline pb-3 last:border-0 last:pb-0">
                  <SeverityBadge severity={alert.severity} />
                  <p className="mt-1 text-sm font-medium text-ink">{alert.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{alert.detail}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nothing needs attention" hint="No connector errors or stale work." />
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Contributors"
            hint={`Volume in the last ${windowDays} days — not a productivity ranking`}
          />
          {pulse.loading && !pulse.data ? (
            <Skeleton className="h-32 w-full" />
          ) : pulse.data?.contributors.length ? (
            <ul className="space-y-3">
              {pulse.data.contributors.map((person) => {
                const max = Math.max(...pulse.data!.contributors.map((c) => c.total), 1);
                return (
                  <li key={person.person_id} className="flex items-center gap-3">
                    <Avatar name={initials(person.name)} tint={avatarTint(person.name)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <p className="truncate text-sm font-medium text-ink">{person.name}</p>
                        <span className="tabular shrink-0 text-xs text-ink-secondary">
                          {person.commits}c · {person.prs}pr
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 rounded-full bg-surface-inset">
                        <div
                          className="h-1.5 rounded-full"
                          style={{
                            width: `${Math.max(4, (person.total / max) * 100)}%`,
                            background: "var(--series-1)",
                          }}
                        />
                      </div>
                      <p className="mt-1 text-[11px] text-ink-muted">
                        {LEVEL_COPY[person.level]?.label ?? person.level} · last seen{" "}
                        {relativeDate(person.last_seen)}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState title="No contributor activity in this window" />
          )}
        </Card>

        <Card>
          <CardHeader title="Latest work" hint="Most recent artifacts, with their references" />
          {pulse.loading && !pulse.data ? (
            <Skeleton className="h-32 w-full" />
          ) : pulse.data?.highlights.length ? (
            <ul className="space-y-3">
              {pulse.data.highlights.map((item, index) => (
                <li key={index} className="border-b border-hairline pb-3 last:border-0 last:pb-0">
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 flex-1 text-sm text-ink">{item.title}</p>
                    <span className="shrink-0 text-xs text-ink-muted">{relativeDate(item.date)}</span>
                  </div>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                    <Chip>{ARTIFACT_LABELS[item.type] ?? item.type}</Chip>
                    <span>{item.author ?? "unknown author"}</span>
                    {item.reference ? (
                      <code className="font-mono text-[11px] text-ink-secondary">
                        {item.reference}
                      </code>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nothing ingested in this window" />
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader
          title="Data coverage"
          hint="Metrics only ever reflect the streams that are connected"
          action={
            <Button size="sm" onClick={pulse.reload} disabled={pulse.loading}>
              {pulse.loading ? "Refreshing…" : "Refresh"}
            </Button>
          }
        />
        <div className="flex flex-wrap gap-2">
          {pulse.data
            ? Object.entries(pulse.data.data_coverage).map(([source, present]) => (
                <span
                  key={source}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                    present
                      ? "border-hairline text-ink"
                      : "border-dashed border-hairline text-ink-muted"
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${present ? "bg-good" : "bg-axis"}`}
                    aria-hidden
                  />
                  {SOURCE_LABELS[source] ?? source}
                  {present ? "" : " · not connected"}
                </span>
              ))
            : null}
        </div>
      </Card>
    </>
  );
}
