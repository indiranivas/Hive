# Hive in your editor (MCP)

Claude reads Hive's knowledge graph directly while you code, over MCP. No tab
switching, no copy-pasting, no asking around — when you hit a problem, Claude
checks whether the team has already solved it.

The server is `backend/mcp_server/`. It speaks MCP over stdio, runs entirely on
your machine, and talks to the same SQLite/Postgres database the API and the
Teams bot use.

---

## 1. Install

```bash
pip install -r backend/requirements-mcp.txt
```

That is `requirements.txt` plus the MCP SDK. The API, workers, bot and CLI do
not need it: `mcp_server/tools.py` holds no SDK import, so the whole tool
surface runs — and is tested — without it.

## 2. Register it on your account — once

Register at **user scope** and Hive follows you into every project, including
folders that have nothing to do with this repo. That is the point: the team's
memory should be there while you write code, not only while you have Hive open.

```bash
claude mcp add hive --scope user -e PYTHONIOENCODING=utf-8 \
  -- "C:/path/to/python.exe" "C:/path/to/Hive/scripts/hive_mcp.py"
```

Use **absolute paths** for both. User scope means the server is launched from
whatever folder you happen to be in, so a bare `python` may resolve to a
different interpreter than the one holding Hive's dependencies, and a relative
script path will not resolve at all. The launcher itself is cwd-independent — it
finds the backend, the database and `.env` from its own location — so once the
two absolute paths are right, everything else follows.

Confirm it took:

```bash
claude mcp get hive
#   Scope: User config (available in all your projects)
#   Status: ✔ Connected
```

To remove or re-point it later: `claude mcp remove hive -s user`, then add again.

### The committed project config

`.mcp.json` and `.vscode/mcp.json` are committed too, and use a bare `python`
with a relative path so they work for any teammate who clones the repo. They
apply only when this repo is the open workspace.

If you have registered at user scope, that one wins — same server name, same
launcher, so there is nothing to reconcile. The project files exist so somebody
who has just cloned Hive gets the tools without registering anything first.

## 3. Verify

Run the launcher by hand from **any** directory — that is the property that
matters:

```bash
cd ~            # deliberately not the Hive repo
python "C:/path/to/Hive/scripts/hive_mcp.py"
```

It should print one line to **stderr** and then sit waiting for JSON-RPC on
stdin:

```text
Hive MCP: 6 tools | identity you@levelshift.com (Platform) | llm=… vectors=… graph=…
```

Ctrl-C to exit. In Claude Code, `/mcp` lists the server and its tools.

## 4. Give it something to know

The graph is only as good as what has been ingested. A fresh install knows the
demo seed — fictional people and repos — so a real question returns an honest
"no evidence" until you point it at real work:

```bash
cd backend
python -m hive.cli ingest-git --repo /path/to/your/clone --days 90
```

Re-run as work lands, or run the Celery beat schedule and let it pull every
`INGEST_INTERVAL_MINUTES`. Ingest every repo you want Hive to reason across —
`hive_blast_radius` can only report coupling between repos it has both sides of.

---

## What Claude can ask

| Tool | The moment it fires |
| --- | --- |
| `hive_prior_art` | You paste an error or describe a symptom |
| `hive_blast_radius` | You are about to change a shared service |
| `hive_area_briefing` | You open code you have never worked in |
| `hive_who_knows` | You need a person, not an answer |
| `hive_ask` | Anything else about the team's work trail |
| `hive_raise_request` | Nothing was found, so the gap gets recorded |

### Paste an error while coding

> **You:** `TypeError: refresh token re-issued on every 401`
>
> **Claude** (via `hive_prior_art`): Deepa V hit this on 2026-08-22 — fixed in
> `services/billing/auth_middleware.py`, commit `billing-service@a1b2c3d4`: the
> refresh token was re-issued on every 401 and stampeded the identity provider;
> she cached it for its full TTL and retried once. PR #312 carries the same fix.

