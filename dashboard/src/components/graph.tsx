"use client";

/* Relationship ring — hand-rolled inline SVG, no graph library.
 *
 * A force simulation was the obvious reach here and the wrong one: it settles
 * somewhere different on every load, so nobody can say "look at the top-left
 * cluster" twice. This layout is deterministic — the same data always draws the
 * same picture, and a node keeps its position when a filter changes, which is
 * what makes the picture readable as a *map* rather than a fresh puzzle.
 *
 * Nodes sit on a circle, grouped into contiguous arcs. Links are quadratic
 * curves bowed toward the centre in proportion to the angle they span, so short
 * hops stay near the rim and long ones cut across — the eye reads reach without
 * reading labels.
 */

import { useMemo, useState } from "react";

const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
];

export interface RingNode {
  id: string;
  label: string;
  group: string;
  weight: number;
  sublabel?: string;
}

export interface RingLink {
  source: string;
  target: string;
  weight: number;
  kind: string;
}

interface Placed extends RingNode {
  angle: number;
  x: number;
  y: number;
  radius: number;
  colour: string;
}

const SIZE = 720;
const CENTRE = SIZE / 2;
const RING = SIZE / 2 - 132; // leaves room for labels outside the ring

function polar(angle: number, radius: number) {
  return { x: CENTRE + radius * Math.cos(angle), y: CENTRE + radius * Math.sin(angle) };
}

