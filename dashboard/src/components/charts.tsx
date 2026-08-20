"use client";

/* Hand-rolled inline SVG charts.
 * Rules applied from the data-viz method: one axis, fixed categorical slot order
 * (never cycled), 2px surface gaps between stacked segments, 4px rounded data
 * ends, recessive grid/axes, a legend whenever there are 2+ series, direct value
 * labels (the light-mode palette carries a sub-3:1 contrast warning, and visible
 * labels are the required relief), and a hover layer on every plotted form. */

import { useState } from "react";
import { ACTIVITY_SERIES } from "@/lib/format";
import type { ActivityWeek } from "@/lib/types";

const BAR_RADIUS = 4;
const SEGMENT_GAP = 2;

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-xs text-ink-secondary">
          <span
            className="h-2.5 w-2.5 rounded-sm"
            style={{ background: item.color }}
            aria-hidden
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** Stacked weekly activity. Series slots are fixed, so a stream with no data
 *  leaves its colour unused rather than shifting the others. */
export function ActivityBars({ weeks }: { weeks: ActivityWeek[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const present = ACTIVITY_SERIES.filter((series) =>
    weeks.some((week) => (week[series.key] ?? 0) > 0),
  );
  const max = Math.max(1, ...weeks.map((week) => week.total));
  const height = 168;
  const barWidth = 26;

  if (!weeks.length) return null;

  return (
    <div className="relative">
      <div
        className="flex items-end justify-between gap-1 overflow-x-auto pb-1"
        style={{ height: height + 34 }}
      >
        {weeks.map((week, index) => {
          const total = week.total;
          let offset = 0;
          const segments = present
            .map((series) => {
              const value = week[series.key] ?? 0;
              if (!value) return null;
              const raw = (value / max) * height;
              const segmentHeight = Math.max(3, raw - SEGMENT_GAP);
              const bottom = offset;
              offset += raw;
              return { series, value, segmentHeight, bottom };
            })
            .filter(Boolean) as {
            series: (typeof ACTIVITY_SERIES)[number];
            value: number;
            segmentHeight: number;
            bottom: number;
          }[];

          return (
            <div
              key={week.week}
              className="group flex min-w-0 flex-1 flex-col items-center gap-1.5"
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover(null)}
            >
              <span
                className={`tabular text-[11px] ${total ? "text-ink-secondary" : "text-ink-muted"}`}
              >
                {total || ""}
              </span>
              <div
                className="relative w-full rounded-t transition-opacity"
                style={{ height, maxWidth: barWidth }}
              >
                {segments.map(({ series, segmentHeight, bottom }, segmentIndex) => (
                  <div
                    key={series.key}
                    className="absolute inset-x-0"
                    style={{
                      background: series.color,
                      height: segmentHeight,
                      bottom,
                      borderTopLeftRadius: segmentIndex === segments.length - 1 ? BAR_RADIUS : 0,
                      borderTopRightRadius: segmentIndex === segments.length - 1 ? BAR_RADIUS : 0,
                      opacity: hover === null || hover === index ? 1 : 0.45,
                    }}
                  />
                ))}
                {!total ? (
                  <div className="absolute inset-x-0 bottom-0 h-px bg-axis" aria-hidden />
                ) : null}
              </div>
              <span className="tabular whitespace-nowrap text-[10px] text-ink-muted">
                {week.week.slice(5)}
              </span>
            </div>
          );
        })}
      </div>

      {hover !== null && weeks[hover] ? (
        <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-center">
          <div className="rounded-lg border border-hairline bg-surface-1 px-3 py-2 text-xs shadow-lg">
            <p className="mb-1 font-medium text-ink">Week of {weeks[hover].week}</p>
            {present.map((series) => (
              <p key={series.key} className="flex items-center gap-2 text-ink-secondary">
                <span
                  className="h-2 w-2 rounded-sm"
                  style={{ background: series.color }}
                  aria-hidden
                />
                {series.label}
                <span className="tabular ml-auto text-ink">{weeks[hover][series.key] ?? 0}</span>
              </p>
            ))}
          </div>
        </div>
      ) : null}

      {present.length >= 2 ? <Legend items={present.map((s) => ({ label: s.label, color: s.color }))} /> : null}
      {present.length === 1 ? (
        <p className="mt-3 text-xs text-ink-muted">
          Only {present[0].label.toLowerCase()} so far — other streams land as connectors are added.
        </p>
      ) : null}
    </div>
  );
}

/** Horizontal magnitude bars, one series -- single hue, no legend, values labelled. */
export function TopicBars({
  items,
  emptyLabel = "No topics yet",
  onSelect,
}: {
  items: { label: string; value: number; note?: string }[];
  emptyLabel?: string;
  onSelect?: (label: string) => void;
}) {
  const max = Math.max(1, ...items.map((item) => item.value));
  if (!items.length) return <p className="text-sm text-ink-muted">{emptyLabel}</p>;

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.label}>
          <button
            onClick={onSelect ? () => onSelect(item.label) : undefined}
            className={`group flex w-full items-center gap-3 rounded-lg px-1 py-1 text-left ${
              onSelect ? "hover:bg-surface-2" : "cursor-default"
            }`}
          >
            <span className="w-36 shrink-0 truncate text-xs text-ink-secondary" title={item.label}>
              {item.label}
            </span>
            <span className="h-2.5 min-w-0 flex-1 rounded-full bg-surface-inset">
              <span
                className="block h-2.5 rounded-full"
                style={{
                  width: `${Math.max(3, (item.value / max) * 100)}%`,
                  background: "var(--series-1)",
                }}
              />
            </span>
            <span className="tabular w-10 shrink-0 text-right text-xs text-ink">{item.value}</span>
            {item.note ? (
              <span className="w-24 shrink-0 truncate text-right text-[11px] text-ink-muted">
                {item.note}
              </span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Raised vs answered per week.
 *  Grouped bars rather than lines: these are sparse integer counts, and an area
 *  between two isolated events implies a continuous trend that is not there. */
export function TrendChart({
  points,
}: {
  points: { week: string; new: number; resolved: number }[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const series = [
    { key: "new" as const, label: "Raised", color: "var(--series-1)" },
    { key: "resolved" as const, label: "Answered", color: "var(--series-2)" },
  ];
  const max = Math.max(1, ...points.flatMap((point) => [point.new, point.resolved]));
  const height = 150;

  if (!points.length) return <p className="text-sm text-ink-muted">No history yet.</p>;

  return (
    <div className="relative">
      <div className="flex items-end gap-1" style={{ height: height + 36 }}>
        {points.map((point, index) => {
          const empty = point.new === 0 && point.resolved === 0;
          return (
            <div
              key={point.week}
              className="flex min-w-0 flex-1 flex-col items-center gap-1.5"
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover(null)}
            >
              <div className="flex w-full items-end justify-center gap-[3px]" style={{ height }}>
                {series.map((entry) => {
                  const value = point[entry.key];
                  return (
                    <div
                      key={entry.key}
                      className="relative flex w-full max-w-3 justify-center"
                      style={{ height: "100%" }}
                    >
                      {value > 0 ? (
                        <>
                          <span className="tabular absolute -top-4 text-[10px] text-ink-secondary">
                            {value}
                          </span>
                          <span
                            className="absolute bottom-0 w-full rounded-t"
                            style={{
                              height: Math.max(4, (value / max) * height),
                              background: entry.color,
                              opacity: hover === null || hover === index ? 1 : 0.45,
                            }}
                          />
                        </>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              <span
                className={`tabular whitespace-nowrap text-[10px] ${
                  empty ? "text-ink-muted" : "text-ink-secondary"
                }`}
              >
                {point.week.slice(5)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-1 h-px w-full bg-axis" aria-hidden />

      {hover !== null && points[hover] ? (
        <div className="pointer-events-none absolute right-2 top-0 rounded-lg border border-hairline bg-surface-1 px-2.5 py-1.5 text-xs shadow-lg">
          <p className="mb-1 font-medium text-ink">Week of {points[hover].week}</p>
          {series.map((entry) => (
            <p key={entry.key} className="flex items-center gap-2 text-ink-secondary">
              <span className="h-2 w-2 rounded-sm" style={{ background: entry.color }} aria-hidden />
              {entry.label}
              <span className="tabular ml-auto text-ink">{points[hover][entry.key]}</span>
            </p>
          ))}
        </div>
      ) : null}

      <Legend items={series.map((entry) => ({ label: entry.label, color: entry.color }))} />
    </div>
  );
}

/** Bipartite topic <-> people diagram. Deterministic layout beats a force
 *  simulation here: the same data always draws the same picture. */
export function ExpertiseGraph({
  links,
  soloTopics,
}: {
  links: { topic: string; person: string; score: number }[];
  soloTopics: string[];
}) {
  const [focus, setFocus] = useState<string | null>(null);

  const topics = Array.from(new Set(links.map((link) => link.topic))).slice(0, 14);
  const people = Array.from(new Set(links.map((link) => link.person)));
  const visible = links.filter((link) => topics.includes(link.topic));

  if (!visible.length) return <p className="text-sm text-ink-muted">No expertise evidence yet.</p>;

  const rowHeight = 26;
  const height = Math.max(topics.length, people.length) * rowHeight + 24;
  const width = 560;
  const leftX = 150;
  const rightX = width - 150;

  const topicY = (topic: string) => 20 + topics.indexOf(topic) * rowHeight;
  const personY = (person: string) =>
    20 + people.indexOf(person) * (Math.max(topics.length, people.length) / people.length) * rowHeight;

  const dim = (value: string) => focus !== null && focus !== value;

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Topics linked to people">
        {visible.map((link, index) => {
          const y1 = topicY(link.topic);
          const y2 = personY(link.person);
          const faded = dim(link.topic) && dim(link.person);
          return (
            <path
              key={index}
              d={`M${leftX},${y1} C${(leftX + rightX) / 2},${y1} ${(leftX + rightX) / 2},${y2} ${rightX},${y2}`}
              fill="none"
              stroke="var(--series-1)"
              strokeWidth={Math.min(3, 1 + link.score / 2)}
              opacity={faded ? 0.08 : 0.42}
            />
          );
        })}

        {topics.map((topic) => (
          <g
            key={topic}
            onMouseEnter={() => setFocus(topic)}
            onMouseLeave={() => setFocus(null)}
            className="cursor-default"
          >
            <text
              x={leftX - 8}
              y={topicY(topic) + 3.5}
              textAnchor="end"
              fontSize="11"
              fill={dim(topic) ? "var(--text-muted)" : "var(--text-primary)"}
            >
              {topic.length > 22 ? `${topic.slice(0, 21)}…` : topic}
            </text>
            {soloTopics.includes(topic) ? (
              <circle cx={leftX - 2} cy={topicY(topic)} r="3" fill="var(--status-warning)" />
            ) : (
              <circle cx={leftX - 2} cy={topicY(topic)} r="2.5" fill="var(--series-1)" />
            )}
          </g>
        ))}

        {people.map((person) => (
          <g
            key={person}
            onMouseEnter={() => setFocus(person)}
            onMouseLeave={() => setFocus(null)}
          >
            <circle cx={rightX + 2} cy={personY(person)} r="3" fill="var(--series-2)" />
            <text
              x={rightX + 10}
              y={personY(person) + 3.5}
              fontSize="11"
              fill={dim(person) ? "var(--text-muted)" : "var(--text-primary)"}
            >
              {person}
            </text>
          </g>
        ))}
      </svg>
      <p className="mt-2 flex items-center gap-2 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-warning" aria-hidden />
          bus-factor 1
        </span>
        <span aria-hidden>·</span>
        <span>only one person has evidence on that topic</span>
      </p>
    </div>
  );
}