When two people solved the same thing differently, the tool says so rather than
letting the most recent one look like the agreed pattern.

### Before changing a service

> **Claude** (via `hive_blast_radius` on `identity-service`): billing-service is
> the strongest coupling — changed together in 3 weeks, shared contributors
> Deepa V and Karthik M. Worth telling them before you merge. hive-api and
> web-dashboard are weaker.

### Picking up a ticket in unfamiliar code

> **Claude** (via `hive_area_briefing` on `data-pipeline`): Sanjay P (4 changes,
> last 2 days ago), Lakshmi N (4), Arun K (1). One problem already answered
> here: *"Why did invoice retries create duplicate rows in the warehouse?"* —
> answered by Deepa V.

---

## How to read what it gives you

**Coupling is inferred, not parsed.** Hive reads no `package.json`, no
`requirements.txt`, no import graph. `hive_blast_radius` derives coupling from
three signals in the work trail — who changes both repos, who changes both
*within one week*, and which commits name the other repo by name. Every result
carries the evidence behind it. Treat it as a prompt to go and check, never as
proof that a dependency exists.

**Prior art is retrieved, not verified.** A commit that matches your error is
evidence somebody dealt with something similar. Read the referenced change
before applying its approach.

**A gap is a real answer.** When Hive says it has no evidence, nobody on the
team has committed, reviewed or written down anything matching. That is a
finding — `hive_raise_request` records it and routes it to the best-placed
expert, so the next person gets an answer instead of the same silence.

## Scope, identity and audit

The server runs as you, on your machine. Identity comes from `DEV_USER_EMAIL`
in `.env` — the same resolution the CLI uses — and that is who appears in the
audit log.

These tools reach **org-wide** where your role allows it, unlike the dashboard,
which defaults a member to their own team. That is deliberate: "has anyone here
solved this" and "what breaks if I change this" are close to worthless answered
inside one team's boundary, because the service that depends on yours is usually
owned by somebody else. The gate is the existing `can_query_org` permission in
`api/core/security.py`, not a rule invented for MCP.

Every `hive_ask` lands in `query_log` with `surface='mcp'`, alongside the Teams
and dashboard traffic. `hive_raise_request` is the only tool that writes
anything at all; the rest are strictly read-only.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Claude never calls Hive on its own | The server's `instructions` tell it when to. Check `/mcp` shows `hive` connected; otherwise say "check Hive" once and it will keep going. |
| Server exits with an SDK message | `pip install -r backend/requirements-mcp.txt`. |
| A tool call hangs forever | Almost always something writing to **stdout**. stdout is the JSON-RPC channel — any stray `print` corrupts the stream and the client waits forever. Hive logs to stderr; keep it that way in anything you add. |
| First call hangs, later ones fine | Heavy providers must be imported on the main thread at boot, not inside a tool. `tools.warm_providers()` does this — importing a C extension (numpy, via chromadb) from an MCP worker thread deadlocks on the import lock. Do not make provider loading lazy. |
| `database is locked` | Embedded Chroma (`VECTOR_PROVIDER=chroma` with no `CHROMA_URL`) is single-process. Running the MCP server alongside the API or a Celery worker means two processes on one on-disk store. Point them all at a Chroma server (`CHROMA_URL=http://localhost:8000`), or use `VECTOR_PROVIDER=sql`. |
| Answers are only from your own team | Your role lacks `can_query_org`. See `ROLES` in `api/core/security.py`. |
| Empty answers everywhere | Nothing ingested yet — see step 4. `python -m hive.cli seed` loads the demo trail; `ingest-git` loads a real one. |
| Works in the Hive repo, not elsewhere | You are on the committed project config, not user scope. Run the `claude mcp add --scope user` in step 2. |
| `No module named mcp_server` | The registered command uses a relative script path. User scope launches from an arbitrary cwd — make both paths absolute. |
