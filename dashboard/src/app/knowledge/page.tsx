"use client";

import { useState } from "react";
import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  Inline,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { hours, relativeDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { KnowledgeRequest } from "@/lib/types";

const FILTERS = [
  { key: "", label: "All" },
  { key: "open", label: "Open" },
  { key: "answered", label: "Answered" },
] as const;

function AnswerForm({ kr, onAnswered }: { kr: KnowledgeRequest; onAnswered: () => void }) {
  const [answer, setAnswer] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (answer.trim().length < 3) return;
    setSaving(true);
    setError(null);
    try {
      await api.answerKnowledgeRequest(kr.id, answer.trim());
      setAnswer("");
      onAnswered();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="mt-3 border-t border-hairline pt-3">
      <textarea
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        rows={3}
        placeholder="Answer this once and Hive will answer it for everyone from now on…"
        className="w-full resize-y rounded-lg border border-hairline bg-surface-inset px-3 py-2 text-sm text-ink placeholder:text-ink-muted"
      />
      <div className="mt-2 flex items-center gap-2">
        <Button type="submit" variant="solid" size="sm" disabled={saving || answer.trim().length < 3}>
          {saving ? "Saving…" : "Answer and index"}
        </Button>
        <p className="text-xs text-ink-muted">
          Indexed into the knowledge repo, so the next person gets the answer, not the gap.
        </p>
      </div>
      {error ? <p className="mt-2 text-xs text-critical">{error}</p> : null}
    </form>
  );
}

function RequestCard({ kr, onChanged }: { kr: KnowledgeRequest; onChanged: () => void }) {
  const answered = kr.status === "answered" || kr.status === "indexed";
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 flex-1 text-sm font-medium text-ink">{kr.question}</h3>
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${
            answered ? "border-hairline text-ink-secondary" : "border-warning/40 text-warning"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${answered ? "bg-good" : "bg-warning"}`}
            aria-hidden
          />
          {answered ? "Answered" : "Open"}
        </span>
      </div>

      {kr.context ? <p className="mt-1.5 text-xs text-ink-muted">Context: {kr.context}</p> : null}

      {kr.answer ? (
        <div className="mt-3 rounded-lg bg-surface-inset p-3">
          <p className="whitespace-pre-line text-sm leading-relaxed text-ink-secondary">
            <Inline text={kr.answer} />
          </p>
        </div>
      ) : null}

      {!answered && kr.routed_to ? (
        <p className="mt-2 text-xs text-ink-secondary">
          Routed to <span className="font-medium text-ink">{kr.routed_to}</span> — they have the
          strongest recent evidence on these topics.
        </p>
      ) : null}
      {!answered && !kr.routed_to ? (
        <p className="mt-2 text-xs text-ink-muted">
          No obvious expert — open to whoever can answer it.
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        {kr.tags.map((tag) => (
          <Chip key={tag}>{tag}</Chip>
        ))}
        <span className="ml-auto flex flex-wrap items-center gap-x-3">
          <span>asked by {kr.requester ?? "unknown"} {relativeDate(kr.created_at)}</span>
          {answered ? (
            <span>
              answered by {kr.answered_by ?? "unknown"}
              {kr.resolution_hours !== null ? ` in ${hours(kr.resolution_hours)}` : ""}
            </span>
          ) : null}
        </span>
      </div>

      {!answered ? <AnswerForm kr={kr} onAnswered={onChanged} /> : null}
    </Card>
  );
}

export default function KnowledgePage() {
  const [filter, setFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [asking, setAsking] = useState(false);
  const [newQuestion, setNewQuestion] = useState("");

  const requests = useApi(
    () => api.knowledgeRequests({ status: filter || undefined, search: debounced || undefined }),
    [filter, debounced],
  );

  const raise = async (event: React.FormEvent) => {
    event.preventDefault();
    if (newQuestion.trim().length < 3) return;
    setAsking(true);
    try {
      await api.createKnowledgeRequest(newQuestion.trim());
      setNewQuestion("");
      requests.reload();
    } finally {
      setAsking(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Knowledge repo"
        subtitle="Answered questions become permanent, searchable team knowledge."
      />

      <Card className="mb-4">
        <form onSubmit={raise} className="flex flex-wrap items-center gap-2">
          <input
            value={newQuestion}
            onChange={(event) => setNewQuestion(event.target.value)}
            placeholder="Raise a Knowledge Request…"
            className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface-inset px-3 py-2 text-sm text-ink placeholder:text-ink-muted"
          />
          <Button type="submit" variant="solid" disabled={asking || newQuestion.trim().length < 3}>
            {asking ? "Raising…" : "Raise request"}
          </Button>
        </form>
      </Card>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-lg border border-hairline p-0.5">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              onClick={() => setFilter(option.key)}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                filter === option.key
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-ink-secondary hover:text-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setDebounced(search);
          }}
          className="flex min-w-0 flex-1 items-center gap-2"
        >
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search questions and answers…"
            className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface-inset px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted"
          />
          <Button type="submit" size="sm">
            Search
          </Button>
          {debounced ? (
            <Button
              size="sm"
              variant="quiet"
              onClick={() => {
                setSearch("");
                setDebounced("");
              }}
            >
              Clear
            </Button>
          ) : null}
        </form>
        {requests.data ? (
          <span className="tabular text-xs text-ink-muted">{requests.data.count} shown</span>
        ) : null}
      </div>

      {requests.error ? (
        <ErrorState message={requests.error} detail={requests.detail} onRetry={requests.reload} />
      ) : null}

      {requests.loading && !requests.data ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="mt-3 h-3 w-full" />
            </Card>
          ))}
        </div>
      ) : requests.data?.items.length ? (
        <div className="space-y-4">
          {requests.data.items.map((kr) => (
            <RequestCard key={kr.id} kr={kr} onChanged={requests.reload} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="Nothing here yet"
          hint={
            debounced
              ? "No request matches that search."
              : "When Hive cannot answer a question it offers to raise a request. Answers land here."
          }
        />
      )}
    </>
  );
}
