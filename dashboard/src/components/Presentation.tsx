"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { LeadershipOverview } from "@/lib/types";

/* The deck is a fixed 1280×720 stage scaled to the window, so every slide
 * looks the same on a laptop, a projector or a shared screen. It always uses
 * its own dark palette: the screenshots are dark, and a room projector washes
 * out a light deck. */
const STAGE_W = 1280;
const STAGE_H = 720;

type Slide = {
  id: string;
  criteria?: string[];
  notes: string;
  live?: { href: string; label: string };
  body: (ctx: { data: LeadershipOverview | null }) => ReactNode;
};

/* ------------------------------------------------------------------ pieces */

function Kicker({ children }: { children: ReactNode }) {
  return <p className="deck-kicker">{children}</p>;
}

function Hex({ size = 28, stroke = "var(--d-accent)", fill = "none", width = 2.2 }: {
  size?: number;
  stroke?: string;
  fill?: string;
  width?: number;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <path
        d="M12 2.6 20.4 7.3v9.4L12 21.4 3.6 16.7V7.3z"
        fill={fill}
        stroke={stroke}
        strokeWidth={width}
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** A browser-window frame around a real screenshot of the running prototype. */
function Shot({ src, alt, width = 760, url }: { src: string; alt: string; width?: number; url: string }) {
  return (
    <figure className="deck-shot" style={{ width }}>
      <div className="deck-shot-bar">
        <span />
        <span />
        <span />
        <p>localhost:3000{url}</p>
      </div>
      <Image src={src} alt={alt} width={1440} height={900} className="block h-auto w-full" priority />
    </figure>
  );
}

function Callout({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="deck-callout">
      <span className="deck-num">{n}</span>
      <div>
        <p className="deck-callout-title">{title}</p>
        <p className="deck-callout-body">{children}</p>
      </div>
    </div>
  );
}

function Card({ title, children, accent }: { title: string; children: ReactNode; accent?: boolean }) {
  return (
    <div className={`deck-card ${accent ? "deck-card-accent" : ""}`}>
      <p className="deck-card-title">{title}</p>
      <div className="deck-card-body">{children}</div>
    </div>
  );
}

/* Honeycomb backdrop for the title and closing slides. */
function Honeycomb() {
  const cells = [];
  for (let row = 0; row < 7; row += 1) {
    for (let col = 0; col < 12; col += 1) {
      const x = col * 112 + (row % 2) * 56;
      const y = row * 97;
      const lit = (row * 7 + col * 3) % 11 === 0;
      cells.push(
        <path
          key={`${row}-${col}`}
          transform={`translate(${x} ${y})`}
          d="M56 0 104 28v56L56 112 8 84V28z"
          fill={lit ? "rgba(242,176,30,0.10)" : "none"}
          stroke="rgba(242,176,30,0.10)"
          strokeWidth="1.5"
        />,
      );
    }
  }
  return (
    <svg className="deck-honeycomb" viewBox="0 0 1344 700" preserveAspectRatio="xMidYMid slice" aria-hidden>
      {cells}
    </svg>
  );
}

/* ---------------------------------------------------------- illustrations */

function ToolGlyph({ kind }: { kind: string }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (kind) {
    case "git":
      return (
        <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden>
          <circle cx="6" cy="5" r="2.2" {...p} />
          <circle cx="6" cy="19" r="2.2" {...p} />
          <circle cx="18" cy="9" r="2.2" {...p} />
          <path d="M6 7.2v9.6M18 11.2c0 4-6 3-11 6" {...p} />
        </svg>
      );
    case "board":
      return (
        <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden>
          <rect x="3" y="4" width="18" height="16" rx="2" {...p} />
          <path d="M9 4v16M15 4v16M5 8h2M11 8h2M11 12h2M17 8h2" {...p} />
        </svg>
      );
    case "mail":
      return (
        <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden>
          <rect x="3" y="5" width="18" height="14" rx="2" {...p} />
          <path d="m3.5 6 8.5 7 8.5-7" {...p} />
        </svg>
      );
    case "chat":
      return (
        <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden>
          <path d="M20 14a3 3 0 0 1-3 3H9l-5 3V7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3z" {...p} />
          <path d="M8 9h8M8 12h5" {...p} />
        </svg>
      );
    case "doc":
      return (
        <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden>
          <path d="M6 3h8l4 4v14H6z" {...p} />
          <path d="M14 3v4h4M9 12h6M9 16h6" {...p} />
        </svg>
      );
    default:
      return (
        <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden>
          <circle cx="12" cy="8" r="4" {...p} />
          <path d="M4 21c1-4.5 4.5-6.5 8-6.5s7 2 8 6.5" {...p} />
        </svg>
      );
  }
}

/** Five tools, nobody searching all of them, and a person with a question. */
function ScatteredTools() {
  const tools = [
    { kind: "git", label: "Git", x: 40, y: 30, r: -6 },
    { kind: "board", label: "Azure DevOps", x: 230, y: 0, r: 4 },
    { kind: "mail", label: "Outlook", x: 400, y: 60, r: -3 },
    { kind: "chat", label: "Teams", x: 110, y: 190, r: 5 },
    { kind: "doc", label: "Docs", x: 330, y: 210, r: -5 },
  ];
  return (
    <div className="relative" style={{ width: 540, height: 330 }}>
      <svg className="absolute inset-0" width="540" height="330" aria-hidden>
        {tools.map((tool) => (
          <line
            key={tool.label}
            x1={tool.x + 55}
            y1={tool.y + 50}
            x2={270}
            y2={150}
            stroke="rgba(255,255,255,0.12)"
            strokeDasharray="4 6"
            strokeWidth="1.5"
          />
        ))}
      </svg>
      {tools.map((tool) => (
        <div
          key={tool.label}
          className="deck-tool"
          style={{ left: tool.x, top: tool.y, transform: `rotate(${tool.r}deg)` }}
        >
          <ToolGlyph kind={tool.kind} />
          <span>{tool.label}</span>
        </div>
      ))}
      <div className="deck-asker">
        <ToolGlyph kind="person" />
        <span className="deck-q">?</span>
      </div>
    </div>
  );
}

/** Sources → Hive → what people get. */
function FlowDiagram() {
  const left = ["Git commits & PRs", "Azure DevOps", "Email threads", "Teams calls"];
  const right = ["Answers with citations", "Who-knows-what map", "Auto weekly status", "Gaps routed to experts"];
  const ys = [60, 150, 240, 330];
  return (
    <svg viewBox="0 0 1100 390" width="1100" height="390" aria-label="Data flows from work tools into Hive and out as answers">
      <defs>
        <linearGradient id="flowL" x1="0" x2="1">
          <stop offset="0" stopColor="#3987e5" stopOpacity="0.15" />
          <stop offset="1" stopColor="#f2b01e" stopOpacity="0.9" />
        </linearGradient>
        <linearGradient id="flowR" x1="0" x2="1">
          <stop offset="0" stopColor="#f2b01e" stopOpacity="0.9" />
          <stop offset="1" stopColor="#1baf7a" stopOpacity="0.25" />
        </linearGradient>
      </defs>
      {ys.map((y, i) => (
        <g key={`l${i}`}>
          <path d={`M250 ${y} C 380 ${y}, 400 195, 470 195`} stroke="url(#flowL)" strokeWidth="2.5" fill="none" className="deck-flow" />
          <rect x="20" y={y - 26} width="230" height="52" rx="12" fill="#1c1c1a" stroke={i === 0 ? "#3fbf7f" : "#34342f"} />
          <text x="40" y={y + 6} fill="#e9e8e1" fontSize="17" fontWeight="500">{left[i]}</text>
          <text x="232" y={y + 5} fill={i === 0 ? "#3fbf7f" : "#8f8e86"} fontSize="11" textAnchor="end">{i === 0 ? "live" : "next"}</text>
        </g>
      ))}
      <g transform="translate(470 85)">
        <path d="M80 0 160 46v128L80 220 0 174V46z" fill="rgba(242,176,30,0.10)" stroke="#f2b01e" strokeWidth="3" strokeLinejoin="round" />
        <text x="80" y="104" textAnchor="middle" fill="#f2b01e" fontSize="30" fontWeight="700">Hive</text>
        <text x="80" y="130" textAnchor="middle" fill="#c9c8bf" fontSize="12">read · index · reason</text>
      </g>
      {ys.map((y, i) => (
        <g key={`r${i}`}>
          <path d={`M630 195 C 700 195, 720 ${y}, 850 ${y}`} stroke="url(#flowR)" strokeWidth="2.5" fill="none" className="deck-flow" />
          <rect x="850" y={y - 26} width="230" height="52" rx="12" fill="#1c1c1a" stroke="#34342f" />
          <text x="870" y={y + 6} fill="#e9e8e1" fontSize="17" fontWeight="500">{right[i]}</text>
        </g>
      ))}
    </svg>
  );
}

/** The AI pipeline: why this is a real AI use case, not a search box. */
function PipelineDiagram() {
  const steps = [
    { t: "Ingest", d: "Commits, PRs, reviews pulled read-only" },
    { t: "Understand", d: "LLM extracts topics; text chunked and embedded" },
    { t: "Retrieve", d: "Vector + keyword search over the trail" },
    { t: "Grade", d: "AI judges if the evidence answers the question" },
    { t: "Answer", d: "Plain English, every claim cited" },
  ];
  return (
    <svg viewBox="0 0 1180 330" width="1180" height="330" aria-label="Hive's AI pipeline">
      {steps.map((step, i) => {
        const x = 10 + i * 236;
        return (
          <g key={step.t}>
            <rect x={x} y="40" width="200" height="120" rx="16" fill={i === 3 ? "rgba(242,176,30,0.10)" : "#1c1c1a"} stroke={i === 3 ? "#f2b01e" : "#34342f"} strokeWidth="1.5" />
            <circle cx={x + 30} cy="72" r="14" fill="#f2b01e" />
            <text x={x + 30} y="77" textAnchor="middle" fill="#0e0e0d" fontSize="14" fontWeight="700">{i + 1}</text>
            <text x={x + 54} y="78" fill="#f3f2ec" fontSize="19" fontWeight="600">{step.t}</text>
            <foreignObject x={x + 16} y="96" width="172" height="60">
              <p style={{ color: "#b9b8af", fontSize: 13, lineHeight: 1.4, margin: 0 }}>{step.d}</p>
            </foreignObject>
            {i < steps.length - 1 ? (
              <path d={`M${x + 204} 100 h28`} stroke="#5a5a54" strokeWidth="2" markerEnd="url(#arrow)" />
            ) : null}
          </g>
        );
      })}
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 10 5 0 10z" fill="#5a5a54" />
        </marker>
      </defs>
      {/* weak evidence loop */}
      <path d="M818 160 C 818 230, 590 230, 590 165" stroke="#f2b01e" strokeWidth="2" fill="none" strokeDasharray="5 5" markerEnd="url(#arrowA)" />
      <text x="704" y="242" textAnchor="middle" fill="#f2b01e" fontSize="13">weak evidence → rewrite the query, retry once</text>
      <path d="M908 160 v80 h62" stroke="#8f8e86" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
      <rect x="975" y="212" width="200" height="60" rx="12" fill="#1c1c1a" stroke="#34342f" />
      <text x="992" y="238" fill="#f3f2ec" fontSize="15" fontWeight="600">Still no evidence?</text>
      <text x="992" y="258" fill="#b9b8af" fontSize="12.5">Say so · route to the expert</text>
      <defs>
        <marker id="arrowA" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 10 5 0 10z" fill="#f2b01e" />
        </marker>
      </defs>
    </svg>
  );
}

function Architecture() {
  const layers = [
    { name: "Where people use it", items: ["Dashboard", "@Hive in Teams", "VS Code (MCP)"], tone: "#f2b01e" },
    { name: "Hive engine", items: ["FastAPI", "LangGraph retrieval", "Expertise graph", "Audit log"], tone: "#3987e5" },
    { name: "AI & storage", items: ["Azure OpenAI", "ChromaDB vectors", "Neo4j / SQL graph", "Postgres"], tone: "#1baf7a" },
    { name: "Connectors (read-only)", items: ["Git  ✓", "Azure DevOps", "M365 email", "Teams calls"], tone: "#8f8e86" },
  ];
  return (
    <div className="space-y-3">
      {layers.map((layer) => (
        <div key={layer.name} className="deck-layer" style={{ borderLeftColor: layer.tone }}>
          <p className="w-[210px] shrink-0 text-[14px] font-semibold uppercase tracking-wider" style={{ color: layer.tone }}>
            {layer.name}
          </p>
          <div className="flex flex-wrap gap-2">
            {layer.items.map((item) => (
              <span key={item} className="deck-pill">{item}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Roadmap() {
  const stops = [
    { when: "Today", what: "Working prototype", detail: "Git, dashboard, Teams bot, Claude MCP, Neo4j", done: true },
    { when: "Next", what: "Azure DevOps", detail: "Work items and boards: on-track and blockers" },
    { when: "Then", what: "Email & meetings", detail: "M365 threads and Teams call transcripts" },
    { when: "Later", what: "Org-wide memory", detail: "Every team, one expertise graph" },
  ];
  return (
    <div className="relative mt-10">
      <div className="absolute left-0 right-0 top-[11px] h-[3px] rounded-full bg-[color:var(--d-hairline)]" />
      <div className="absolute left-0 top-[11px] h-[3px] w-[14%] rounded-full bg-[color:var(--d-accent)]" />
      <div className="relative grid grid-cols-4 gap-6">
        {stops.map((stop) => (
          <div key={stop.when}>
            <span
              className="block h-[25px] w-[25px] rounded-full border-[3px]"
              style={{
                borderColor: stop.done ? "var(--d-accent)" : "var(--d-hairline)",
                background: stop.done ? "var(--d-accent)" : "var(--d-bg)",
              }}
            />
            <p className="mt-4 text-[14px] font-semibold uppercase tracking-wider text-[color:var(--d-accent)]">{stop.when}</p>
            <p className="mt-1 text-[22px] font-semibold text-[color:var(--d-ink)]">{stop.what}</p>
            <p className="mt-1 text-[15px] leading-snug text-[color:var(--d-ink-2)]">{stop.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Eight things Hive does, at a glance. */
function CapabilityGrid() {
  const items = [
    { icon: "ask", t: "Ask anything", d: "Plain-English answers over the work trail, every claim cited" },
    { icon: "people", t: "Who knows what", d: "Expertise scored from real commits and answers, not skill tags" },
    { icon: "graph", t: "Knowledge graph", d: "People, repos, topics and questions linked in Neo4j" },
    { icon: "status", t: "Auto status", d: "Each person's weekly update drafted from their work" },
    { icon: "route", t: "Gap routing", d: "Unanswered questions sent to the likely expert, then indexed" },
    { icon: "radius", t: "Blast radius", d: "What else moves when a repo changes, and who to tell" },
    { icon: "history", t: "Prior art", d: "“Has anyone hit this error before?” Who fixed it, and how" },
    { icon: "risk", t: "Bus-factor alerts", d: "Repos and topics that rest on a single person" },
  ];
  const glyph = (name: string) => {
    const p = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
    switch (name) {
      case "ask":
        return <path d="M20 14a3 3 0 0 1-3 3H9l-5 3V7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3z" {...p} />;
      case "people":
        return (
          <>
            <circle cx="9" cy="8" r="3" {...p} />
            <path d="M3 20c.8-3.5 3.4-5 6-5s5.2 1.5 6 5M16 5.5a3 3 0 0 1 0 5.5M18 15c1.5.6 2.6 2.2 3 5" {...p} />
          </>
        );
      case "graph":
        return (
          <>
            <circle cx="6" cy="6" r="2.5" {...p} />
            <circle cx="18" cy="8" r="2.5" {...p} />
            <circle cx="10" cy="18" r="2.5" {...p} />
            <path d="M8.3 7 15.6 7.6M7 8.3l2.2 7.3M16.7 10.2l-4.8 6" {...p} />
          </>
        );
      case "status":
        return (
          <>
            <rect x="4" y="3" width="16" height="18" rx="2" {...p} />
            <path d="M8 8h8M8 12h8M8 16h5" {...p} />
          </>
        );
      case "route":
        return <path d="M4 6h10a4 4 0 0 1 0 8H8a4 4 0 0 0 0 8h12M17 19l3 3-3 3" {...p} transform="translate(0 -3)" />;
      case "radius":
        return (
          <>
            <circle cx="12" cy="12" r="2.5" {...p} />
            <circle cx="12" cy="12" r="6" {...p} strokeDasharray="3 3" />
            <circle cx="12" cy="12" r="9.5" {...p} strokeDasharray="2 4" />
          </>
        );
      case "history":
        return (
          <>
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" {...p} />
            <path d="M3 3v5h5M12 7v5l3 2" {...p} />
          </>
        );
      default:
        return (
          <>
            <path d="M12 3 22 20H2z" {...p} />
            <path d="M12 10v4M12 17h.01" {...p} />
          </>
        );
    }
  };
  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map((item) => (
        <div key={item.t} className="deck-cap">
          <span className="deck-cap-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden>
              {glyph(item.icon)}
            </svg>
          </span>
          <p className="deck-cap-title">{item.t}</p>
          <p className="deck-cap-body">{item.d}</p>
        </div>
      ))}
    </div>
  );
}

/** The knowledge graph's schema: every edge is derived from a table. Label
 *  positions are placed by hand so no two collide where lines cross. */
function GraphSchema() {
  const nodes: Record<string, { x: number; y: number; c: string }> = {
    Person: { x: 250, y: 220, c: "#f2b01e" },
    Team: { x: 70, y: 80, c: "#8f8e86" },
    Topic: { x: 480, y: 70, c: "#1baf7a" },
    Repo: { x: 530, y: 330, c: "#3987e5" },
    Artifact: { x: 290, y: 405, c: "#e87ba4" },
    KR: { x: 60, y: 345, c: "#eb6834" },
  };
  const edges: { a: string; b: string; label: string; at: [number, number] }[] = [
    { a: "Person", b: "Team", label: "MEMBER_OF", at: [150, 140] },
    { a: "Person", b: "Topic", label: "KNOWS", at: [345, 160] },
    { a: "Person", b: "Repo", label: "WORKED_IN", at: [425, 290] },
    { a: "Person", b: "Artifact", label: "AUTHORED · REVIEWED", at: [262, 322] },
    { a: "Person", b: "KR", label: "ASKED · ANSWERED", at: [140, 268] },
    { a: "Artifact", b: "Repo", label: "IN_REPO", at: [420, 375] },
    { a: "Artifact", b: "Topic", label: "ABOUT", at: [436, 160] },
  ];
  const mono = "var(--font-geist-mono), monospace";
  return (
    <svg viewBox="0 0 640 450" width="640" height="450" aria-label="Hive knowledge graph schema">
      {edges.map(({ a, b }) => (
        <path
          key={`${a}-${b}`}
          d={`M${nodes[a].x} ${nodes[a].y} L ${nodes[b].x} ${nodes[b].y}`}
          stroke="#45453f"
          strokeWidth="2"
          fill="none"
        />
      ))}
      {/* derived edges: no row behind them, computed from shared work */}
      <path d="M232 182 C 200 105, 300 105, 268 182" stroke="#f2b01e" strokeWidth="2" strokeDasharray="5 4" fill="none" />
      <text x="250" y="104" textAnchor="middle" fill="#f2b01e" fontSize="11.5" fontFamily={mono}>COLLABORATES_WITH</text>
      <path d="M562 312 C 640 270, 640 390, 560 350" stroke="#3987e5" strokeWidth="2" strokeDasharray="5 4" fill="none" />
      <text x="585" y="410" textAnchor="middle" fill="#3987e5" fontSize="11.5" fontFamily={mono}>COUPLED_WITH</text>
      {edges.map(({ label, at: [x, y] }) => (
        <g key={label}>
          <rect x={x - label.length * 3.6 - 6} y={y - 11} width={label.length * 7.2 + 12} height="22" rx="6" fill="#0e0e0d" stroke="#31312c" />
          <text x={x} y={y + 4} textAnchor="middle" fill="#c4c3ba" fontSize="11.5" fontFamily={mono}>
            {label}
          </text>
        </g>
      ))}
      {Object.entries(nodes).map(([name, n]) => (
        <g key={name}>
          <circle cx={n.x} cy={n.y} r={name === "Person" ? 42 : 34} fill="#181816" stroke={n.c} strokeWidth="2.5" />
          <text x={n.x} y={n.y + 5} textAnchor="middle" fill="#f3f2ec" fontSize={name === "Person" ? 16 : 14} fontWeight="600">
            {name}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Claude in the editor talking to Hive over MCP, with a real tool exchange. */
function McpConversation() {
  return (
    <div className="deck-editor">
      <div className="deck-editor-bar">
        <span />
        <span />
        <span />
        <p>Claude Code · VS Code</p>
      </div>
      <div className="space-y-3 p-5 text-[14.5px] leading-relaxed">
        <div className="deck-msg deck-msg-user">
          Getting a token refresh loop on 401s in billing auth. Has anyone seen this?
        </div>
        <div className="deck-tool-call">
          <span className="text-[color:var(--d-accent)]">▸ hive_prior_art</span>
          <span className="text-[color:var(--d-ink-3)]"> (&quot;401 errors cause a token refresh loop in billing auth&quot;)</span>
        </div>
        <div className="deck-tool-result">
          <p>
            <b>1. Deepa V</b>: Fix JWT refresh loop in billing auth middleware · 2d ago
          </p>
          <p className="text-[color:var(--d-ink-3)]">billing-service@a1b2c3d4 · services/billing/auth_middleware.py</p>
          <p>“Cache the refreshed token for its full TTL and retry once.”</p>
          <p className="mt-1">
            <b>2. Deepa V</b>: PR #312 Billing auth layer hardening
          </p>
          <p className="mt-1 text-[color:var(--d-ink-3)]">
            Note: 4 people worked on this. Compare approaches before applying.
          </p>
        </div>
        <div className="deck-msg deck-msg-claude">
          Your team already fixed this. Deepa V cached the refreshed token for its TTL in commit <code>a1b2c3d4</code>. I&rsquo;ll apply the same
          pattern here; Deepa is the person to ask if it doesn&rsquo;t hold.
        </div>
      </div>
    </div>
  );
}

function McpTools() {
  const tools = [
    ["hive_prior_art", "Has the team hit this before?"],
    ["hive_blast_radius", "What moves if I change this?"],
    ["hive_area_briefing", "Brief me on unfamiliar code"],
    ["hive_who_knows", "Who has evidence on a topic"],
    ["hive_ask", "Any question, answered with citations"],
    ["hive_raise_request", "Log a gap, route to an expert"],
  ];
  return (
    <div className="grid gap-2.5">
      {tools.map(([name, what]) => (
        <div key={name} className="deck-mcp-tool">
          <code>{name}</code>
          <span>{what}</span>
        </div>
      ))}
    </div>
  );
}

/** One engine behind three surfaces. */
function Surfaces() {
  const surfaces = [
    { t: "Dashboard", d: "Pulse, status, org map, expertise, gaps", tag: "Next.js" },
    { t: "@Hive in Teams", d: "Ask in chat; answers come as Adaptive Cards with sources", tag: "Bot Framework" },
    { t: "Claude in the editor", d: "Six MCP tools Claude calls while you code", tag: "MCP · stdio" },
  ];
  return (
    <svg viewBox="0 0 1100 250" width="1100" height="250" aria-label="One engine behind three surfaces">
      <g transform="translate(450 150)">
        <rect x="0" y="0" width="200" height="80" rx="16" fill="rgba(242,176,30,0.10)" stroke="#f2b01e" strokeWidth="2" />
        <text x="100" y="36" textAnchor="middle" fill="#f2b01e" fontSize="22" fontWeight="700">Hive engine</text>
        <text x="100" y="60" textAnchor="middle" fill="#c4c3ba" fontSize="12.5">one API · one graph · one index</text>
      </g>
      {surfaces.map((s, i) => {
        const x = 20 + i * 370;
        return (
          <g key={s.t}>
            <path d={`M${x + 165} 92 C ${x + 165} 130, 550 120, 550 150`} stroke="#5a5a54" strokeWidth="2" fill="none" className="deck-flow" />
            <rect x={x} y="0" width="330" height="92" rx="14" fill="#181816" stroke="#31312c" />
            <text x={x + 20} y="34" fill="#f3f2ec" fontSize="19" fontWeight="600">{s.t}</text>
            <text x={x + 310} y="33" fill="#f2b01e" fontSize="11.5" textAnchor="end" fontFamily="var(--font-geist-mono), monospace">{s.tag}</text>
            <foreignObject x={x + 20} y="44" width="290" height="44">
              <p style={{ color: "#b9b8af", fontSize: 13.5, lineHeight: 1.4, margin: 0 }}>{s.d}</p>
            </foreignObject>
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ slides */

const SLIDES: Slide[] = [
  {
    id: "title",
    notes: "This is Hive: a team's memory, built automatically from the work it already does.",
    body: () => (
      <div className="relative flex h-full flex-col justify-center overflow-hidden px-[96px]">
        <Honeycomb />
        <div className="relative">
          <Kicker>Internal hackathon · Reimagine</Kicker>
          <div className="flex items-center gap-5">
            <Hex size={92} width={2.4} />
            <h1 className="text-[120px] font-bold leading-none tracking-[-0.04em] text-[color:var(--d-ink)]">Hive</h1>
          </div>
          <p className="mt-8 max-w-[800px] text-[30px] leading-snug text-[color:var(--d-ink-2)]">
            A team&rsquo;s memory, built automatically from the work it already does.
          </p>
          <p className="mt-3 text-[20px] text-[color:var(--d-ink-3)]">
            Ask it anything about the team&rsquo;s work and get an answer with the commit or PR behind it.
          </p>
        </div>
      </div>
    ),
  },
  {
    id: "problem",
    criteria: ["Problem relevance"],
    notes:
      "Every team's knowledge is spread across Git, DevOps, email and chat, plus a few people's heads. So we lose days finding who knows something, managers rebuild status by hand, and knowledge walks out when someone moves on.",
    body: () => (
      <div className="deck-pad">
        <Kicker>The problem</Kicker>
        <h2 className="deck-h2 max-w-[640px]">What a team knows is in five tools and a few people&rsquo;s heads.</h2>
        <div className="mt-8 flex items-start gap-12">
          <div className="grid w-[560px] gap-4">
            <Card title="“Who knows this?”">Days of asking around, and the same questions answered again and again.</Card>
            <Card title="Status by hand">The team picture gets rebuilt every week from memory rather than evidence.</Card>
            <Card title="Knowledge walks out">When someone moves on, what they knew leaves with them. Nobody sees the risk coming.</Card>
          </div>
          <ScatteredTools />
        </div>
      </div>
    ),
  },
  {
    id: "solution",
    criteria: ["Problem-solution fit"],
    notes:
      "Hive reads that trail passively, with no data entry, indexes it, and links it into a knowledge graph. Out come cited answers, an expertise map, auto status, and routed questions.",
    body: () => (
      <div className="deck-pad">
        <Kicker>What Hive does</Kicker>
        <h2 className="deck-h2">It reads the work trail, so nobody has to.</h2>
        <div className="mt-6 flex justify-center">
          <FlowDiagram />
        </div>
        <div className="mt-2 grid grid-cols-3 gap-4">
          <Card title="Passive">No new tool and no data entry. Nobody changes how they work.</Card>
          <Card title="Cited, never invented">Every claim links to the commit, PR or answer behind it.</Card>
          <Card title="Read-only">Hive can&rsquo;t send, commit or update anything. It only observes and answers.</Card>
        </div>
      </div>
    ),
  },
  {
    id: "capabilities",
    criteria: ["Problem-solution fit", "Originality"],
    notes:
      "Here's everything it can do today. Eight capabilities, all running on the same engine and data. I'll show the most interesting ones live.",
    body: () => (
      <div className="deck-pad">
        <Kicker>Capabilities</Kicker>
        <h2 className="deck-h2">What Hive can do today.</h2>
        <div className="mt-10">
          <CapabilityGrid />
        </div>
        <p className="mt-8 text-[16px] text-[color:var(--d-ink-3)]">
          All eight work in the prototype on the same data, from the dashboard, Teams and Claude.
        </p>
      </div>
    ),
  },
  {
    id: "ai",
    criteria: ["Real AI use case"],
    notes:
      "Under the hood it's a LangGraph pipeline. An LLM extracts topics, then retrieval mixes vector and keyword search. The key step is grading: the AI judges whether the evidence actually answers the question, rewrites and retries if not, and refuses to guess.",
    body: () => (
      <div className="deck-pad">
        <Kicker>How the AI works</Kicker>
        <h2 className="deck-h2">Not a chatbot guessing. It retrieves, grades and cites.</h2>
        <div className="mt-10 flex justify-center">
          <PipelineDiagram />
        </div>
        <p className="mt-6 max-w-[1000px] text-[18px] leading-relaxed text-[color:var(--d-ink-2)]">
          Built as a <span className="text-[color:var(--d-accent)]">LangGraph</span> state machine on Azure OpenAI. Without an LLM configured, it still
          returns the ranked, cited evidence, and never invents prose about people&rsquo;s work.
        </p>
      </div>
    ),
  },
  {
    id: "ask",
    criteria: ["Real AI use case", "Clarity"],
    live: { href: "/ask?q=Who%20fixed%20the%20JWT%20refresh%20loop%20in%20billing%3F", label: "Ask it live" },
    notes:
      "A real question: 'Who fixed the JWT refresh loop in billing?' Hive names Deepa, gives the date, and links the exact commit and PR. Click 'Ask it live' to run it now.",
    body: () => (
      <div className="deck-pad flex gap-10">
        <div className="w-[380px] shrink-0">
          <Kicker>Live · Ask Hive</Kicker>
          <h2 className="deck-h2 text-[40px]">Ask in plain English. Get the proof.</h2>
          <div className="mt-8 space-y-5">
            <Callout n={1} title="A real question">&ldquo;Who fixed the JWT refresh loop in billing?&rdquo;</Callout>
            <Callout n={2} title="A sourced answer">Names the person and the date, in seconds.</Callout>
            <Callout n={3} title="Every claim cited">The commit and PR it came from, ranked by relevance.</Callout>
          </div>
        </div>
        <div className="pt-4">
          <Shot src="/presentation/ask.png" alt="Ask Hive answering with three cited sources" url="/ask" width={780} />
        </div>
      </div>
    ),
  },
  {
    id: "mcp",
    criteria: ["Originality", "Re-usability"],
    notes:
      "This is the part I'm most excited about. Hive is an MCP server, so Claude can call it while you code. Ask Claude about an error and it checks whether your team already fixed it, with the commit, the file and who to ask. This is a real tool result from the prototype.",
    body: () => (
      <div className="deck-pad">
        <Kicker>Claude + MCP · Hive in the editor</Kicker>
        <h2 className="deck-h2">Claude asks the team&rsquo;s memory before it guesses.</h2>
        <div className="mt-7 grid grid-cols-[1.35fr_1fr] gap-8">
          <McpConversation />
          <div>
            <p className="mb-3 text-[14px] font-semibold uppercase tracking-wider text-[color:var(--d-accent)]">Six MCP tools</p>
            <McpTools />
            <p className="mt-4 text-[13.5px] leading-relaxed text-[color:var(--d-ink-3)]">
              Runs locally over stdio. Register once with <code className="text-[color:var(--d-ink-2)]">claude mcp add hive</code> and it follows you into every project.
            </p>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "graph",
    criteria: ["Originality", "Scaling potential"],
    live: { href: "/graph", label: "Open the org map" },
    notes:
      "Everything is linked in a knowledge graph: people, teams, repos, topics, commits and questions, mirrored into Neo4j so it's queryable with Cypher. It answers multi-hop questions vector search can't, like 'which topics rest on one person?', and it powers the org map.",
    body: () => (
      <div className="deck-pad">
        <Kicker>Knowledge graph · Neo4j</Kicker>
        <h2 className="deck-h2">Everything linked in one graph.</h2>
        <div className="mt-4 grid grid-cols-[640px_1fr] gap-8">
          <GraphSchema />
          <div className="space-y-4 pt-4">
            <div className="deck-code">
              <p className="deck-code-label">Cypher · topics that rest on one person</p>
              <pre>{`MATCH (p:Hive {kind:'person'})
      -[r:REL {kind:'KNOWS'}]->
      (t:Hive {kind:'topic'})
WITH t, collect(p) AS knowers
WHERE size(knowers) = 1
RETURN t.label AS bus_factor_risk`}</pre>
            </div>
            <ul className="deck-list text-[15.5px] text-[color:var(--d-ink-2)]">
              <li>Neo4j via Bolt, or Aura over the HTTPS Query API</li>
              <li>Every edge derived from a table, rebuilt on sync</li>
              <li>Falls back to the in-memory graph if Neo4j is unreachable</li>
            </ul>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "map",
    criteria: ["Clarity"],
    live: { href: "/graph", label: "Open the org map" },
    notes:
      "Here's the graph in the dashboard: who actually works with whom, derived from the work rather than an org chart. The Expertise page ranks the right person for any topic.",
    body: () => (
      <div className="deck-pad">
        <Kicker>Live · Org map & expertise</Kicker>
        <h2 className="deck-h2">Who really knows what, from evidence, not skill tags.</h2>
        <div className="relative mt-8 h-[470px]">
          <div className="absolute left-0 top-0">
            <Shot src="/presentation/graph.png" alt="Organisation map of people and their collaboration" url="/graph" width={640} />
          </div>
          <div className="absolute right-0 top-[90px]">
            <Shot src="/presentation/expertise.png" alt="Expertise map ranking people by topic" url="/expertise" width={600} />
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "status",
    criteria: ["Clarity"],
    live: { href: "/status", label: "Open auto status" },
    notes:
      "Every person's weekly update, drafted from their commits and PRs, with evidence behind each line. Questions nobody could answer get routed to an expert, and this page shows where documentation is missing.",
    body: () => (
      <div className="deck-pad">
        <Kicker>Live · Auto status & knowledge gaps</Kicker>
        <h2 className="deck-h2">The weekly update writes itself, with receipts.</h2>
        <div className="relative mt-8 h-[470px]">
          <div className="absolute left-0 top-0">
            <Shot src="/presentation/status.png" alt="Auto-generated weekly status per person" url="/status" width={660} />
          </div>
          <div className="absolute right-0 top-[80px]">
            <Shot src="/presentation/gaps.png" alt="Gap analytics for unanswered questions" url="/knowledge/gaps" width={580} />
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "surfaces",
    criteria: ["Re-usability", "Scaling potential"],
    notes:
      "One engine, three places to use it: the dashboard, @Hive in Teams, and Claude in the editor. They share one API, one graph and one index, so a new surface costs almost nothing.",
    body: ({ data }) => (
      <div className="deck-pad">
        <Kicker>Where people use it</Kicker>
        <h2 className="deck-h2">One engine. Wherever the team already works.</h2>
        <div className="mt-10 flex justify-center">
          <Surfaces />
        </div>
        <div className="mt-8 grid grid-cols-4 gap-4">
          {[
            { v: data?.trail.artifacts, l: "work items indexed" },
            { v: data?.trail.people, l: "people mapped" },
            { v: data?.expertise.topics_mapped, l: "topics with an expert" },
            { v: data?.knowledge.answered, l: "answers kept for reuse" },
          ].map((row) => (
            <div key={row.l} className="deck-stat">
              <span className="tabular text-[32px] font-bold text-[color:var(--d-accent)]">{row.v ?? "—"}</span>
              <span className="text-[14.5px] leading-snug text-[color:var(--d-ink-2)]">{row.l}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-[color:var(--d-ink-3)]">Live from the running prototype · demo team is fictional</p>
      </div>
    ),
  },
  {
    id: "stack",
    criteria: ["Feasibility"],
    notes:
      "It's built on an open-source stack plus Azure OpenAI: FastAPI, LangGraph, ChromaDB, Neo4j. It's read-only, role-scoped and audited, and it reports work output only: no keystrokes, no hours, no sentiment.",
    body: () => (
      <div className="deck-pad">
        <Kicker>Under the hood</Kicker>
        <h2 className="deck-h2">Open-source stack, built to be trusted.</h2>
        <div className="mt-8 grid grid-cols-[1.5fr_1fr] gap-8">
          <Architecture />
          <div className="grid gap-3">
            {[
              ["Read-only", "Cannot send, commit or update anything."],
              ["Role-scoped", "Managers see their team. Nobody sees up."],
              ["Audited", "Every question is logged: who, what, when."],
              ["Not surveillance", "Work output only. No keystrokes, hours or sentiment."],
            ].map(([t, d]) => (
              <div key={t} className="deck-trust">
                <Hex size={20} />
                <div>
                  <p className="text-[17px] font-semibold text-[color:var(--d-ink)]">{t}</p>
                  <p className="text-[14px] text-[color:var(--d-ink-2)]">{d}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "next",
    criteria: ["Scaling potential"],
    notes:
      "Git is live today. Next are Azure DevOps, then email and meeting transcripts, all through the same pipeline, so each source makes every answer richer.",
    body: () => (
      <div className="deck-pad">
        <Kicker>What&rsquo;s next</Kicker>
        <h2 className="deck-h2">Every new source makes every answer richer.</h2>
        <Roadmap />
        <div className="mt-14 grid grid-cols-3 gap-4">
          <Card title="Scales by connector">Each new source flows through the same normalise → embed → graph pipeline.</Card>
          <Card title="Nothing team-specific">Point it at any team&rsquo;s Git and DevOps and it works.</Card>
          <Card title="Open by design">Neo4j, MCP and REST mean other tools can build on Hive&rsquo;s graph.</Card>
        </div>
      </div>
    ),
  },
  {
    id: "close",
    notes: "That's Hive: the team's memory, built from the work itself. Thank you. Happy to take questions.",
    body: () => (
      <div className="relative flex h-full flex-col justify-center overflow-hidden px-[96px]">
        <Honeycomb />
        <div className="relative">
          <div className="flex items-center gap-4">
            <Hex size={56} />
            <Kicker>Hive</Kicker>
          </div>
          <h2 className="mt-4 text-[76px] font-bold leading-[1.02] tracking-[-0.03em] text-[color:var(--d-ink)]">
            Knows everything.
            <br />
            <span className="text-[color:var(--d-accent)]">Changes nothing.</span>
          </h2>
          <p className="mt-8 max-w-[820px] text-[24px] leading-snug text-[color:var(--d-ink-2)]">
            Cited answers, an expertise map, a Neo4j knowledge graph and Claude in the editor, all from the work the team already does.
          </p>
          <p className="mt-12 text-[22px] text-[color:var(--d-ink)]">Thank you · Questions?</p>
        </div>
      </div>
    ),
  },
];

/* ----------------------------------------------------------------- the deck */

function useStageScale() {
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const fit = () => setScale(Math.min(window.innerWidth / STAGE_W, (window.innerHeight - 56) / STAGE_H));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  return scale;
}

function Deck({
  index,
  setIndex,
  onClose,
}: {
  index: number;
  setIndex: (next: number) => void;
  onClose: () => void;
}) {
  const router = useRouter();
  const scale = useStageScale();
  const [notes, setNotes] = useState(false);
  const [data, setData] = useState<LeadershipOverview | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const slide = SLIDES[index];

  useEffect(() => {
    let cancelled = false;
    api.overview().then(
      (result) => !cancelled && setData(result),
      () => undefined, // the deck still presents without live numbers
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const go = useCallback(
    (next: number) => setIndex(Math.max(0, Math.min(SLIDES.length - 1, next))),
    [setIndex],
  );

  const goLive = useCallback(() => {
    if (!slide.live) return;
    onClose();
    router.push(slide.live.href);
  }, [onClose, router, slide.live]);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else rootRef.current?.requestFullscreen().catch(() => undefined);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (["ArrowRight", "PageDown", " ", "Enter"].includes(event.key)) {
        event.preventDefault();
        go(index + 1);
      } else if (["ArrowLeft", "PageUp", "Backspace"].includes(event.key)) {
        event.preventDefault();
        go(index - 1);
      } else if (event.key === "Home") go(0);
      else if (event.key === "End") go(SLIDES.length - 1);
      else if (event.key === "Escape" && !document.fullscreenElement) onClose();
      else if (event.key.toLowerCase() === "n") setNotes((value) => !value);
      else if (event.key.toLowerCase() === "f") toggleFullscreen();
      else if (event.key.toLowerCase() === "l") goLive();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, goLive, index, onClose, toggleFullscreen]);

  return (
    <div ref={rootRef} className="hive-deck" role="dialog" aria-modal="true" aria-label="Hive presentation">
      <div className="deck-progress" style={{ width: `${((index + 1) / SLIDES.length) * 100}%` }} />

      <div className="flex flex-1 items-center justify-center overflow-hidden">
        <div style={{ width: STAGE_W * scale, height: STAGE_H * scale }}>
          <div
            key={slide.id}
            className="deck-stage"
            style={{ width: STAGE_W, height: STAGE_H, transform: `scale(${scale})` }}
          >
            {slide.criteria ? (
              <div className="deck-criteria">
                {slide.criteria.map((criterion) => (
                  <span key={criterion}>{criterion}</span>
                ))}
              </div>
            ) : null}
            {slide.body({ data })}
          </div>
        </div>
      </div>

      {notes ? (
        <div className="deck-notes">
          <p className="deck-notes-label">Speaker notes</p>
          <p>{slide.notes}</p>
        </div>
      ) : null}

      <div className="deck-bar-bottom">
        <button onClick={onClose} className="deck-btn" title="Close (Esc)">
          ✕ Close
        </button>
        <span className="deck-hint">← → navigate · N notes · F full screen{slide.live ? " · L live" : ""}</span>
        <div className="ml-auto flex items-center gap-2">
          {slide.live ? (
            <button onClick={goLive} className="deck-btn deck-btn-accent" title="Open this page live (L)">
              {slide.live.label} →
            </button>
          ) : null}
          <button onClick={() => setNotes((value) => !value)} className={`deck-btn ${notes ? "deck-btn-on" : ""}`}>
            Notes
          </button>
          <button onClick={toggleFullscreen} className="deck-btn" title="Full screen (F)">
            ⛶
          </button>
          <button onClick={() => go(index - 1)} disabled={index === 0} className="deck-btn" aria-label="Previous slide">
            ←
          </button>
          <span className="tabular w-14 text-center text-[13px] text-[color:var(--d-ink-3)]">
            {index + 1} / {SLIDES.length}
          </span>
          <button
            onClick={() => go(index + 1)}
            disabled={index === SLIDES.length - 1}
            className="deck-btn"
            aria-label="Next slide"
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}

/** Floating "Present" button, available on every page. Reopening the deck
 *  resumes on the slide you left, so a live demo detour costs no clicks. */
export function PresentationLauncher() {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const close = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    setOpen(false);
  }, []);

  // `?present=3` opens straight onto slide 3: handy as a bookmark before a slot.
  useEffect(() => {
    const requested = Number(new URLSearchParams(window.location.search).get("present"));
    if (!requested) return;
    const timer = setTimeout(() => {
      setIndex(Math.max(0, Math.min(SLIDES.length - 1, requested - 1)));
      setOpen(true);
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (open) return;
    // Shift+P opens the deck from anywhere except while typing.
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.shiftKey && event.key.toLowerCase() === "p") setOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {open ? (
        <Deck index={index} setIndex={setIndex} onClose={close} />
      ) : (
        <button onClick={() => setOpen(true)} className="hive-present-fab" title="Open the presentation (Shift+P)">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
            <rect x="3" y="4" width="18" height="12" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M10 8.2v3.6l3.2-1.8z" fill="currentColor" />
            <path d="M12 16v4M8 20h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span className="hive-present-label">{index > 0 ? `Resume · ${index + 1}/${SLIDES.length}` : "Present"}</span>
        </button>
      )}
    </>
  );
}
