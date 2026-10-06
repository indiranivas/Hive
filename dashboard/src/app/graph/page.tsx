"use client";

import { useMemo, useState } from "react";
import { RelationshipRing, RingLegend, type RingLink, type RingNode } from "@/components/graph";
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
import { useApi } from "@/lib/hooks";

const VIEWS = [
  { key: "people", label: "People" },
  { key: "repos", label: "Repos" },
] as const;
type View = (typeof VIEWS)[number]["key"];

const KIND_LABELS: Record<string, string> = {
  org: "Organisation",
  team: "Team",
  person: "Person",
  repo: "Repo",
  module: "Module",
  topic: "Topic",
  artifact: "Artifact",
  kr: "Knowledge request",
};

/** Relationships worth spelling out in the detail panel, in reading order. */
const EDGE_COPY: Record<string, string> = {
  MANAGES: "manages",
  MEMBER_OF: "belongs to",
  PART_OF: "part of",
  COLLABORATES_WITH: "overlaps with",
  COUPLED_WITH: "moves with",
  WORKED_IN: "works in",
  AUTHORED: "authored",
  REVIEWED: "reviewed",
  KNOWS: "has evidence on",
  ABOUT: "about",
  IN_REPO: "lives in",
  TOUCHED: "touched",
  ASKED: "asked",
  ANSWERED: "answered",
  ROUTED_TO: "routed to",
  TAGGED: "tagged",
  REFERENCES: "cites",
};

