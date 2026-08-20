"use client";

import { useState } from "react";
import {
  Avatar,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ARTIFACT_LABELS, LEVEL_COPY, avatarTint, initials, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { StatusResult } from "@/lib/types";

function weekOffsetISO(offset: number): string | undefined {
  if (offset === 0) return undefined;
  const date = new Date();
  date.setDate(date.getDate() + offset * 7);
  return date.toISOString().slice(0, 10);
}

function StatusCard({ status }: { status: StatusResult }) {
  const [open, setOpen] = useState(false);
  const level = LEVEL_COPY[status.activity_level];

  return (
    <Card>
      <div className="flex items-start gap-3">
        <Avatar name={initials(status.person_name)} tint={avatarTint(status.person_name)} size={36} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h3 className="text-sm font-semibold text-ink">{status.person_name}</h3>
            <span className="text-xs text-ink-muted">{status.role}</span>
            <span className={`ml-auto text-xs ${level?.tone ?? "text-ink-muted"}`}>
              {level?.label ?? status.activity_level}
            </span>
          </div>

          <div className="mt-3 space-y-1.5">
            {status.summary.split("\n").map((line, index) =>
              line.trim() ? (
                <p
                  key={index}
                  className={`text-sm leading-relaxed ${
                    line.startsWith("(") ? "text-ink-muted" : "text-ink-secondary"
                  }`}
                >
                  {line}
                </p>
              ) : null,
            )}
          </div>

          {status.evidence.length ? (
            <>
              <button
                onClick={() => setOpen((value) => !value)}
                className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
              >
                {open ? "Hide" : "Show"} {status.evidence.length} evidence item
                {status.evidence.length === 1 ? "" : "s"}
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 12 12"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className={open ? "rotate-180" : ""}
                  aria-hidden
                >
                  <path d="M3 4.5 6 7.5 9 4.5" />
                </svg>
              </button>
              {open ? (
                <ul className="mt-2 space-y-2 border-l border-hairline pl-3">
                  {status.evidence.map((item) => (
                    <li key={item.artifact_id} className="text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <Chip>{ARTIFACT_LABELS[item.type] ?? item.type}</Chip>
                        <span className="text-ink">{item.title}</span>
                        {item.reference ? (
                          <code className="font-mono text-[11px] text-ink-muted">
                            {item.reference}
                          </code>
                        ) : null}
                        <span className="ml-auto text-ink-muted">{shortDate(item.date)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <p className="mt-3 text-xs text-ink-muted">No artifacts in this period.</p>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function StatusPage() {
  const [offset, setOffset] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const week = weekOffsetISO(offset);
  const status = useApi(() => api.teamStatus(week), [offset]);

  const regenerate = async () => {
    setRefreshing(true);
    try {
      await api.teamStatus(week, true);
      status.reload();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Auto status"
        subtitle={
          status.data
            ? `Week of ${status.data.period_start} to ${status.data.period_end} — generated from commits, PRs and tickets.`
            : "Weekly per-person status, generated from the work trail."
        }
        action={
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg border border-hairline p-0.5">
              <Button size="sm" variant="quiet" onClick={() => setOffset((value) => value - 1)}>
                ← Previous
              </Button>
              <Button
                size="sm"
                variant="quiet"
                onClick={() => setOffset(0)}
                disabled={offset === 0}
              >
                This week
              </Button>
              <Button
                size="sm"
                variant="quiet"
                onClick={() => setOffset((value) => Math.min(0, value + 1))}
                disabled={offset === 0}
              >
                Next →
              </Button>
            </div>
            <Button size="sm" onClick={regenerate} disabled={refreshing}>
              {refreshing ? "Regenerating…" : "Regenerate"}
            </Button>
          </div>
        }
      />

      {status.error ? (
        <ErrorState message={status.error} detail={status.detail} onRetry={status.reload} />
      ) : null}

      {status.loading && !status.data ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-4 w-32" />
              <Skeleton className="mt-3 h-3 w-full" />
              <Skeleton className="mt-2 h-3 w-4/5" />
            </Card>
          ))}
        </div>
      ) : status.data?.statuses.length ? (
        <>
          <div className="space-y-4">
            {status.data.statuses.map((entry) => (
              <StatusCard key={entry.person_id} status={entry} />
            ))}
          </div>
          <p className="mt-4 text-xs text-ink-muted">
            Summaries come from{" "}
            <code className="text-ink-secondary">{status.data.statuses[0]?.model}</code>. Every
            bullet is traceable to an artifact above — Hive does not score people.
          </p>
        </>
      ) : (
        <EmptyState
          title="No statuses for this week"
          hint="Nobody on the team has ingested activity in this period."
        />
      )}
    </>
  );
}
