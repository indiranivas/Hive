"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Metric,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { SOURCE_LABELS, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";

const PILLARS = [
  {
    title: "The problem",
    body:
      "What a team knows is spread across commits, pull requests, tickets and chat, or it lives in someone's head. People lose hours finding the right person, managers rebuild status by hand, and when someone leaves, what they knew goes with them.",
  },
  {
    title: "What Hive does",
    body:
      "Hive reads the work trail the team already produces, with no extra data entry. It answers questions in plain English with the commit or PR behind each claim, maps who knows what, and drafts the weekly status.",
  },
  {
    title: "Why it is safe to trust",
    body:
      "Read-only: Hive never writes to your tools. Every answer cites its source. When the evidence isn't there, Hive says so and routes the question to the person most likely to know.",
  },
];

const TOUR = [
  { href: "/ask", title: "Ask Hive", why: "Ask a question in plain English and get an answer with sources. Also in Teams and the code editor." },
  { href: "/graph", title: "Org map", why: "Who actually works with whom, based on the work itself rather than the org chart." },
  { href: "/expertise", title: "Expertise", why: "Find the right person for a topic in seconds." },
  { href: "/status", title: "Auto status", why: "Weekly updates drafted from the work, with no status meeting." },
  { href: "/knowledge/gaps", title: "Gap analytics", why: "Questions nobody could answer: where documentation and training are missing." },
  { href: "/", title: "Team pulse", why: "What shipped this week, and what is stuck." },
];

function NumberField({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
}) {
  return (
    <label className="block">
      <span className="text-xs text-ink-muted">{label}</span>
      <input
        type="number"
        min={0}
        step={step}
        value={value}
        onChange={(event) => onChange(Math.max(0, Number(event.target.value) || 0))}
        className="tabular mt-1 w-full rounded-lg border border-hairline bg-surface-0 px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none"
      />
    </label>
  );
}

