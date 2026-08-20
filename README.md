# Hive

A passive knowledge layer over a team's work trail. See [HIVE-BLUEPRINT.md](HIVE-BLUEPRINT.md)
for the full architecture and the seven-phase plan.

**Status: Phases 1, 2, 4 and 6 complete, plus most of 3.** Git ingestion, the
normalize/chunk/embed pipeline, graded retrieval, expertise scoring, auto-status, the full
Knowledge Request loop (raise → route to an expert → answer → index), the REST API, the CLI, the
@Hive Teams bot and the manager dashboard all work end to end. Still open: the Azure DevOps and
email/call connectors (Phases 3 and 5), and production hardening (Phase 7).

---

## Quick start (no credentials, no Docker)

```bash
cd backend
pip install -r requirements-dev.txt
export PYTHONPATH=$PWD          # PowerShell: $env:PYTHONPATH = $PWD

python -m hive.cli seed                      # demo team + work trail
python -m hive.cli ask "who worked on billing auth?"
python -m hive.cli experts billing-service
python -m hive.cli status
```

Then point it at a real repository:

```bash
python -m hive.cli ingest-git --repo /path/to/your/clone --days 30
python -m hive.cli ask "who has touched the auth module recently?"
```

Everything defaults to offline providers — SQLite, lexical embeddings, and a stub LLM that
returns a **cited evidence list with no synthesis**. That is a deliberate floor, not a
placeholder: Hive never invents prose about people's work just because no model is configured.

Run the API instead of the CLI:

```bash
uvicorn api.main:app --reload      # http://localhost:8000/docs
```

## The dashboard

```bash
cd dashboard
npm install
npm run dev                        # http://localhost:3000
```

