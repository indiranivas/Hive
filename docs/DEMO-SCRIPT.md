# Hive — hackathon demo script

**Format:** 5 minutes presenting (deck + live prototype), then 2 minutes of judges' Q&A. Timings are
strictly enforced, so rehearse with a stopwatch and cut, never rush.

**The deck lives inside the app.** Click the round amber **Present** button (bottom-right on every
page) or press **Shift+P**. Inside the deck:

| Key | Does |
| --- | --- |
| ← → / Space | Previous / next slide |
| **L** or the amber button | Jump to that page *live* (slides 6, 8, 9, 10). Reopen the deck and it resumes on the same slide |
| **N** | Speaker notes (the script lines below) |
| **F** | Full screen |
| Esc | Close |

Bookmark `http://localhost:3000/overview?present=1` to open straight onto slide 1.
Backup: [`Hive-Pitch-Deck.html`](../Hive-Pitch-Deck.html) is the same story as a standalone file
(no server needed).

---

## Pre-flight (do this 30 minutes before your slot)

Run from the repo root in VS Code's terminal (PowerShell):

```powershell
# 1. Fresh demo data, dated relative to today (otherwise "this week" pages are empty)
cd backend; $env:PYTHONPATH = $PWD
python -m hive.cli seed --reset

# 2. API (terminal 1)
python -m uvicorn api.main:app --port 8000

# 3. Dashboard (terminal 2)
cd ..\dashboard; npm run dev
```

Then:

- [ ] Seed **before** starting the API, and let it finish. It calls the LLM for every work item and
      locks the database for about 7 minutes; while it runs, Ask Hive fails. If the API was already
      running during a reseed, restart it afterwards.
- [ ] Open each page once (Ask, Org map, Status, Gap analytics) so Next.js has compiled them.
      The first load of a page in dev mode takes several seconds.
- [ ] Ask the demo question once on **Ask Hive** to confirm the LLM is reachable (~5–10 s).
- [ ] Open **Status** once so this week's reports are generated and cached.
- [ ] *Optional MCP demo:* in VS Code, open Claude Code and confirm `hive` shows as connected in `/mcp`.
- [ ] Browser zoom 110–125%, other tabs closed, notifications off. Be in the room 10 minutes early.

---

## The 5 minutes

| Time | Slide | Say (keep it to this) | Criterion |
| --- | --- | --- | --- |
| **0:00–0:15** | 1 · Title | "This is Hive: a team's memory, built automatically from the work it already does." | — |
| **0:15–0:45** | 2 · Problem | "Every team's knowledge is spread across Git, DevOps, email and chat, plus a few people's heads. We lose days finding who knows something, status gets rebuilt by hand, and knowledge walks out when someone moves on." | Problem relevance |
| **0:45–1:05** | 3 · What Hive does | "Hive reads that trail passively, with no data entry, and links it into a knowledge graph. Out come cited answers, an expertise map, auto status and routed questions." | Fit |
| **1:05–1:25** | 4 · Capabilities | "Eight things it does today, all on one engine. I'll show the most interesting ones live." | Fit · Originality |
| **1:25–1:45** | 5 · How the AI works | "A LangGraph pipeline: it retrieves evidence, then the AI *grades* whether the evidence answers the question, rewrites and retries if not, and refuses to guess." | Real AI use case |
| **1:45–2:30** | 6 · Ask Hive → press **L** | The question runs live. *While it thinks:* "Searching commits, PRs and past answers, grading the evidence." When it lands: "Deepa, the date, and the exact commit and PR. Nothing invented." Reopen the deck. | Real AI use case |
| **2:30–3:15** | 7 · Claude + MCP | "The part I'm most excited about: Hive is an MCP server, so Claude calls it while you code. Ask about an error and Claude checks whether your team already fixed it, with the commit, the file and who to ask. That's a real result from the prototype." *Optional, if time allows:* ask the same in Claude Code live. | Originality · Re-use |
| **3:15–3:45** | 8 · Neo4j graph | "Everything is linked in a knowledge graph mirrored into Neo4j: people, repos, topics, commits, questions. It answers multi-hop questions vector search can't, like this Cypher for topics that rest on one person." | Originality · Scale |
| **3:45–4:05** | 9 · Org map (or 10 · Status) | "Here's the graph live: who actually works with whom, from the work rather than an org chart." | Clarity |
| **4:05–4:25** | 11 · Surfaces | "One engine, three places: dashboard, @Hive in Teams, and Claude in the editor. The numbers are live from the prototype." | Re-use · Scale |
| **4:25–4:45** | 12 · Stack | "Open-source stack plus Azure OpenAI. Read-only, role-scoped, audited, and work output only: no surveillance." | Feasibility |
| **4:45–5:00** | 13 → 14 | "Next is Azure DevOps, then email and meetings, through the same pipeline. Hive: knows everything, changes nothing. Thank you." | Scale |

**If you're running long:** skip slides 9–10 (the live org map and status). Never cut slides 6–8 (Ask, MCP, Neo4j).
Those are the strongest capability proofs.

### Backup questions for Ask Hive

- "Why did we add idempotency keys to invoice creation?" (explains the *why*, cites 4 sources)
- "Why were sessions disappearing on deploy and how was it fixed?" (cause + fix + who)

### Optional live MCP prompts (Claude Code in VS Code)

- "Getting a token refresh loop on 401s in billing auth. Has the team seen this?" → `hive_prior_art`
- "I'm about to change identity-service. What else moves with it and who should I tell?" → `hive_blast_radius`

---

## Q&A prep (2 minutes, so keep answers to one or two sentences)

**"Isn't this just ChatGPT / Copilot over our docs?"**
No. Copilot answers from documents someone wrote; Hive answers from the work itself: commits, PRs,
tickets. Every answer cites its source, and it knows *who* did the work.

**"What does MCP add?"**
Claude can call Hive's six tools mid-task, so before it debugs from scratch it checks whether the team
already solved the problem. It runs locally over stdio, and one `claude mcp add` makes it available in every project.

**"Why Neo4j and not just vector search?"**
Vectors find similar text; the graph follows relationships. "Which topics rest on one person?" or "who
works across these two repos?" are multi-hop questions. Every edge is derived from tables, and if Neo4j
is unreachable it falls back to an in-memory graph.

**"What if the AI makes things up?"**
It retrieves evidence first and grades it. If the evidence is weak it says so and offers to raise a
Knowledge Request to the likely expert. With no LLM configured, it still returns the cited evidence list.

**"Is this monitoring people?"**
Work output only: commits, PRs, tickets. No keystrokes, hours or sentiment. It's read-only and
role-scoped, and every query is audit-logged.

**"What's real and what's mocked?"**
Everything shown runs: ingestion, retrieval, grading, the graph, the dashboard, the Teams bot and the
MCP server. The demo *team* is fictional seed data; `hive.cli ingest-git --repo <path>` ingests a real repo.

**"What's next?"**
The Azure DevOps connector, then email and meeting transcripts, all through the same pipeline.

---

## If something breaks on stage

| Symptom | Do this |
| --- | --- |
| Ask Hive is slow or errors | Close the live page, stay on slide 6 (it shows a real answer), and move on |
| A page says "Cannot reach the Hive API" | The API stopped. Restart it (pre-flight step 2) and click **Retry** |
| Status page is empty | The seed is stale. Rerun `python -m hive.cli seed --reset` (about 7 minutes, then restart the API). Don't attempt this mid-slot |
| Dashboard won't load at all | Open [`Hive-Pitch-Deck.html`](../Hive-Pitch-Deck.html) directly in the browser and present from that |