export default function GraphPage() {
  const [view, setView] = useState<View>("people");
  const [selected, setSelected] = useState<string | null>(null);

  const graph = useApi(() => api.graph(), []);
  const bus = useApi(() => api.busFactor(), []);

  const model = useMemo(() => {
    if (!graph.data) return null;
    const { nodes, edges } = graph.data;
    const byId = new Map(nodes.map((node) => [node.id, node]));

    // Every person's team, so both views can be grouped by the org chart.
    const teamOf = new Map<string, string>();
    for (const edge of edges) {
      if (edge.kind === "MEMBER_OF") {
        teamOf.set(edge.source, byId.get(edge.target)?.label ?? "Unassigned");
      }
    }

    if (view === "people") {
      const authored = new Map<string, number>();
      for (const edge of edges) {
        if (edge.kind === "AUTHORED") {
          authored.set(edge.source, (authored.get(edge.source) ?? 0) + 1);
        }
      }
      const ringNodes: RingNode[] = nodes
        .filter((node) => node.kind === "person")
        .map((node) => ({
          id: node.id,
          label: node.label,
          group: teamOf.get(node.id) ?? "No team",
          weight: authored.get(node.id) ?? 0,
          sublabel: String(node.meta.role ?? ""),
        }));
      const ids = new Set(ringNodes.map((n) => n.id));
      const ringLinks: RingLink[] = edges
        .filter((e) => e.kind === "COLLABORATES_WITH" && ids.has(e.source) && ids.has(e.target))
        .map((e) => ({ source: e.source, target: e.target, weight: e.weight, kind: e.kind }));
      return { ringNodes, ringLinks, byId, edges, groupWord: "team" };
    }

    // Repos have no team of their own, so attribute each to whichever team does
    // the most work in it. Stated as attribution, never as ownership.
    const contribution = new Map<string, Map<string, number>>();
    const volume = new Map<string, number>();
    for (const edge of edges) {
      if (edge.kind !== "WORKED_IN") continue;
      const team = teamOf.get(edge.source) ?? "No team";
      const tally = contribution.get(edge.target) ?? new Map<string, number>();
      tally.set(team, (tally.get(team) ?? 0) + edge.weight);
      contribution.set(edge.target, tally);
      volume.set(edge.target, (volume.get(edge.target) ?? 0) + edge.weight);
    }
    const ringNodes: RingNode[] = nodes
      .filter((node) => node.kind === "repo")
      .map((node) => {
        const tally = [...(contribution.get(node.id) ?? new Map())].sort((a, b) => b[1] - a[1]);
        return {
          id: node.id,
          label: node.label,
          group: tally[0]?.[0] ?? "No team",
          weight: volume.get(node.id) ?? 0,
        };
      });
    const ids = new Set(ringNodes.map((n) => n.id));
    const ringLinks: RingLink[] = edges
      .filter((e) => e.kind === "COUPLED_WITH" && ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, weight: e.weight, kind: e.kind }));
    return { ringNodes, ringLinks, byId, edges, groupWord: "team" };
  }, [graph.data, view]);

  const detail = useMemo(() => {
    if (!model || !selected) return null;
    const node = model.byId.get(selected);
    if (!node) return null;
    const related = model.edges
      .filter((edge) => edge.source === selected || edge.target === selected)
      .map((edge) => {
        const otherId = edge.source === selected ? edge.target : edge.source;
        return {
          kind: edge.kind,
          direction: edge.source === selected ? "out" : "in",
          other: model.byId.get(otherId),
          weight: edge.weight,
        };
      })
      .filter((entry) => entry.other);
    const grouped = new Map<string, typeof related>();
    for (const entry of related) {
      grouped.set(entry.kind, [...(grouped.get(entry.kind) ?? []), entry]);
    }
    return { node, grouped: [...grouped.entries()].sort((a, b) => b[1].length - a[1].length) };
  }, [model, selected]);

  const composition = useMemo(() => {
    if (!graph.data) return null;
    const nodeKinds = new Map<string, number>();
    for (const node of graph.data.nodes) {
      nodeKinds.set(node.kind, (nodeKinds.get(node.kind) ?? 0) + 1);
    }
    const edgeKinds = new Map<string, number>();
    for (const edge of graph.data.edges) {
      edgeKinds.set(edge.kind, (edgeKinds.get(edge.kind) ?? 0) + 1);
    }
    return {
      nodeKinds: [...nodeKinds.entries()].sort((a, b) => b[1] - a[1]),
      edgeKinds: [...edgeKinds.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [graph.data]);

  return (
    <>
      <PageHeader
        title="Organisation map"
        subtitle="Who works with whom, and which repos move together — derived from the work trail, not an org chart someone maintained."
        action={
          <div className="flex items-center gap-1 rounded-lg border border-hairline p-0.5">
            {VIEWS.map((option) => (
              <button
                key={option.key}
                onClick={() => {
                  setView(option.key);
                  setSelected(null);
                }}
                className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                  view === option.key
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

      {graph.error ? (
        <ErrorState message={graph.error} detail={graph.detail} onRetry={graph.reload} />
      ) : null}

      {graph.data ? (
        <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="People" value={graph.data.nodes.filter((n) => n.kind === "person").length} />
          <Metric label="Repos" value={graph.data.nodes.filter((n) => n.kind === "repo").length} />
          <Metric
            label="Relationships"
            value={graph.data.edges.length}
            hint={`${composition?.edgeKinds.length ?? 0} kinds`}
          />
          <Metric
            label="Graph source"
            value={graph.data.provider}
            hint={
              graph.data.provider === "memory"
                ? "derived from SQL on every call"
                : "mirror — refresh with POST /api/graph/sync"
            }
          />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title={view === "people" ? "Collaboration" : "Repo coupling"}
            hint={
              view === "people"
                ? "People grouped by team; a line means shared repos or shared topics"
                : "Repos attributed to the team doing most of the work; a line means they move together"
            }
          />
          {graph.loading && !graph.data ? (
            <Skeleton className="h-96 w-full" />
          ) : model && model.ringNodes.length ? (
            <>
              <RelationshipRing
                nodes={model.ringNodes}
                links={model.ringLinks}
                selected={selected}
                onSelect={setSelected}
              />
              <RingLegend groupWord={model.groupWord} />
              {!model.ringLinks.length ? (
                <p className="mt-3 rounded-lg bg-surface-inset px-3 py-2 text-xs text-ink-muted">
                  No {view === "people" ? "collaboration" : "coupling"} links yet. Nodes are drawn,
                  but nothing connects them — ingest more repos so overlaps can appear.
                </p>
              ) : null}
            </>
          ) : (
            <EmptyState
              title={`No ${view} in the graph`}
              hint="Run an ingestion to populate the work trail: hive.cli ingest-git --repo <path>"
            />
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Selection" hint="Click any node in the ring" />
            {detail ? (
              <div>
                <p className="text-sm font-semibold text-ink">{detail.node.label}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                  <Chip>{KIND_LABELS[detail.node.kind] ?? detail.node.kind}</Chip>
                  {detail.node.meta.role ? <span>{String(detail.node.meta.role)}</span> : null}
                  {detail.node.meta.email ? (
                    <code className="font-mono text-[11px]">{String(detail.node.meta.email)}</code>
                  ) : null}
                </p>
                <div className="mt-3 space-y-3">
                  {detail.grouped.map(([kind, entries]) => (
                    <div key={kind}>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                        {EDGE_COPY[kind] ?? kind.toLowerCase().replace(/_/g, " ")} · {entries.length}
                      </p>
                      <ul className="mt-1 space-y-0.5">
                        {entries.slice(0, 8).map((entry, index) => (
                          <li key={index} className="truncate text-xs text-ink-secondary">
                            {entry.direction === "in" ? "← " : "→ "}
                            {entry.other!.label}
                          </li>
                        ))}
                        {entries.length > 8 ? (
                          <li className="text-xs text-ink-muted">+{entries.length - 8} more</li>
                        ) : null}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-ink-muted">
                Nothing selected. Hover a node to isolate its links; click to pin it and read every
                relationship it has across the whole graph — not just the ones drawn here.
              </p>
            )}
          </Card>

          <Card>
            <CardHeader title="Bus factor" hint="Topics resting on a single person" />
            {bus.error ? (
              <ErrorState message={bus.error} onRetry={bus.reload} />
            ) : bus.data?.at_risk.length ? (
              <ul className="space-y-1.5">
                {bus.data.at_risk.slice(0, 8).map((topic) => (
                  <li
                    key={`${topic.topic}-${topic.expert_id}`}
                    className="flex items-baseline justify-between gap-2 text-xs"
                  >
                    <span className="truncate text-ink-secondary">{topic.topic}</span>
                    <span className="shrink-0 text-ink-muted">{topic.expert_name}</span>
                  </li>
                ))}
                {bus.data.at_risk.length > 8 ? (
                  <li className="text-xs text-ink-muted">
                    +{bus.data.at_risk.length - 8} more topics with one expert
                  </li>
                ) : null}
              </ul>
            ) : bus.loading ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <EmptyState title="No single-expert topics" hint="Every scored topic has cover." />
            )}
          </Card>

          {composition ? (
            <Card>
              <CardHeader title="What the graph holds" hint="Every edge is derived from a table" />
              <div className="flex flex-wrap gap-1.5">
                {composition.nodeKinds.map(([kind, count]) => (
                  <Chip key={kind}>
                    {KIND_LABELS[kind] ?? kind} {count}
                  </Chip>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {composition.edgeKinds.map(([kind, count]) => (
                  <span
                    key={kind}
                    className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[10px] text-ink-muted"
                  >
                    {kind} {count}
                  </span>
                ))}
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader title="How to read this" />
        <ul className="space-y-2 text-sm text-ink-secondary">
          <li>
            <strong className="text-ink">Collaboration is inferred.</strong> A line between two
            people means they share repos or topics in the work trail — not that they have ever
            spoken. It is weighted <code className="font-mono text-xs">repos×2 + topics</code>.
          </li>
          <li>
            <strong className="text-ink">Coupling is not a dependency.</strong> Hive parses no
            manifests and no import graph. Two repos are linked when the same people change both,
            in the same week, or when a commit names the other repo. Treat it as a prompt to check.
          </li>
          <li>
            <strong className="text-ink">Position is stable.</strong> Nodes are placed
            deterministically, so the same data always draws the same picture and a node keeps its
            spot between visits.
          </li>
        </ul>
      </Card>
    </>
  );
}
