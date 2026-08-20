"use client";

import { TopicBars, TrendChart } from "@/components/charts";
import {
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  Metric,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { hours } from "@/lib/format";
import { useApi } from "@/lib/hooks";

export default function GapAnalyticsPage() {
  const analytics = useApi(() => api.gapAnalytics(), []);

  return (
    <>
      <PageHeader
        title="Gap analytics"
        subtitle="Where the team's knowledge is thin, and who is a single point of failure."
      />

      {analytics.error ? (
        <ErrorState
          message={analytics.error}
          detail={analytics.detail}
          onRetry={analytics.reload}
        />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {analytics.data ? (
          <>
            <Metric label="Open gaps" value={analytics.data.open_krs} hint="Awaiting an answer" />
            <Metric label="Answered" value={analytics.data.answered_krs} hint="In the repo" />
            <Metric
              label="Avg resolution"
              value={hours(analytics.data.avg_resolution_hours)}
              unavailable={
                analytics.data.avg_resolution_hours === null
                  ? "Nothing answered yet"
                  : undefined
              }
            />
            <Metric
              label="Bus-factor risks"
              value={analytics.data.bus_factor.length}
              hint="People holding solo topics"
            />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-3 h-7 w-14" />
            </Card>
          ))
        )}
      </div>

      <Card className="mt-4">
        <CardHeader title="Raised vs answered" hint="Per week — a widening gap means questions are piling up" />
        {analytics.loading && !analytics.data ? (
          <Skeleton className="h-44 w-full" />
        ) : analytics.data ? (
          <TrendChart points={analytics.data.trend} />
        ) : null}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Most requested topics" hint="Tags across every request" />
          {analytics.loading && !analytics.data ? (
            <Skeleton className="h-52 w-full" />
          ) : analytics.data?.top_requested_topics.length ? (
            <TopicBars
              items={analytics.data.top_requested_topics.map((entry) => ({
                label: entry.topic,
                value: entry.count,
              }))}
            />
          ) : (
            <EmptyState title="No tagged requests yet" />
          )}
        </Card>

        <Card>
          <CardHeader
            title="Bus factor"
            hint="Topics where exactly one person holds the evidence"
          />
          {analytics.loading && !analytics.data ? (
            <Skeleton className="h-52 w-full" />
          ) : analytics.data?.bus_factor.length ? (
            <ul className="space-y-3">
              {analytics.data.bus_factor.map((entry) => (
                <li
                  key={entry.person}
                  className="border-b border-hairline pb-3 last:border-0 last:pb-0"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-medium text-ink">{entry.person}</p>
                    <span className="tabular text-xs text-ink-secondary">
                      {entry.solo_topic_count} solo topic
                      {entry.solo_topic_count === 1 ? "" : "s"}
                    </span>
                  </div>
                  <p className="mt-1.5 flex flex-wrap gap-1.5">
                    {entry.solo_topics.slice(0, 8).map((topic) => (
                      <Chip key={topic}>{topic}</Chip>
                    ))}
                    {entry.solo_topic_count > 8 ? (
                      <span className="text-xs text-ink-muted">
                        +{entry.solo_topic_count - 8} more
                      </span>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No single points of failure"
              hint="Every topic has at least two people with evidence."
            />
          )}
        </Card>
      </div>

      <p className="mt-4 text-xs leading-relaxed text-ink-muted">
        Bus factor is computed from extracted topics, so it reflects where work has been recorded —
        not a judgement about anyone. A long solo list usually means nobody else has touched that
        area yet, which is exactly the thing worth spreading.
      </p>
    </>
  );
}