It needs the API running (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`). Seven pages:

| Page | What it shows |
| --- | --- |
| `/` Team pulse | Activity tiles, 8-week stacked activity chart, contributors, latest work, alerts, data coverage |
| `/status` Auto status | Weekly per-person summaries with expand-to-evidence, week stepper, regenerate |
| `/expertise` Expertise map | Expert search, topic coverage bars, a topic↔people diagram, bus-factor flags |
| `/knowledge` Knowledge repo | Browse, search and **answer** open requests; answers are indexed on save |
| `/knowledge/gaps` Gap analytics | Open vs answered, resolution time, most-requested topics, bus factor, weekly trend |
| `/ask` Ask Hive | The same engine as the Teams bot, with sources and a raise-a-request button |
| `/settings` Settings | Providers, connector health, a manual ingestion trigger, the guardrails |

Design notes worth knowing:

- **Charts are hand-rolled inline SVG** — no chart library. Colours come from a validated
  categorical palette (checked for colourblind separation and contrast in both themes), series
  slots are fixed so a filter never repaints the survivors, and every bar carries a direct value
  label.
- **Light and dark are separately chosen palettes**, not an inversion, applied from
  `data-theme` before first paint so there is no flash of the wrong theme.
- **Missing data is stated, not faked.** "On track" reads `—` with *"Needs the Azure DevOps
  connector"* rather than showing a plausible percentage, and every page has a real empty state.

## The Teams bot (@Hive)

You can exercise the bot's whole decision path with no Teams tenant, no Azure Bot registration
and no SDK installed:

```bash
python -m hive.cli bot "who fixed the jwt refresh loop?"
python -m hive.cli bot "who knows billing-service"
python -m hive.cli bot "kr how do we rotate the ADO PAT?"
python -m hive.cli bot help --json          # the raw Adaptive Card
```

That runs the same `bot/handlers.py` dispatch Teams calls -- only the transport differs.

### Putting it in Teams

Full walkthrough with the Azure Portal fields and a troubleshooting table:
**[docs/TEAMS-SETUP.md](docs/TEAMS-SETUP.md)**. The short version:

1. **Register the bot.** Azure Portal > Azure Bot > create. Note the Microsoft App ID and
   generate a client secret. Set `BOT_APP_ID` and `BOT_APP_PASSWORD` in `.env`.
2. **Run the bot locally and expose it.** botbuilder is a separate install (verified on
   Python 3.14 with botbuilder-core 4.17.1):
   ```bash
   pip install -r backend/requirements-bot.txt
   cd backend && python -m bot.app        # listens on :3978
   ngrok http 3978
   ```
3. **Point the channel at the tunnel.** In the Azure Bot's Configuration, set the messaging
   endpoint to `https://<tunnel>/api/messages`, then enable the Microsoft Teams channel.
4. **Build and sideload the app package.**
   ```bash
   python scripts/build_teams_package.py         # -> dist/hive-teams-app.zip
   ```
   Teams > Apps > Manage your apps > Upload an app > Upload a custom app.
5. **Ask it something:** `@Hive who wrote the most commits this week?`

What the bot understands: any question (the default), `who knows <topic>`, `kr <question>`, and
`help`. Answers arrive as Adaptive Cards carrying their sources; when Hive has no evidence, the
card offers a **Raise a Knowledge Request** button that records the gap.

## Running the tests

```bash
cd backend && python -m pytest
```

156 tests cover chunking, embeddings, the vector store, git parsing, ingestion idempotency,
expertise decay, retrieval scoping, the API's permission gates, the bot's parsing, dispatch, cards
and identity mapping, the Azure OpenAI request format (asserted against a mock transport, so the
deployment path, api-version, auth header and token-parameter switch are covered without a live
resource), and the dashboard endpoints — pulse honesty, status generation and reuse, the KR
lifecycle and gap analytics, and both LangGraph flows — grading thresholds, the rewrite-recovery
path, the retry cap, routing rank order, load balancing, self-routing refusal and outbox dedupe.

The dashboard itself is verified by build + lint (`npx next build`, `npx eslint src`) and was
driven in a real browser end to end: ask a question, get sources; ask an unknown one, raise the
request; answer it in the repo; re-ask and get the repo's answer.

Six of those cover `bot/app.py`, the Bot Framework transport, using a recording adapter in place
of the channel — a card comes back for a question, the conversation reference is stored, a card
action round-trips, and a dispatch failure apologises in-channel instead of returning a 500. They
need the SDK, so `python -m pytest` reports **150 passed, 1 skipped** without it and **156 passed**
once `requirements-bot.txt` is installed.

## Orchestration: two LangGraph state machines

LangGraph runs the two flows that genuinely branch or loop. It is used as a **control-flow runtime
only** — every node calls Hive's own retrieval, expertise and LLM providers, so the offline stub
behaves identically to Azure OpenAI inside a graph and no LangChain model abstraction is
introduced. If `langgraph` is not installed, both graphs fall back to an equivalent plain loop.

**Graded retrieval** ([retrieval_graph.py](backend/api/services/retrieval_graph.py)) — the answer
path. A weak first pass gets one rewritten retry instead of an immediate "I don't know":

```text
retrieve ─► grade ─► sufficient ──────────────► answer + cite
                └─► weak ─► rewrite ─► retrieve
                └─► weak & retries spent ─────► admit the gap, offer a request
```

Grading is score-based with the stub (deterministic, so tests are reproducible) and
LLM-based when a real provider is configured. The retry is visible in the UI — *"First pass looked
weak, so Hive re-searched for `graph token caching`"* — because a silent query rewrite is
the kind of magic that erodes trust in a sourced answer.

**Knowledge Request routing** ([kr_routing_graph.py](backend/api/services/kr_routing_graph.py)) —
blueprint section 8, with a real fork:

```text
tag ─► find experts ─► rank ─► route ─────► notify the expert
                           └─► nobody ───► notify the team
```

Ranking is the blueprint's formula (`expertise×0.5 + recency×0.3 − open_requests×0.2`), so a
busy expert loses to an equally-qualified idle one, and a question never routes back to whoever
asked it. Notifications go to a **`notifications` outbox** table drained by a Celery task, so a
routing decision cannot be lost just because Teams delivery is unavailable — and re-routing to the
same person does not ping them twice.

Set `RETRIEVAL_MODE=linear` to bypass the retrieval graph entirely.

## Going to production

Swap providers with environment variables — no code changes:

| Concern | Dev default | Production |
| --- | --- | --- |
| Database | SQLite (`backend/.data/hive.db`) | `DATABASE_URL=postgresql+psycopg://…` |
| Embeddings | `hashing` (lexical, offline) | `EMBEDDING_PROVIDER=azure_openai` + `EMBEDDING_DIM=1536` |
| Vector store | `sql` (embeddings in Postgres, scanned in Python) | `VECTOR_PROVIDER=chroma` → Qdrant in Phase 7 |
| LLM | `stub` (extractive, no key) | `LLM_PROVIDER=azure_openai` + endpoint/deployment |
| Auth | `dev` (single local admin) | `AUTH_MODE=azure_ad` + tenant/client IDs |
| Teams bot | `hive.cli bot` (no SDK) | `requirements-bot.txt` + `BOT_APP_ID`/`BOT_APP_PASSWORD` |

```bash
cp .env.example .env      # set DB_PASSWORD, LLM_API_KEY, git sources
docker compose up --build
docker compose exec api alembic upgrade head
```

### Azure OpenAI

Production runs the LLM **and** the embeddings on Azure OpenAI, so no team content leaves the
tenant:

```bash
LLM_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai
EMBEDDING_DIM=1536                                  # text-embedding-3-small
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=hive-gpt4o                  # deployment name, not model name
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=hive-embed-3-small
AZURE_OPENAI_API_VERSION=2024-10-21                 # pin what your resource supports
AZURE_OPENAI_AUTH=key                               # or `entra`
AZURE_OPENAI_API_KEY=...
```

Four Azure-specific things the client handles, each of which otherwise shows up as a 400 or 404:

- **Deployments, not models.** The deployment name goes in the URL path and no `model` field is
  sent. A model name here yields a 404 `DeploymentNotFound`.
- **`api-version` is mandatory** and resource-specific, so it is configurable rather than
  hardcoded.
- **Reasoning deployments** (o-series, gpt-5) reject `max_tokens` and any `temperature`.
  `AZURE_OPENAI_TOKEN_PARAM=auto` detects them by deployment-name prefix and sends
  `max_completion_tokens` instead; force it either way if your naming does not match.
- **Content filters return HTTP 200** with an empty completion, not an error. That is treated as
  "no answer" so it surfaces as a Knowledge Request rather than a blank card.

Prefer `AZURE_OPENAI_AUTH=entra` where you can (`pip install azure-identity`): it uses the managed
identity or `az login` session, so there is no key in `.env`, and many tenants disable local key
auth on Cognitive Services anyway. Tokens are cached until just before expiry.

Changing `EMBEDDING_PROVIDER` or `EMBEDDING_DIM` invalidates existing vectors — old and new
embeddings are not comparable. Re-ingest, or delete `vector_chunks` and let the connectors
refill it.

## Layout

```text
backend/
  api/core/        config, db session, embeddings, vector store, LLM, auth, prompts
  api/models/      SQLAlchemy tables, portable column types, pydantic schemas
  api/routes/      /api/query, /api/expertise, /api/admin
  api/services/    query engine, retrieval graph, KR routing graph, expertise, topics
  bot/             commands, cards, handlers (all SDK-free) + app.py transport, proactive
  ingestion/       git connector (local | azure_repos | github), normalizer, embedder, runner
  workers/         Celery app + scheduled git ingestion
  db/              Alembic migrations, dev seed data
  hive/cli.py      init-db | seed | ingest-git | ask | experts | bot | status
  tests/
dashboard/         Next.js app: 7 pages, hand-rolled SVG charts, typed API client
appPackage/        Teams manifest + icons
scripts/           build_teams_package.py -> sideloadable zip
```

## Design decisions worth knowing

These are the places the implementation departs from the blueprint's pseudo-code, and why.

- **Synchronous services.** FastAPI runs `def` endpoints in a threadpool and Celery workers are
  sync, so sync SQLAlchemy never blocks an event loop. This avoids the async/greenlet complexity
  the blueprint's `async def` sketches would otherwise pull in.
- **Provider abstractions with offline defaults.** Embeddings, vector store, LLM and auth each
  sit behind a small interface whose default implementation needs no network, no API key and no
  heavy dependency. A fresh clone is queryable in one command, and tests are deterministic.
- **Hybrid retrieval.** Vector search alone misses exact identifiers (`PR #312`, a service name,
  a SHA), so a keyword pass runs alongside it and the scores are merged 75/25.
- **Idempotent ingestion.** `(source, source_id)` is unique; re-ingesting a commit updates the
  row and replaces its chunks. Each artifact persists inside its own savepoint, so one bad
  payload cannot discard a batch.
- **The bot's logic holds no SDK imports.** `botbuilder` is confined to `bot/app.py`; parsing,
  dispatch and card building are plain sync Python. That keeps the bot fully testable without the
  SDK installed and makes the same dispatch reusable from the CLI (`hive.cli bot ...`) and, later,
  the dashboard.
- **Cards force blank lines between answer lines.** Teams collapses single newlines in a
  TextBlock, so multi-line answers and bullet lists silently run together into one paragraph.
- **Teams identity links to existing people.** A first @Hive message matches an existing person by
  email and backfills `azure_ad_id` rather than creating a second row, because commit emails
  almost always got there first.
- **Expertise needs evidence, not resemblance.** Semantic similarity re-ranks people who already
  have a matching topic score but never introduces one, because a vaguely similar commit is not
  evidence that someone knows a topic. Topic search matches the whole phrase and its parts, so
  `azure-devops-api` still finds someone scored on `azure` and `devops` — weighted so a partial
  match cannot outrank an exact one. Changed file paths feed topic extraction too: commit
  messages rarely name the module, but the files always do.
- **Per-connector watermarks.** `ingestion_state` tracks a cursor, last status and last error per
  connector, so scheduled pulls stay incremental and connector health is observable.
- **`people.azure_ad_id` is nullable.** Commit emails identify authors long before those people
  ever sign in through Entra ID; the ID is backfilled on first login.
- **A local git provider.** Not in the blueprint. It reads a clone with the git CLI, which is
  what makes Phase 1 testable before anyone issues a PAT.

## Guardrails, as built

Read-only by construction — no connector holds a write scope and no code path posts, commits or
emails. Every query is written to `query_log` with user, sources, surface and latency. Scope is
enforced server-side: a member passing another team's `team_id` is silently scoped back to their
own team rather than being told what exists elsewhere.
