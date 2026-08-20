"use client";

import { useState } from "react";
import { ExpertiseGraph, TopicBars } from "@/components/charts";
import {
  Avatar,
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
import { avatarTint, initials, relativeDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Expert } from "@/lib/types";

export default function ExpertisePage() {
  const map = useApi(() => api.expertiseMap(), []);
  const [topic, setTopic] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [experts, setExperts] = useState<Expert[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const search = async (value: string) => {
    const needle = value.trim();
    if (!needle) return;
    setSearching(true);
    setSearchError(null);
    setSubmitted(needle);
    try {
      const result = await api.searchExperts(needle);
      setExperts(result.experts);
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "Search failed");
      setExperts(null);
    } finally {
      setSearching(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Expertise map"
        subtitle="Who has evidence on what — scored from artifact frequency and recency."
      />

      <Card className="mb-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            search(topic);
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Who knows… billing-service, jwt-auth, react"
            className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface-inset px-3 py-2 text-sm text-ink placeholder:text-ink-muted"
          />
          <button
            type="submit"
            disabled={searching || !topic.trim()}
            className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-surface-0 disabled:opacity-45"
          >
            {searching ? "Searching…" : "Find experts"}
          </button>
        </form>

        {searchError ? <p className="mt-3 text-sm text-critical">{searchError}</p> : null}

        {experts ? (
          experts.length ? (
            <ul className="mt-4 space-y-3">
              {experts.map((expert, index) => (
                <li key={expert.person_id} className="flex items-start gap-3">
                  <span className="tabular w-4 shrink-0 pt-1.5 text-xs text-ink-muted">
                    {index + 1}
                  </span>
                  <Avatar name={initials(expert.display_name)} tint={avatarTint(expert.display_name)} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <p className="text-sm font-medium text-ink">{expert.display_name}</p>
                      <span className="text-xs text-ink-muted">{expert.email}</span>
                      <span className="tabular ml-auto text-xs text-ink-secondary">
                        score {expert.score.toFixed(2)}
                      </span>
                    </div>
                    <p className="mt-1 flex flex-wrap gap-1.5">
                      {expert.topics.slice(0, 6).map((item) => (
                        <Chip key={item} tone={item === submitted ? "accent" : "neutral"}>
                          {item}
                        </Chip>
                      ))}
                    </p>
                    <p className="mt-1 text-[11px] text-ink-muted">
                      {expert.evidence_count} artifacts · last seen {relativeDate(expert.last_seen)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title={`No evidence for "${submitted}"`}
              hint="Nobody on this team has work artifacts on that topic. Raise a Knowledge Request instead."
            />
          )
        ) : null}
      </Card>

      {map.error ? <ErrorState message={map.error} detail={map.detail} onRetry={map.reload} /> : null}

      <div className="grid gap-4 sm:grid-cols-3">
        {map.data ? (
          <>
            <Metric label="People with evidence" value={map.data.people.length} />
            <Metric label="Distinct topics" value={map.data.topics.length} />
            <Metric
              label="Bus-factor 1 topics"
              value={map.data.solo_topics.length}
              hint="Only one person has evidence"
            />
          </>
        ) : (
          Array.from({ length: 3 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-12" />
            </Card>
          ))
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Topics by coverage" hint="Click a topic to find its experts" />
          {map.loading && !map.data ? (
            <Skeleton className="h-64 w-full" />
          ) : map.data?.topics.length ? (
            <TopicBars
              items={map.data.topics.slice(0, 14).map((entry) => ({
                label: entry.topic,
                value: entry.links,
                note: `${entry.people} ${entry.people === 1 ? "person" : "people"}`,
              }))}
              onSelect={(label) => {
                setTopic(label);
                search(label);
              }}
            />
          ) : (
            <EmptyState title="No topics extracted yet" hint="Ingest some work first." />
          )}
        </Card>

        <Card>
          <CardHeader title="Topic to people" hint="Hover a row to isolate its links" />
          {map.loading && !map.data ? (
            <Skeleton className="h-64 w-full" />
          ) : map.data ? (
            <ExpertiseGraph links={map.data.links} soloTopics={map.data.solo_topics} />
          ) : null}
        </Card>
      </div>
    </>
  );
}