/** Curve between two rim points, bowed toward the centre by how far apart they are. */
function chord(a: Placed, b: Placed) {
  let span = Math.abs(a.angle - b.angle);
  if (span > Math.PI) span = 2 * Math.PI - span;
  // 0 for neighbours (hug the rim), ~1 for opposites (cut through the middle).
  const pull = span / Math.PI;
  const mid = (a.angle + b.angle) / 2;
  const flip = Math.abs(a.angle - b.angle) > Math.PI ? Math.PI : 0;
  const control = polar(mid + flip, RING * (1 - 0.92 * pull));
  return `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${control.x.toFixed(1)},${control.y.toFixed(
    1,
  )} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
}

export function RelationshipRing({
  nodes,
  links,
  selected,
  onSelect,
  emptyLabel = "Nothing to draw yet.",
}: {
  nodes: RingNode[];
  links: RingLink[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  emptyLabel?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  const { placed, index, groups } = useMemo(() => {
    // Group order is alphabetical and nodes are sorted inside it, so position is
    // a pure function of the data — no dependence on API ordering.
    const names = Array.from(new Set(nodes.map((n) => n.group))).sort();
    const ordered = [...nodes].sort(
      (a, b) => names.indexOf(a.group) - names.indexOf(b.group) || a.label.localeCompare(b.label),
    );
    const maxWeight = Math.max(1, ...ordered.map((n) => n.weight));

    const step = ordered.length ? (2 * Math.PI) / ordered.length : 0;
    const placedNodes: Placed[] = ordered.map((node, i) => {
      const angle = i * step - Math.PI / 2; // start at 12 o'clock
      const { x, y } = polar(angle, RING);
      return {
        ...node,
        angle,
        x,
        y,
        radius: 4 + 7 * Math.sqrt(node.weight / maxWeight),
        colour: SERIES[names.indexOf(node.group) % SERIES.length],
      };
    });

    const byId = new Map(placedNodes.map((n) => [n.id, n]));
    const arcs = names.map((name) => {
      const members = placedNodes.filter((n) => n.group === name);
      return {
        name,
        colour: SERIES[names.indexOf(name) % SERIES.length],
        from: members[0].angle,
        to: members[members.length - 1].angle,
        mid: (members[0].angle + members[members.length - 1].angle) / 2,
        count: members.length,
      };
    });
    return { placed: placedNodes, index: byId, groups: arcs };
  }, [nodes]);

  if (!nodes.length) return <p className="p-6 text-sm text-ink-muted">{emptyLabel}</p>;

  const focus = hovered ?? selected;
  const drawn = links
    .map((link) => ({ link, a: index.get(link.source), b: index.get(link.target) }))
    .filter((entry): entry is { link: RingLink; a: Placed; b: Placed } => !!entry.a && !!entry.b);
  const maxLink = Math.max(1, ...drawn.map((d) => d.link.weight));
  const touches = (link: RingLink) =>
    !focus || link.source === focus || link.target === focus;

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="w-full"
      role="img"
      aria-label="Relationship graph"
    >
      {/* Group arcs sit outside the ring: the org structure, not a data series. */}
      {groups.map((group) => {
        const inner = polar(group.from - 0.06, RING + 26);
        const outer = polar(group.to + 0.06, RING + 26);
        const large = Math.abs(group.to - group.from) > Math.PI ? 1 : 0;
        const label = polar(group.mid, RING + 46);
        const flip = Math.cos(group.mid) < 0;
        return (
          <g key={group.name}>
            <path
              d={`M${inner.x},${inner.y} A${RING + 26},${RING + 26} 0 ${large} 1 ${outer.x},${outer.y}`}
              fill="none"
              stroke={group.colour}
              strokeWidth="3"
              strokeLinecap="round"
              opacity={0.55}
            />
            <text
              x={label.x}
              y={label.y}
              fontSize="13"
              fontWeight="600"
              fill="var(--text-secondary)"
              textAnchor="middle"
              transform={`rotate(${(group.mid * 180) / Math.PI + (flip ? 180 : 0)} ${label.x} ${label.y})`}
            >
              {group.name} · {group.count}
            </text>
          </g>
        );
      })}

      <g>
        {drawn.map(({ link, a, b }, i) => {
          const lit = touches(link);
          const crossGroup = a.group !== b.group;
          return (
            <path
              key={`${link.source}-${link.target}-${link.kind}-${i}`}
              d={chord(a, b)}
              fill="none"
              // Cross-group links are the signal worth seeing; same-group links
              // are expected, so they recede rather than compete.
              stroke={crossGroup ? "var(--series-2)" : "var(--series-1)"}
              strokeWidth={0.8 + 2.6 * (link.weight / maxLink)}
              strokeLinecap="round"
              opacity={lit ? (crossGroup ? 0.72 : 0.34) : 0.05}
            />
          );
        })}
      </g>

      <g>
        {placed.map((node) => {
          const lit =
            !focus ||
            node.id === focus ||
            drawn.some(
              ({ link }) =>
                (link.source === focus && link.target === node.id) ||
                (link.target === focus && link.source === node.id),
            );
          const isSelected = node.id === selected;
          const label = polar(node.angle, RING + 12);
          const flip = Math.cos(node.angle) < 0;
          return (
            <g
              key={node.id}
              onMouseEnter={() => setHovered(node.id)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => onSelect(isSelected ? null : node.id)}
              className="cursor-pointer"
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={node.radius + (isSelected ? 3 : 0)}
                fill={node.colour}
                stroke={isSelected ? "var(--text-primary)" : "var(--surface-1)"}
                strokeWidth={isSelected ? 2 : 1}
                opacity={lit ? 1 : 0.2}
              />
              <text
                x={label.x}
                y={label.y}
                fontSize="11"
                fill={isSelected ? "var(--text-primary)" : "var(--text-secondary)"}
                fontWeight={isSelected ? 600 : 400}
                opacity={lit ? 1 : 0.25}
                textAnchor={flip ? "end" : "start"}
                transform={`rotate(${(node.angle * 180) / Math.PI + (flip ? 180 : 0)} ${label.x} ${label.y})`}
              >
                {node.label.length > 22 ? `${node.label.slice(0, 21)}…` : node.label}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

/** Legend for the two link classes the ring distinguishes. */
export function RingLegend({ groupWord }: { groupWord: string }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
      {[
        { label: `Across ${groupWord}s`, colour: "var(--series-2)" },
        { label: `Within one ${groupWord}`, colour: "var(--series-1)" },
      ].map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-xs text-ink-secondary">
          <span className="h-0.5 w-4 rounded-full" style={{ background: item.colour }} aria-hidden />
          {item.label}
        </li>
      ))}
      <li className="text-xs text-ink-muted">Node size = volume of work · line width = strength</li>
    </ul>
  );
}
