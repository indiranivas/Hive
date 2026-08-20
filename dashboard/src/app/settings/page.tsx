"use client";

import { useState } from "react";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Metric,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { API_BASE, api } from "@/lib/api";
import { relativeDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-hairline py-2.5 last:border-0">
      <span className="text-sm text-ink-secondary">{label}</span>
      <span className="text-right">
        <code className="font-mono text-xs text-ink">{value}</code>
        {hint ? <span className="ml-2 text-xs text-ink-muted">{hint}</span> : null}
      </span>
    </div>
  );
}

export default function SettingsPage() {
  const health = useApi(() => api.health(), []);
  const ingestion = useApi(() => api.ingestionStatus(), []);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);

  const runIngestion = async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const result = await api.triggerGitIngestion();
      setRunResult(
        result.runs.length
          ? `${result.runs.length} connector run(s) completed.`
          : "No git providers configured. Set GIT_LOCAL_REPOS, ADO_* or GITHUB_* in .env.",
      );
      ingestion.reload();
    } catch (caught) {
      setRunResult(caught instanceof Error ? caught.message : "Ingestion failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <PageHeader title="Settings" subtitle="Providers, connectors and what Hive is allowed to do." />

      <div className="grid gap-4 sm:grid-cols-3">
        {ingestion.data ? (
          <>
            <Metric label="Artifacts" value={ingestion.data.artifact_count} />
            <Metric label="Embedded chunks" value={ingestion.data.chunk_count} />
            <Metric label="People" value={ingestion.data.people_count} />
          </>
        ) : (
          Array.from({ length: 3 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-16" />
              <Skeleton className="mt-3 h-7 w-12" />
            </Card>
          ))
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Providers" hint="All swappable by environment variable" />
          {health.error ? (
            <ErrorState message={health.error} onRetry={health.reload} />
          ) : health.data ? (
            <div>
              <Row label="API" value={API_BASE} />
              <Row label="Environment" value={health.data.environment} />
              <Row
                label="LLM"
                value={health.data.llm_provider}
                hint={health.data.llm_provider === "stub" ? "extractive, no key" : undefined}
              />
              <Row
                label="Embeddings"
                value={health.data.embedding_provider}
                hint={health.data.embedding_provider === "hashing" ? "lexical, offline" : undefined}
              />
              <Row label="Vector store" value={health.data.vector_provider} />
              <Row label="Database" value={health.data.database} />
            </div>
          ) : (
            <Skeleton className="h-40 w-full" />
          )}
        </Card>

        <Card>
          <CardHeader
            title="Connectors"
            hint="Incremental: each keeps its own watermark"
            action={
              <Button size="sm" onClick={runIngestion} disabled={running}>
                {running ? "Running…" : "Run git ingestion"}
              </Button>
            }
          />
          {ingestion.error ? (
            <ErrorState message={ingestion.error} detail={ingestion.detail} onRetry={ingestion.reload} />
          ) : ingestion.data?.connectors.length ? (
            <ul className="space-y-3">
              {ingestion.data.connectors.map((connector) => (
                <li key={connector.connector} className="border-b border-hairline pb-3 last:border-0 last:pb-0">
                  <div className="flex items-center justify-between gap-2">
                    <code className="min-w-0 truncate font-mono text-xs text-ink">
                      {connector.connector}
                    </code>
                    <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-ink-secondary">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          connector.last_status === "ok"
                            ? "bg-good"
                            : connector.last_status === "error"
                              ? "bg-critical"
                              : "bg-axis"
                        }`}
                        aria-hidden
                      />
                      {connector.last_status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-ink-muted">
                    {connector.artifacts_ingested} ingested · last run{" "}
                    {relativeDate(connector.last_run_at)}
                  </p>
                  {connector.last_error ? (
                    <p className="mt-1 break-words text-xs text-critical">{connector.last_error}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No connector has run yet"
              hint="Point Hive at a repo: hive.cli ingest-git --repo <path>, or configure ADO_* / GITHUB_* and run it from here."
            />
          )}
          {runResult ? <p className="mt-3 text-xs text-ink-secondary">{runResult}</p> : null}
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Guardrails" hint="Enforced in code, not policy" />
        <ul className="space-y-2 text-sm text-ink-secondary">
          {[
            "Read-only. Hive never writes to email, tickets, repos or chat.",
            "No surveillance. Work artifacts only — no keystrokes, no screens, no productivity scores.",
            "Scoped access. Members see their own team; nobody sees up the org chart.",
            "Full audit trail. Every question is logged with who asked, when and via which surface.",
          ].map((line) => (
            <li key={line} className="flex items-start gap-2">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-good" aria-hidden />
              {line}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
