"use client";

import { useEffect, useState } from "react";
import { Button, Card, Chip, EmptyState, Inline, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { ARTIFACT_LABELS, shortDate } from "@/lib/format";
import type { QueryResponse } from "@/lib/types";

const EXAMPLES = [
  "Who fixed the JWT refresh loop?",
  "What changed in the billing service recently?",
  "Who has touched the ingestion pipeline?",
];

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [asked, setAsked] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [raised, setRaised] = useState<string | null>(null);

  const ask = async (value: string) => {
    const text = value.trim();
    if (!text) return;
    setAsking(true);
    setError(null);
    setRaised(null);
    setAsked(text);
    try {
      setResult(await api.ask(text));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Query failed");
      setResult(null);
    } finally {
      setAsking(false);
    }
  };

  // `/ask?q=...` asks on arrival, so the presentation can deep-link a live question.
  // Deferred to a timer so a dev-mode double mount (cleared by the cleanup) asks once.
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("q");
    if (!initial) return;
    const timer = setTimeout(() => {
      setQuestion(initial);
      ask(initial);
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const raiseRequest = async () => {
    const kr = await api.createKnowledgeRequest(asked);
    setRaised(kr.id);
  };

  return (
    <>
      <PageHeader
        title="Ask Hive"
        subtitle="The same engine behind @Hive in Teams. Every answer carries its sources."
      />

      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            ask(question);
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask anything about your team's work…"
              className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface-inset px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-muted"
            />
            <Button type="submit" variant="solid" disabled={asking || !question.trim()}>
              {asking ? "Thinking…" : "Ask"}
            </Button>
          </div>
        </form>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((example) => (
            <Chip
              key={example}
              onClick={() => {
                setQuestion(example);
                ask(example);
              }}
            >
              {example}
            </Chip>
          ))}
        </div>
      </Card>

      {error ? (
        <Card className="mt-4">
          <p className="text-sm text-critical">{error}</p>
        </Card>
      ) : null}

      {result ? (
        <Card className="mt-4">
          <p className="text-xs text-ink-muted">You asked</p>
          <p className="mt-0.5 text-sm font-medium text-ink">{asked}</p>

          <div className="mt-4 space-y-2">
            {result.answer.split("\n").map((line, index) =>
              line.trim() ? (
                <p
                  key={index}
                  className={`text-sm leading-relaxed ${
                    line.trim().startsWith("(") ? "text-ink-muted" : "text-ink-secondary"
                  }`}
                >
                  <Inline text={line} />
                </p>
              ) : null,
            )}
          </div>

          {result.sources.length ? (
            <div className="mt-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Sources
              </p>
              <ul className="space-y-2">
                {result.sources.map((source, index) => (
                  <li
                    key={source.artifact_id}
                    className="rounded-lg border border-hairline bg-surface-inset p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="tabular text-ink-muted">{index + 1}</span>
                      <Chip>{ARTIFACT_LABELS[source.type] ?? source.type}</Chip>
                      <span className="text-ink-secondary">{source.author ?? "unknown"}</span>
                      <span className="text-ink-muted">{shortDate(source.date)}</span>
                      {source.reference ? (
                        <code className="font-mono text-[11px] text-ink-secondary">
                          {source.reference}
                        </code>
                      ) : null}
                      <span className="tabular ml-auto text-ink-muted">
                        rel {source.relevance.toFixed(2)}
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm text-ink">{source.title}</p>
                    {source.excerpt ? (
                      <p className="mt-1 line-clamp-2 text-xs text-ink-muted">{source.excerpt}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {result.has_gap ? (
            <div className="mt-5 rounded-lg border border-dashed border-hairline p-4">
              {raised ? (
                <p className="text-sm text-ink-secondary">
                  Knowledge Request recorded. Track it in the knowledge repo.
                </p>
              ) : (
                <>
                  <p className="text-sm text-ink">Hive could not answer this from the work trail.</p>
                  <p className="mt-1 text-xs text-ink-muted">
                    Raising a request records the gap so an expert can answer it once, for everyone.
                  </p>
                  <div className="mt-3">
                    <Button variant="solid" size="sm" onClick={raiseRequest}>
                      Raise a Knowledge Request
                    </Button>
                  </div>
                </>
              )}
            </div>
          ) : null}

          {result.rewrites.length ? (
            <p className="mt-4 rounded-lg bg-surface-inset px-3 py-2 text-xs text-ink-muted">
              First pass looked weak, so Hive re-searched for{" "}
              {result.rewrites.map((rewrite, index) => (
                <span key={rewrite}>
                  {index > 0 ? ", then " : ""}
                  <code className="font-mono text-ink-secondary">{rewrite}</code>
                </span>
              ))}
              .
            </p>
          ) : null}

          <p className="mt-4 flex flex-wrap gap-x-3 text-[11px] text-ink-muted">
            <span>model {result.model}</span>
            <span>{result.sources.length} sources</span>
            <span className="tabular">{result.latency_ms}ms</span>
            <span>
              {result.attempts} retrieval pass{result.attempts === 1 ? "" : "es"}
            </span>
          </p>
        </Card>
      ) : !asking && !error ? (
        <div className="mt-4">
          <EmptyState
            title="Ask a question to get started"
            hint="Hive answers only from ingested commits, PRs, tickets, email and meetings — and tells you when it has nothing."
          />
        </div>
      ) : null}
    </>
  );
}