/** A projection from the viewer's own inputs, kept visibly apart from measured numbers. */
function ScaleCalculator({ defaultMinutes }: { defaultMinutes: number }) {
  const [people, setPeople] = useState(200);
  const [perWeek, setPerWeek] = useState(3);
  const [minutes, setMinutes] = useState(defaultMinutes);
  const [rate, setRate] = useState(30);
  const WORK_WEEKS = 46;
  const FTE_HOURS = 1760;

  const hoursPerYear = (people * perWeek * minutes * WORK_WEEKS) / 60;
  const fte = hoursPerYear / FTE_HOURS;
  const value = hoursPerYear * rate;

  return (
    <Card>
      <CardHeader
        title="What this means at LevelShift scale"
        hint="A projection from the inputs you enter. Not a measurement. Change any number."
      />
      <div className="grid gap-3 sm:grid-cols-4">
        <NumberField label="People using Hive" value={people} onChange={setPeople} />
        <NumberField label="Questions per person / week" value={perWeek} onChange={setPerWeek} />
        <NumberField label="Minutes saved per question" value={minutes} onChange={setMinutes} />
        <NumberField label="Loaded cost per hour (USD)" value={rate} onChange={setRate} />
      </div>
      <div className="mt-5 grid gap-4 border-t border-hairline pt-5 sm:grid-cols-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-ink-muted">Hours returned / year</p>
          <p className="tabular mt-1 text-2xl font-semibold text-ink">
            {Math.round(hoursPerYear).toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-ink-muted">Full-time equivalents</p>
          <p className="tabular mt-1 text-2xl font-semibold text-ink">{fte.toFixed(1)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-ink-muted">Value / year</p>
          <p className="tabular mt-1 text-2xl font-semibold text-ink">
            ${Math.round(value).toLocaleString()}
          </p>
        </div>
      </div>
      <p className="mt-4 text-xs leading-relaxed text-ink-muted">
        People × questions × minutes × {WORK_WEEKS} working weeks. One FTE = {FTE_HOURS.toLocaleString()} hours.
        This counts question-answering only; status reports and onboarding would add to it.
      </p>
    </Card>
  );
}

export default function OverviewPage() {
  const overview = useApi(() => api.overview(), []);
  const data = overview.data;

  return (
    <>
      <PageHeader
        title="Leadership overview"
        subtitle="Hive on one page: the problem, what it does, and what it has done so far. Every number is counted from the work trail."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {PILLARS.map((pillar) => (
          <Card key={pillar.title}>
            <h2 className="text-sm font-semibold text-accent">{pillar.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-secondary">{pillar.body}</p>
          </Card>
        ))}
      </div>

      {overview.error ? (
        <div className="mt-4">
          <ErrorState message={overview.error} detail={overview.detail} onRetry={overview.reload} />
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {overview.loading && !data ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-16" />
            </Card>
          ))
        ) : data ? (
          <>
            <Metric
              label="Work captured"
              value={data.trail.artifacts.toLocaleString()}
              hint={`From ${data.trail.people} people, ${data.trail.teams} teams and ${data.trail.repos} repos. No one typed any of it in.`}
            />
            <Metric
              label="Questions answered"
              value={data.questions.answered_with_evidence}
              hint={
                data.questions.total
                  ? `${Math.round((data.questions.answer_rate ?? 0) * 100)}% answered with sources${
                      data.questions.median_latency_ms
                        ? `, in about ${Math.round(data.questions.median_latency_ms / 1000)}s`
                        : ""
                    }`
                  : "Ask the first question on the Ask Hive page"
              }
            />
            <Metric
              label="Expert answers kept for reuse"
              value={data.knowledge.answered}
              hint={
                data.knowledge.median_hours_to_answer !== null
                  ? `Typically answered in ${data.knowledge.median_hours_to_answer}h · ${data.knowledge.open} still open`
                  : `${data.knowledge.open} questions waiting for an expert`
              }
            />
            <Metric
              label="Hours saved so far"
              value={data.time_saved.hours}
              hint="Estimated from counts. See the breakdown below."
            />
          </>
        ) : null}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="How the hours-saved figure is built"
            hint="Count × minutes each. The minutes are conservative assumptions, shown so they can be challenged."
          />
          {data ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-xs text-ink-muted">
                  <th className="pb-2 font-medium">What Hive did</th>
                  <th className="pb-2 text-right font-medium">Count</th>
                  <th className="pb-2 text-right font-medium">Min each</th>
                  <th className="pb-2 text-right font-medium">Hours</th>
                </tr>
              </thead>
              <tbody>
                {data.time_saved.breakdown.map((row) => (
                  <tr key={row.label} className="border-b border-hairline last:border-0">
                    <td className="py-2 pr-2 text-ink-secondary">{row.label}</td>
                    <td className="tabular py-2 text-right text-ink">{row.count}</td>
                    <td className="tabular py-2 text-right text-ink-muted">{row.minutes_each}</td>
                    <td className="tabular py-2 text-right font-medium text-ink">{row.hours}</td>
                  </tr>
                ))}
                <tr>
                  <td className="pt-3 font-medium text-ink" colSpan={3}>
                    Total
                  </td>
                  <td className="tabular pt-3 text-right font-semibold text-ink">
                    {data.time_saved.hours}
                  </td>
                </tr>
              </tbody>
            </table>
          ) : (
            <Skeleton className="h-32 w-full" />
          )}
        </Card>

        <ScaleCalculator
          defaultMinutes={data?.time_saved.breakdown[0]?.minutes_each ?? 20}
        />
      </div>

      <Card className="mt-4">
        <CardHeader
          title="Where knowledge rests on one person"
          hint="Share of each repo's work done by its top contributor. Above 60%, that person is a single point of failure."
          action={
            data ? (
              <span className="text-xs text-ink-muted">
                {data.expertise.areas_at_risk} of {data.expertise.areas.length} repos at risk
              </span>
            ) : null
          }
        />
        {data?.expertise.areas.length ? (
          <ul className="space-y-3">
            {data.expertise.areas.map((area) => (
              <li key={area.repo}>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium text-ink">
                    {area.repo}
                    {area.at_risk ? (
                      <span className="ml-2 inline-flex items-center gap-1 text-xs font-normal text-ink-secondary">
                        <span className="h-2 w-2 rounded-full bg-warning" aria-hidden />
                        At risk
                      </span>
                    ) : null}
                  </span>
                  <span className="tabular text-xs text-ink-muted">
                    {Math.round(area.top_share * 100)}% by {area.top_person} · {area.contributors}{" "}
                    {area.contributors === 1 ? "person" : "people"} · {area.artifacts} items
                  </span>
                </div>
                <div className="mt-1.5 h-2 rounded-full bg-surface-inset">
                  <div
                    className="h-2 rounded-full"
                    style={{
                      width: `${Math.max(4, area.top_share * 100)}%`,
                      background: area.at_risk ? "var(--status-warning)" : "var(--series-1)",
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>
        ) : data ? (
          <EmptyState title="No repository work ingested yet" />
        ) : (
          <Skeleton className="h-32 w-full" />
        )}
      </Card>

      <Card className="mt-4">
        <CardHeader title="See it working" hint="Each page is live on the same data" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TOUR.map((stop, index) => (
            <Link
              key={stop.href}
              href={stop.href}
              className="group rounded-lg border border-hairline p-4 transition-colors hover:border-accent hover:bg-surface-2"
            >
              <p className="text-xs text-ink-muted">Step {index + 1}</p>
              <p className="mt-1 text-sm font-semibold text-ink group-hover:text-accent">
                {stop.title} →
              </p>
              <p className="mt-1 text-xs leading-relaxed text-ink-secondary">{stop.why}</p>
            </Link>
          ))}
        </div>
      </Card>

      <Card className="mt-4">
        <CardHeader
          title="Sources"
          hint={
            data?.trail.first_seen
              ? `Work trail from ${shortDate(data.trail.first_seen)} to ${shortDate(data.trail.last_seen)}`
              : "Each source added makes every answer richer"
          }
        />
        <div className="flex flex-wrap gap-2">
          {data
            ? Object.entries(data.trail.sources).map(([source, live]) => (
                <span
                  key={source}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                    live ? "border-hairline text-ink" : "border-dashed border-hairline text-ink-muted"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-good" : "bg-axis"}`} aria-hidden />
                  {SOURCE_LABELS[source] ?? source}
                  {live ? " · live" : " · on the roadmap"}
                </span>
              ))
            : null}
        </div>
      </Card>
    </>
  );
}
