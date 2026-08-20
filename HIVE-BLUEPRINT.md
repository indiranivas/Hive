# Hive — Complete Technical Blueprint v1.0

> **The full architecture, stack, schemas, integration guides, UI spec, and phased build plan to create Hive from scratch.**
> Designed for long-term development. Keep this in the repo root.

---

## Table of Contents

1. [Product Vision & Scope](#1-product-vision--scope)
2. [System Architecture](#2-system-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Project Structure](#4-project-structure)
5. [Data Models & Schemas](#5-data-models--schemas)
6. [Ingestion Pipeline (4 Streams)](#6-ingestion-pipeline-4-streams)
7. [Knowledge Engine](#7-knowledge-engine)
8. [Knowledge Request Framework](#8-knowledge-request-framework)
9. [Teams Bot (@Hive)](#9-teams-bot-hive)
10. [Manager Dashboard (Web App)](#10-manager-dashboard-web-app)
11. [Auth & Permissions](#11-auth--permissions)
12. [Privacy & Guardrails](#12-privacy--guardrails)
13. [Deployment & Infrastructure](#13-deployment--infrastructure)
14. [AI Prompts Library](#14-ai-prompts-library)
15. [API Reference](#15-api-reference)
16. [Phased Build Plan](#16-phased-build-plan)

---

## 1. Product Vision & Scope

### What Hive Is

A passive AI agent that absorbs a team's entire work trail — emails, calls, tasks, Git commits — and builds a live, queryable knowledge layer. Two surfaces:

- **@Hive in Teams** — chatbot for everyone (Q&A, knowledge requests, dependency routing)
- **Hive Dashboard** — web app for managers (statuses, pulse, expertise map, gap analytics)

### Core Capabilities

| Capability | Description | Surface |
|---|---|---|
| Natural language Q&A | Ask anything about the team's work, get a sourced answer | Teams bot |
| Proactive dependency routing | Assigned a task? Hive tells you who's touched related code/modules | Teams bot |
| Auto status reports | Weekly per-person status from commits, tickets, PRs, emails | Dashboard |
| Expertise map | "Who at the company knows X?" with evidence | Both |
| Knowledge Request framework | Gap → route to expert → capture answer → permanent repo | Teams bot |
| Team pulse & analytics | Activity bars, blocker flags, knowledge gap analytics | Dashboard |

### What Hive Does NOT Do

- **Write** — no sending emails, updating tickets, pushing code, or posting messages on behalf of users
- **Monitor individuals** — no keystroke tracking, no sentiment scoring, no "productivity" ranking
- **Make decisions** — surfaces information, never acts on it

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌───────────────┐   │
│  │ Microsoft│ │ Microsoft│ │ Azure DevOps │ │ Azure Repos / │   │
│  │ 365 Mail │ │ Teams    │ │ Work Items   │ │ GitHub        │   │
│  └────┬─────┘ └────┬─────┘ └──────┬───────┘ └──────┬────────┘   │
└───────┼─────────────┼──────────────┼────────────────┼────────────┘
        │             │              │                │
        ▼             ▼              ▼                ▼
┌──────────────────────────────────────────────────────────────────┐
│                    INGESTION LAYER                                │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────────────┐  │
│  │ Email     │ │ Call/Meet │ │ Task      │ │ Git             │  │
│  │ Connector │ │ Connector │ │ Connector │ │ Connector       │  │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └───────┬─────────┘  │
│        └──────────────┴─────────────┴───────────────┘            │
│                             │                                    │
│                    ┌────────▼────────┐                            │
│                    │  Normalizer &   │                            │
│                    │  Chunker        │                            │
│                    └────────┬────────┘                            │
└─────────────────────────────┼────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE ENGINE                               │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────────┐  │
│  │ Vector DB  │  │ Relational │  │ LLM Layer                  │  │
│  │ (ChromaDB/ │  │ DB         │  │ (Mistral / Claude /        │  │
│  │  Qdrant)   │  │ (Postgres) │  │  GPT — configurable)       │  │
│  └────────────┘  └────────────┘  └────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ Knowledge Request Manager                                  │   │
│  │ (gap detection → routing → capture → indexing)             │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                                 ▼
┌──────────────────────┐          ┌──────────────────────────┐
│   TEAMS BOT          │          │   MANAGER DASHBOARD      │
│   (@Hive)            │          │   (Web App)              │
│                      │          │                          │
│ • Q&A                │          │ • Team pulse             │
│ • Knowledge Requests │          │ • Auto-status            │
│ • Dependency routing │          │ • Expertise map          │
│ • Expert connections │          │ • Gap analytics          │
│                      │          │ • Knowledge repo browser │
└──────────────────────┘          └──────────────────────────┘
```

### Component Responsibility Matrix

| Component | Responsibility | Tech |
|---|---|---|
| Ingestion Connectors | Pull data from 4 sources on schedule + webhooks | Python workers |
| Normalizer | Convert raw data → unified `WorkArtifact` schema, chunk for embedding | Python |
| Vector DB | Store embeddings for semantic search | ChromaDB → Qdrant (prod) |
| Relational DB | Structured data: people, teams, artifacts, KRs | PostgreSQL |
| LLM Layer | Answer queries, generate statuses, detect expertise, route KRs | Mistral / Claude API |
| Knowledge Request Manager | Gap detection, expert routing, answer capture, repo indexing | Python service |
| Teams Bot | User-facing chatbot in Microsoft Teams | Bot Framework SDK |
| Dashboard | Manager web UI | Next.js / React |
| API Gateway | REST API serving both surfaces | FastAPI |

---

## 3. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend API | `FastAPI` (Python 3.11+) | Async, fast, typed, great for ML pipelines |
| Task Queue | `Celery` + `Redis` | Scheduled ingestion, background embedding |
| Relational DB | `PostgreSQL 16` | Structured data, JSON support, proven at scale |
| Vector DB | `ChromaDB` (dev) → `Qdrant` (prod) | Quick start → production performance |
| LLM | `Mistral` (API or self-hosted) / `Claude API` | Configurable — swap models without code changes |
| Embeddings | `sentence-transformers` / `Mistral Embed` | Local or API-based |
| Teams Bot | `botbuilder-python` (Bot Framework SDK) | Official Microsoft SDK |
| Dashboard | `Next.js 14` + `Tailwind` + `shadcn/ui` | SSR, excellent DX |
| Auth | `Azure AD` (Entra ID) / `MSAL` | SSO — everyone already has accounts |
| Deployment | `Docker` + `Azure Container Apps` or `Render` | Containerized, scalable |
| Monitoring | `Prometheus` + `Grafana` or `Azure Monitor` | Ingestion health, query latency, LLM costs |

---

## 4. Project Structure

```
hive/
├── backend/
│   ├── api/                    # FastAPI app
│   │   ├── main.py             # App entry, CORS, middleware
│   │   ├── routes/
│   │   │   ├── query.py        # /api/query — natural language Q&A
│   │   │   ├── status.py       # /api/status — auto-generated statuses
│   │   │   ├── knowledge.py    # /api/knowledge-requests — KR CRUD
│   │   │   ├── expertise.py    # /api/expertise — who-knows-what
│   │   │   ├── dashboard.py    # /api/dashboard — team pulse data
│   │   │   └── admin.py        # /api/admin — team/user management
│   │   ├── models/             # SQLAlchemy / Pydantic models
│   │   ├── services/           # Business logic
│   │   │   ├── query_engine.py
│   │   │   ├── status_generator.py
│   │   │   ├── expertise_mapper.py
│   │   │   ├── kr_manager.py
│   │   │   └── dependency_router.py
│   │   └── core/
│   │       ├── config.py       # Env vars, secrets
│   │       ├── security.py     # Azure AD token validation
│   │       └── llm.py          # LLM abstraction layer
│   │
│   ├── ingestion/              # Data connectors
│   │   ├── email_connector.py  # Microsoft Graph API — mail
│   │   ├── call_connector.py   # Microsoft Graph API — transcripts
│   │   ├── task_connector.py   # Azure DevOps REST API
│   │   ├── git_connector.py    # Azure Repos / GitHub API
│   │   ├── normalizer.py       # Raw → WorkArtifact schema
│   │   └── embedder.py         # Chunk + embed into vector DB
│   │
│   ├── bot/                    # Teams bot
│   │   ├── app.py              # Bot Framework entry
│   │   ├── handlers.py         # Message handlers
│   │   ├── cards.py            # Adaptive Card templates
│   │   └── proactive.py        # Proactive messaging (dependency alerts)
│   │
│   ├── workers/                # Celery tasks
│   │   ├── ingest_email.py
│   │   ├── ingest_calls.py
│   │   ├── ingest_tasks.py
│   │   ├── ingest_git.py
│   │   ├── generate_status.py
│   │   ├── update_expertise.py
│   │   └── route_kr.py
│   │
│   ├── db/
│   │   ├── migrations/         # Alembic migrations
│   │   └── seed.py             # Dev seed data
│   │
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── dashboard/                  # Next.js frontend
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx                 # Team pulse overview
│   │   │   ├── status/page.tsx          # Auto-generated statuses
│   │   │   ├── expertise/page.tsx       # Expertise map
│   │   │   ├── knowledge/page.tsx       # Knowledge repo browser
│   │   │   ├── knowledge/gaps/page.tsx  # Gap analytics
│   │   │   └── settings/page.tsx        # Team config
│   │   ├── components/
│   │   │   ├── TeamPulse.tsx
│   │   │   ├── StatusCard.tsx
│   │   │   ├── ExpertiseGraph.tsx
│   │   │   ├── KnowledgeRequestCard.tsx
│   │   │   ├── ActivityBars.tsx
│   │   │   └── GapAnalytics.tsx
│   │   └── lib/
│   │       ├── api.ts           # API client
│   │       └── auth.ts          # MSAL auth
│   ├── tailwind.config.ts
│   ├── Dockerfile
│   └── package.json
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 5. Data Models & Schemas

### 5.1 PostgreSQL Tables

#### `people`

```sql
CREATE TABLE people (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    azure_ad_id     VARCHAR(128) UNIQUE NOT NULL,
    email           VARCHAR(256) UNIQUE NOT NULL,
    display_name    VARCHAR(256) NOT NULL,
    team_id         UUID REFERENCES teams(id),
    role            VARCHAR(32) DEFAULT 'member',   -- 'member' | 'manager' | 'admin'
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

#### `teams`

```sql
CREATE TABLE teams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(256) NOT NULL,
    org_id          UUID REFERENCES orgs(id),
    manager_id      UUID REFERENCES people(id),
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

#### `work_artifacts` — the universal record

```sql
CREATE TABLE work_artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          VARCHAR(32) NOT NULL,    -- 'email' | 'call' | 'task' | 'git'
    source_id       VARCHAR(512) NOT NULL,   -- external ID (message-id, commit SHA, etc.)
    author_id       UUID REFERENCES people(id),
    team_id         UUID REFERENCES teams(id),
    artifact_type   VARCHAR(64) NOT NULL,    -- 'email_thread' | 'meeting_transcript' |
                                             -- 'work_item' | 'commit' | 'pull_request' |
                                             -- 'pr_review' | 'comment'
    title           TEXT,
    content         TEXT NOT NULL,            -- full text content
    metadata        JSONB DEFAULT '{}',       -- {repo, branch, ticket_id, attendees, ...}
    occurred_at     TIMESTAMPTZ NOT NULL,     -- when created in the source system
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE INDEX idx_artifacts_author ON work_artifacts(author_id);
CREATE INDEX idx_artifacts_team ON work_artifacts(team_id);
CREATE INDEX idx_artifacts_type ON work_artifacts(artifact_type);
CREATE INDEX idx_artifacts_occurred ON work_artifacts(occurred_at DESC);
CREATE INDEX idx_artifacts_metadata ON work_artifacts USING GIN(metadata);
```

#### `expertise_scores`

```sql
CREATE TABLE expertise_scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID REFERENCES people(id),
    topic           VARCHAR(256) NOT NULL,   -- 'salesforce-api' | 'react' | 'billing-service'
    score           FLOAT DEFAULT 0.0,       -- computed from artifact frequency + recency
    evidence_count  INT DEFAULT 0,
    last_seen       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (person_id, topic)
);

CREATE INDEX idx_expertise_topic ON expertise_scores(topic);
CREATE INDEX idx_expertise_score ON expertise_scores(score DESC);
```

#### `knowledge_requests`

```sql
CREATE TABLE knowledge_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id    UUID REFERENCES people(id) NOT NULL,
    question        TEXT NOT NULL,
    context         TEXT,                     -- what they were working on
    status          VARCHAR(32) DEFAULT 'open',  -- 'open' | 'routed' | 'answered' | 'indexed'
    routed_to_id    UUID REFERENCES people(id),
    answer          TEXT,
    answered_by_id  UUID REFERENCES people(id),
    answered_at     TIMESTAMPTZ,
    tags            TEXT[] DEFAULT '{}',
    related_artifacts UUID[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_kr_status ON knowledge_requests(status);
CREATE INDEX idx_kr_tags ON knowledge_requests USING GIN(tags);
```

#### `status_reports`

```sql
CREATE TABLE status_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID REFERENCES people(id),
    team_id         UUID REFERENCES teams(id),
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    summary         TEXT NOT NULL,            -- LLM-generated
    evidence        JSONB NOT NULL,           -- [{artifact_id, excerpt, type}, ...]
    generated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (person_id, period_start, period_end)
);
```

#### `query_log` — audit trail

```sql
CREATE TABLE query_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES people(id),
    query_text      TEXT NOT NULL,
    response_text   TEXT,
    sources_used    JSONB DEFAULT '[]',
    surface         VARCHAR(16) NOT NULL,    -- 'teams' | 'dashboard'
    latency_ms      INT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 5.2 Vector Store Collections

```
Collection: "hive_artifacts"
  - id:        UUID (matches work_artifacts.id)
  - embedding: float[768] or float[1024]
  - metadata:
      source, artifact_type, author_id, author_name,
      team_id, occurred_at, title, tags[]

Collection: "hive_knowledge_repo"
  - id:        UUID (matches knowledge_requests.id)
  - embedding: float[768]
  - metadata:
      question, answer, answered_by, tags[], created_at
```

---

## 6. Ingestion Pipeline (4 Streams)

> **Pattern:** Each connector runs as a Celery scheduled task (every 5–15 min) AND listens for real-time webhooks where available. Webhooks give instant updates; scheduled pulls catch anything webhooks miss.

### 6.1 Email Connector

**Source:** Microsoft Graph API

```python
# Setup:
# 1. Register Azure AD app with Mail.Read (application) permission
# 2. Create shared mailbox: hive@levelshift.com
# 3. CC Hive on all team threads — no individual mailbox access needed

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

async def fetch_emails(mailbox: str, since: datetime) -> list[dict]:
    """Fetch emails from the shared Hive mailbox since last check."""
    url = f"{GRAPH_BASE}/users/{mailbox}/messages"
    params = {
        "$filter": f"receivedDateTime ge {since.isoformat()}",
        "$select": "id,subject,bodyPreview,body,from,toRecipients,"
                   "ccRecipients,receivedDateTime,conversationId",
        "$orderby": "receivedDateTime desc",
        "$top": 50
    }
    messages = []
    async with httpx.AsyncClient() as client:
        while url:
            resp = await client.get(url, headers=auth_headers(), params=params)
            data = resp.json()
            messages.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            params = None
    return messages

def normalize_email(msg: dict, team_id: str) -> WorkArtifact:
    return WorkArtifact(
        source="email",
        source_id=msg["id"],
        author_id=resolve_person(msg["from"]["emailAddress"]["address"]),
        team_id=team_id,
        artifact_type="email_thread",
        title=msg["subject"],
        content=strip_html(msg["body"]["content"]),
        metadata={
            "conversation_id": msg["conversationId"],
            "to": [r["emailAddress"]["address"] for r in msg["toRecipients"]],
            "cc": [r["emailAddress"]["address"] for r in msg["ccRecipients"]],
        },
        occurred_at=msg["receivedDateTime"],
    )
```

**Webhook (real-time):**

```python
# POST https://graph.microsoft.com/v1.0/subscriptions
{
    "changeType": "created",
    "notificationUrl": "https://hive.levelshift.com/webhooks/email",
    "resource": "users/hive@levelshift.com/messages",
    "expirationDateTime": "2026-09-18T00:00:00Z",
    "clientState": "hive-secret-state"
}
```

### 6.2 Call / Meeting Connector

**Source:** Microsoft Teams — Graph API Meeting Transcripts

```python
# Requires: OnlineMeetingTranscript.Read.All permission
# Transcripts must be enabled in Teams admin center

async def fetch_transcripts(since: datetime) -> list[dict]:
    # Step 1: Get recent online meetings
    # GET /users/{userId}/onlineMeetings
    # Step 2: For each meeting, get transcripts
    # GET /users/{userId}/onlineMeetings/{meetingId}/transcripts
    # Step 3: Get transcript content
    # GET .../transcripts/{transcriptId}/content?$format=text/vtt
    # Step 4: Parse VTT format to extract speaker-labeled segments
    pass

def normalize_transcript(meeting: dict, vtt_content: str, team_id: str) -> WorkArtifact:
    return WorkArtifact(
        source="call",
        source_id=meeting["id"],
        author_id=None,  # multi-author — stored in metadata
        team_id=team_id,
        artifact_type="meeting_transcript",
        title=meeting["subject"],
        content=vtt_to_plaintext(vtt_content),
        metadata={
            "attendees": [a["emailAddress"]["address"]
                          for a in meeting.get("participants", {}).get("attendees", [])],
            "speakers": parse_vtt_speakers(vtt_content),
            "meeting_url": meeting.get("joinWebUrl"),
        },
        occurred_at=meeting["startDateTime"],
    )
```

> **Fallback:** If Graph API transcript access isn't available, accept manual transcript uploads (drag a .vtt or .txt into the Teams bot). Start with this — works day one with zero admin permissions.

### 6.3 Task / Backlog Connector

**Source:** Azure DevOps REST API

```python
ADO_BASE = "https://dev.azure.com/{org}/{project}/_apis"

async def fetch_work_items(since: datetime) -> list[dict]:
    wiql = {
        "query": f"""
        SELECT [System.Id], [System.Title], [System.State],
               [System.AssignedTo], [System.ChangedDate],
               [System.Description], [System.Tags],
               [System.WorkItemType], [System.IterationPath]
        FROM WorkItems
        WHERE [System.ChangedDate] >= '{since.strftime('%Y-%m-%d')}'
        ORDER BY [System.ChangedDate] DESC
        """
    }
    resp = await client.post(f"{ADO_BASE}/wit/wiql?api-version=7.1", json=wiql)
    ids = [item["id"] for item in resp.json()["workItems"]]

    # Batch fetch (max 200 per call)
    items = []
    for batch in chunks(ids, 200):
        resp = await client.get(
            f"{ADO_BASE}/wit/workitems?ids={','.join(map(str, batch))}"
            f"&$expand=relations&api-version=7.1"
        )
        items.extend(resp.json()["value"])
    return items

def normalize_work_item(item: dict, team_id: str) -> WorkArtifact:
    fields = item["fields"]
    return WorkArtifact(
        source="task",
        source_id=str(item["id"]),
        author_id=resolve_person(fields.get("System.AssignedTo", {}).get("uniqueName")),
        team_id=team_id,
        artifact_type="work_item",
        title=fields["System.Title"],
        content=f"{fields['System.Title']}\nState: {fields['System.State']}\n"
                f"Type: {fields['System.WorkItemType']}\n"
                f"Description: {strip_html(fields.get('System.Description', ''))}",
        metadata={
            "state": fields["System.State"],
            "work_item_type": fields["System.WorkItemType"],
            "iteration": fields.get("System.IterationPath"),
            "tags": fields.get("System.Tags", "").split("; "),
            "priority": fields.get("Microsoft.VSTS.Common.Priority"),
        },
        occurred_at=fields["System.ChangedDate"],
    )
```

**Webhook:** Azure DevOps → Project Settings → Service Hooks → Web Hooks → Event: "Work item updated" → URL: `https://hive.levelshift.com/webhooks/ado`

### 6.4 Git Connector

**Source:** Azure Repos / GitHub API

```python
async def fetch_commits(repo_id: str, since: datetime) -> list[dict]:
    url = f"{ADO_BASE}/git/repositories/{repo_id}/commits"
    params = {"searchCriteria.fromDate": since.isoformat(), "api-version": "7.1", "$top": 100}
    resp = await client.get(url, params=params)
    return resp.json()["value"]

async def fetch_pull_requests(repo_id: str, since: datetime) -> list[dict]:
    url = f"{ADO_BASE}/git/repositories/{repo_id}/pullrequests"
    params = {"searchCriteria.status": "all", "api-version": "7.1", "$top": 50}
    resp = await client.get(url, params=params)
    return [pr for pr in resp.json()["value"]
            if parse_dt(pr["creationDate"]) >= since]

def normalize_commit(commit: dict, repo_name: str, team_id: str) -> WorkArtifact:
    return WorkArtifact(
        source="git",
        source_id=commit["commitId"],
        author_id=resolve_person(commit["author"]["email"]),
        team_id=team_id,
        artifact_type="commit",
        title=commit["comment"].split("\n")[0][:200],
        content=commit["comment"],
        metadata={
            "repo": repo_name,
            "sha": commit["commitId"],
            "files_changed": commit.get("changeCounts", {}),
        },
        occurred_at=commit["author"]["date"],
    )

def normalize_pr(pr: dict, repo_name: str, team_id: str) -> WorkArtifact:
    return WorkArtifact(
        source="git",
        source_id=f"pr-{pr['pullRequestId']}",
        author_id=resolve_person(pr["createdBy"]["uniqueName"]),
        team_id=team_id,
        artifact_type="pull_request",
        title=pr["title"],
        content=f"{pr['title']}\n{pr.get('description', '')}\nStatus: {pr['status']}",
        metadata={
            "repo": repo_name,
            "pr_id": pr["pullRequestId"],
            "status": pr["status"],
            "source_branch": pr["sourceRefName"],
            "target_branch": pr["targetRefName"],
            "reviewers": [r["uniqueName"] for r in pr.get("reviewers", [])],
        },
        occurred_at=pr["creationDate"],
    )
```

### 6.5 Normalizer & Embedder

```python
from sentence_transformers import SentenceTransformer
import chromadb

# Load embedding model
embed_model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim, fast
# Production: "BAAI/bge-large-en-v1.5" (1024-dim, more accurate)

def chunk_content(content: str, max_tokens: int = 512) -> list[str]:
    """Split content into overlapping chunks for embedding."""
    sentences = content.split(". ")
    chunks, current = [], []
    current_len = 0
    for sent in sentences:
        word_count = len(sent.split())
        if current_len + word_count > max_tokens and current:
            chunks.append(". ".join(current) + ".")
            overlap = max(1, len(current) // 5)  # 20% overlap
            current = current[-overlap:]
            current_len = sum(len(s.split()) for s in current)
        current.append(sent)
        current_len += word_count
    if current:
        chunks.append(". ".join(current))
    return chunks

async def embed_and_store(artifact: WorkArtifact):
    """Chunk, embed, and store in vector DB + relational DB."""
    # 1. Save to PostgreSQL
    await db.work_artifacts.insert(artifact)

    # 2. Chunk and embed
    chunks = chunk_content(artifact.content)
    embeddings = embed_model.encode(chunks)

    # 3. Store in ChromaDB
    collection = chroma_client.get_or_create_collection("hive_artifacts")
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        collection.add(
            ids=[f"{artifact.id}_{i}"],
            embeddings=[embedding.tolist()],
            documents=[chunk],
            metadatas=[{
                "artifact_id": str(artifact.id),
                "source": artifact.source,
                "artifact_type": artifact.artifact_type,
                "author_id": str(artifact.author_id),
                "author_name": artifact.author_name,
                "team_id": str(artifact.team_id),
                "occurred_at": artifact.occurred_at.isoformat(),
                "title": artifact.title or "",
                "chunk_index": i,
            }]
        )

    # 4. Update expertise scores
    topics = extract_topics(artifact.content)
    await update_expertise(artifact.author_id, topics, artifact.occurred_at)
```

---

## 7. Knowledge Engine

### 7.1 Query Engine

```python
async def answer_query(query: str, user_id: str, team_id: str | None = None,
                        scope: str = "team") -> QueryResponse:
    """
    Main Q&A pipeline:
    1. Embed the query
    2. Retrieve relevant chunks from vector DB
    3. Filter by access scope
    4. Send to LLM with context
    5. Return sourced answer
    """
    # 1. Embed query
    query_embedding = embed_model.encode(query).tolist()

    # 2. Retrieve from vector DB
    collection = chroma_client.get_collection("hive_artifacts")
    where_filter = {"team_id": team_id} if scope == "team" else {}
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=15,
        where=where_filter if where_filter else None,
    )

    # Also search knowledge repo
    kr_collection = chroma_client.get_collection("hive_knowledge_repo")
    kr_results = kr_collection.query(query_embeddings=[query_embedding], n_results=5)

    # 3. Build context
    context_chunks = format_context(results, kr_results)

    # 4. Send to LLM
    response = await llm.chat(
        system=QUERY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Question: {query}\n\nContext:\n{context_chunks}"}]
    )

    # 5. Log and return
    await db.query_log.insert(QueryLog(
        user_id=user_id, query_text=query, response_text=response.text,
        sources_used=extract_sources(results), surface="teams",
    ))

    return QueryResponse(
        answer=response.text,
        sources=extract_sources(results),
        has_gap="Knowledge Request" in response.text,
    )
```

### 7.2 Status Generator

```python
async def generate_weekly_status(person_id: str, team_id: str,
                                  week_start: date, week_end: date) -> StatusReport:
    # 1. Fetch all artifacts for this person in the date range
    artifacts = await db.work_artifacts.query(
        author_id=person_id, occurred_at_gte=week_start, occurred_at_lte=week_end,
    )

    # 2. Group by type
    commits = [a for a in artifacts if a.artifact_type == "commit"]
    prs = [a for a in artifacts if a.artifact_type == "pull_request"]
    tickets = [a for a in artifacts if a.artifact_type == "work_item"]
    emails = [a for a in artifacts if a.artifact_type == "email_thread"]
    meetings = [a for a in artifacts if a.artifact_type == "meeting_transcript"]

    # 3. Send to LLM
    response = await llm.chat(
        system=STATUS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"""Generate status for {person.display_name}.
Week: {week_start} to {week_end}

Commits ({len(commits)}): {format_commits(commits)}
PRs ({len(prs)}): {format_prs(prs)}
Tickets ({len(tickets)}): {format_tickets(tickets)}
Emails ({len(emails)}): {format_email_summaries(emails)}
Meetings ({len(meetings)}): {format_meeting_summaries(meetings)}
"""}]
    )

    # 4. Store
    report = StatusReport(
        person_id=person_id, team_id=team_id,
        period_start=week_start, period_end=week_end,
        summary=response.text,
        evidence=[{"artifact_id": str(a.id), "type": a.artifact_type} for a in artifacts[:20]],
    )
    await db.status_reports.insert(report)
    return report
```

### 7.3 Expertise Mapper

```python
async def update_expertise(person_id: str, topics: list[str], occurred_at: datetime):
    for topic in topics:
        existing = await db.expertise_scores.get(person_id=person_id, topic=topic)
        if existing:
            recency_weight = 1.0 / max(1, (datetime.now() - occurred_at).days / 30)
            new_score = existing.score * 0.95 + recency_weight * 0.3
            await db.expertise_scores.update(
                id=existing.id, score=new_score,
                evidence_count=existing.evidence_count + 1, last_seen=occurred_at,
            )
        else:
            await db.expertise_scores.insert(ExpertiseScore(
                person_id=person_id, topic=topic,
                score=1.0, evidence_count=1, last_seen=occurred_at,
            ))

async def find_experts(topic: str, limit: int = 5) -> list[ExpertResult]:
    # Combine exact match + semantic search
    exact = await db.expertise_scores.query(
        topic_like=f"%{topic}%", order_by="score DESC", limit=limit
    )
    embedding = embed_model.encode(topic).tolist()
    vector_results = chroma_client.get_collection("hive_artifacts").query(
        query_embeddings=[embedding], n_results=50,
    )
    author_counts = Counter()
    for meta in vector_results["metadatas"][0]:
        author_counts[meta["author_id"]] += 1
    return merge_and_rank(exact, author_counts, limit)
```

### 7.4 Proactive Dependency Router

```python
async def on_task_assigned(work_item: WorkArtifact, assignee_id: str):
    """Triggered when someone is assigned a task. Surfaces related experts in Teams."""
    topics = extract_topics(work_item.content + " " + str(work_item.metadata))

    related_people = []
    for topic in topics:
        experts = await find_experts(topic, limit=3)
        related_people.extend(experts)

    if "repo" in work_item.metadata:
        related_artifacts = await db.work_artifacts.query(
            metadata_contains={"repo": work_item.metadata["repo"]},
            artifact_type__in=["commit", "pull_request"],
            limit=10, order_by="occurred_at DESC",
        )
    else:
        related_artifacts = []

    unique_experts = deduplicate([p for p in related_people if p.person_id != assignee_id])
    if not unique_experts:
        return

    card = build_dependency_card(task=work_item, experts=unique_experts[:3],
                                  related_artifacts=related_artifacts[:5])
    await teams_bot.send_proactive_message(user_id=assignee_id, card=card)
```

---

## 8. Knowledge Request Framework

```python
async def handle_knowledge_gap(query: str, user_id: str, context: str = "") -> KR:
    """
    Called when Hive can't answer OR user manually raises a KR.
    Gap → route to expert → notify → track until answered.
    """
    # 1. Create KR
    kr = await db.knowledge_requests.insert(KnowledgeRequest(
        requester_id=user_id, question=query,
        context=context, status="open", tags=extract_topics(query),
    ))

    # 2. Find best expert
    experts = []
    for tag in kr.tags:
        experts.extend(await find_experts(tag, limit=3))
    best_expert = rank_for_routing(experts)

    if best_expert:
        kr.status = "routed"
        kr.routed_to_id = best_expert.person_id
        await db.knowledge_requests.update(kr)

        card = build_kr_card(kr, requester=await db.people.get(user_id))
        await teams_bot.send_proactive_message(user_id=best_expert.person_id, card=card)
    else:
        await teams_bot.post_to_channel(
            team_id=await get_user_team(user_id), card=build_kr_open_card(kr),
        )
    return kr


async def handle_kr_answer(kr_id: str, answer: str, answered_by: str):
    """Expert answers → store → index in repo → notify requester."""
    kr = await db.knowledge_requests.get(kr_id)

    # 1. Store answer
    kr.answer = answer
    kr.answered_by_id = answered_by
    kr.answered_at = datetime.now()
    kr.status = "answered"
    await db.knowledge_requests.update(kr)

    # 2. Index in knowledge repo (vector DB)
    embedding = embed_model.encode(f"{kr.question}\n{kr.answer}").tolist()
    kr_collection = chroma_client.get_or_create_collection("hive_knowledge_repo")
    kr_collection.add(
        ids=[str(kr.id)],
        embeddings=[embedding],
        documents=[f"Q: {kr.question}\nA: {kr.answer}"],
        metadatas=[{
            "question": kr.question, "answer": kr.answer,
            "answered_by": answered_by, "tags": kr.tags,
            "created_at": kr.created_at.isoformat(),
        }]
    )
    kr.status = "indexed"
    await db.knowledge_requests.update(kr)

    # 3. Notify requester
    await teams_bot.send_proactive_message(user_id=kr.requester_id, card=build_kr_answered_card(kr))

    # 4. Update expertise scores for the answerer
    await update_expertise(answered_by, kr.tags, datetime.now())


def rank_for_routing(experts: list[ExpertResult]) -> ExpertResult | None:
    """Rank by expertise score, recency, and current load (open KRs)."""
    for expert in experts:
        open_kr_count = db.knowledge_requests.count(
            routed_to_id=expert.person_id, status="routed",
        )
        expert.routing_score = (
            expert.score * 0.5 + expert.recency_weight * 0.3 - open_kr_count * 0.2
        )
    experts.sort(key=lambda e: e.routing_score, reverse=True)
    return experts[0] if experts else None
```

---

## 9. Teams Bot (@Hive)

### 9.1 Teams App Manifest

```json
{
    "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
    "manifestVersion": "1.16",
    "version": "1.0.0",
    "id": "{{BOT_APP_ID}}",
    "name": { "short": "Hive", "full": "Hive — Team Knowledge Agent" },
    "description": {
        "short": "Ask Hive anything about your team's work",
        "full": "Hive absorbs your team's work trail and answers questions with sourced evidence."
    },
    "bots": [{
        "botId": "{{BOT_APP_ID}}",
        "scopes": ["personal", "team", "groupChat"],
        "commandLists": [{
            "scopes": ["personal", "team"],
            "commands": [
                { "title": "ask", "description": "Ask Hive a question" },
                { "title": "status", "description": "Get team/person status" },
                { "title": "who-knows", "description": "Find an expert on a topic" },
                { "title": "kr", "description": "Raise a Knowledge Request" }
            ]
        }]
    }],
    "permissions": ["identity", "messageTeamMembers"]
}
```

### 9.2 Bot Message Handler

```python
from botbuilder.core import TurnContext, ActivityHandler
from botbuilder.schema import Activity, Attachment

class HiveBot(ActivityHandler):

    async def on_message_activity(self, turn_context: TurnContext):
        text = remove_mention(turn_context.activity.text.strip(), "Hive")
        user_id = turn_context.activity.from_property.aad_object_id

        if text.lower().startswith("kr "):
            await self.handle_kr(turn_context, text, user_id)
        elif text.lower().startswith("who knows"):
            await self.handle_who_knows(turn_context, text, user_id)
        elif text.lower().startswith("status"):
            await self.handle_status(turn_context, text, user_id)
        else:
            await self.handle_query(turn_context, text, user_id)

    async def handle_query(self, ctx, query, user_id):
        await ctx.send_activity(Activity(type="typing"))
        result = await answer_query(query, user_id, await get_user_team(user_id))
        card = build_answer_card(query, result.answer, result.sources, result.has_gap)
        await ctx.send_activity(Activity(
            type="message",
            attachments=[Attachment(
                content_type="application/vnd.microsoft.card.adaptive", content=card,
            )]
        ))
```

### 9.3 Adaptive Card Templates

See the HTML blueprint for full card JSON for: answer cards, KR notification cards, KR answer forms, dependency routing cards, status cards.

---

## 10. Manager Dashboard (Web App)

### Pages & Routes

| Route | Page | Content |
|---|---|---|
| `/` | Team Pulse | % on track, activity bars, blocker count, highlights |
| `/status` | Auto Status | Per-person weekly cards with expand-to-evidence |
| `/expertise` | Expertise Map | Interactive topic → people graph, searchable |
| `/knowledge` | Knowledge Repo | Browsable answered KRs, searchable, tagged |
| `/knowledge/gaps` | Gap Analytics | Unanswered KRs, top topics, bus-factor alerts |
| `/settings` | Settings | Team members, connected repos, ingestion status |

### Key Component Interfaces

```typescript
// TeamPulse.tsx
interface TeamPulseData {
  onTrackPercent: number;
  totalTasks: number;
  blockedCount: number;
  staleCount: number;
  weeklyActivity: { commits: number; prs: number; tickets: number; emails: number };
  highlights: string[];
  alerts: Alert[];
}

// StatusCard.tsx
interface StatusCardProps {
  person: { name: string; avatarUrl: string; role: string };
  summary: string;
  evidence: Evidence[];
  period: { start: string; end: string };
  activityLevel: "high" | "normal" | "low" | "flagged";
}

// GapAnalytics.tsx
interface GapAnalyticsData {
  openKRs: number;
  avgResolutionHours: number;
  topRequestedTopics: { topic: string; count: number }[];
  busFactor: { person: string; soloTopics: string[]; routedKRs: number }[];
  trendLine: { week: string; newKRs: number; resolved: number }[];
}
```

### API Client

```typescript
// lib/api.ts
const API = process.env.NEXT_PUBLIC_API_URL;

export const api = {
  getTeamPulse: (teamId: string) => fetch(`${API}/api/dashboard/pulse?team_id=${teamId}`).then(r => r.json()),
  getTeamStatus: (teamId: string, week?: string) => fetch(`${API}/api/status/team/${teamId}?week=${week}`).then(r => r.json()),
  searchExpertise: (topic: string) => fetch(`${API}/api/expertise/search?topic=${topic}`).then(r => r.json()),
  getGapAnalytics: (teamId: string) => fetch(`${API}/api/knowledge-requests/analytics?team_id=${teamId}`).then(r => r.json()),
  askHive: (query: string, teamId: string) => fetch(`${API}/api/query`, {
    method: "POST", body: JSON.stringify({ query, team_id: teamId }),
  }).then(r => r.json()),
};
```

---

## 11. Auth & Permissions

```python
# Azure AD (Entra ID) — SSO with Microsoft 365

ROLES = {
    "member": {
        "can_query": True,
        "can_query_org": True,
        "can_create_kr": True,
        "can_answer_kr": True,
        "can_view_own_status": True,
        "can_view_team_status": False,
        "can_view_dashboard": False,
    },
    "manager": {
        "can_query": True,
        "can_query_org": True,
        "can_create_kr": True,
        "can_answer_kr": True,
        "can_view_own_status": True,
        "can_view_team_status": True,
        "can_view_dashboard": True,
        "can_view_gap_analytics": True,
    },
    "admin": {
        # Everything above plus:
        "can_manage_teams": True,
        "can_manage_connectors": True,
        "can_view_audit_log": True,
    },
}

# Scope enforcement:
# - Members query within their team's artifacts only
# - Org knowledge repo queryable by everyone
# - Dashboard is manager+ only
# - Nobody sees "up" — members can't see manager's emails
```

---

## 12. Privacy & Guardrails

**Non-negotiable principles:**

- **Read-only.** Hive never writes to any external system
- **No surveillance.** No keystrokes, no screen monitoring, no productivity scores. Work artifacts only
- **Scoped access.** Members see their team. Managers see their team. Nobody sees up
- **Full audit trail.** Every query logged — who asked what, when, via which surface
- **Data stays internal.** Use Azure OpenAI Service or Anthropic enterprise tier with DPA. For max security, self-host Mistral

**Data retention (configurable):**

```python
RETENTION_POLICY = {
    "work_artifacts": "365 days",
    "embeddings": "365 days",
    "query_log": "90 days",
    "status_reports": "forever",
    "knowledge_repo": "forever",
    "knowledge_requests": "forever",
}
```

---

## 13. Deployment & Infrastructure

### docker-compose.yml

```yaml
version: "3.9"
services:
  api:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, redis, chromadb]
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

  bot:
    build: ./backend
    ports: ["3978:3978"]
    env_file: .env
    depends_on: [api]
    command: python bot/app.py

  worker:
    build: ./backend
    env_file: .env
    depends_on: [postgres, redis, chromadb]
    command: celery -A workers.celery_app worker --loglevel=info

  scheduler:
    build: ./backend
    env_file: .env
    depends_on: [redis]
    command: celery -A workers.celery_app beat --loglevel=info

  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
    env_file: .env
    depends_on: [api]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: hive
      POSTGRES_USER: hive
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  chromadb:
    image: chromadb/chroma:latest
    ports: ["8001:8000"]
    volumes: [chromadata:/chroma/chroma]

volumes:
  pgdata:
  chromadata:
```

### .env.example

```bash
# Database
DATABASE_URL=postgresql://hive:password@postgres:5432/hive

# Redis
REDIS_URL=redis://redis:6379/0

# ChromaDB
CHROMA_URL=http://chromadb:8001

# Azure AD
AZURE_AD_TENANT_ID=your-tenant-id
AZURE_AD_CLIENT_ID=your-client-id
AZURE_AD_CLIENT_SECRET=your-client-secret

# Bot Framework
BOT_APP_ID=your-bot-app-id
BOT_APP_PASSWORD=your-bot-app-password

# Azure DevOps
ADO_ORG=your-org
ADO_PROJECT=your-project
ADO_PAT=your-personal-access-token

# LLM
LLM_PROVIDER=mistral
LLM_API_KEY=your-api-key
LLM_MODEL=mistral-large-latest

# Embedding
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Hive Mailbox
HIVE_MAILBOX=hive@levelshift.com

# Ingestion
INGEST_INTERVAL_MINUTES=10
```

---

## 14. AI Prompts Library

### Query System Prompt

```
You are Hive, an internal knowledge agent for a team at LevelShift.
You answer questions using ONLY the provided context from the team's work trail.

Rules:
1. ONLY use information from the provided context. Never make up information.
2. CITE every claim: commit SHA, ticket ID, PR number, email subject, meeting date.
3. Name specific people — "Nivas authored this", not "someone did this".
4. If context doesn't contain the answer, say so and offer to raise a Knowledge Request.
5. Be concise — lead with the answer.
6. Never speculate about people's motivations, productivity, or performance.
```

### Status Generator Prompt

```
Generate a concise weekly status from work artifacts.

Format:
- 3-5 bullet points max
- COMPLETED work first (merged PRs, closed tickets)
- Then IN-PROGRESS (open PRs, active tickets)
- Then BLOCKERS (stuck 3+ days, unresolved dependencies)
- Every bullet references a specific artifact

Rules:
- Facts only. No praise, no filler.
- Flag anything blocked 3+ business days.
- Flag tickets with no updates for 5+ days as "stale."
- Keep each bullet under 20 words.
```

### Topic Extraction Prompt

```
Extract 2-5 technical topics from this work artifact.
Specific technologies/services/domains — not generic words.

Good: "salesforce-rest-api", "jwt-token-refresh", "react-dashboard"
Bad: "code", "work", "update", "fix"

Return ONLY a JSON array: ["azure-devops-api", "celery-task-queue"]
```

### KR Routing Prompt

```
Given this Knowledge Request and potential experts (with scores and recent work),
recommend the best person to route it to.

Consider: expertise relevance, recency, current load (open KRs).
Return JSON: {"recommended_person_id": "...", "reason": "..."}
```

---

## 15. API Reference

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/query` | Ask Hive a question | member+ |
| GET | `/api/status/team/:teamId` | Team's weekly statuses | manager+ |
| GET | `/api/status/person/:personId` | Person's weekly status | self/manager |
| GET | `/api/expertise/search?topic=X` | Find experts on a topic | member+ |
| GET | `/api/expertise/map?team_id=X` | Full expertise graph | manager+ |
| POST | `/api/knowledge-requests` | Create a Knowledge Request | member+ |
| GET | `/api/knowledge-requests` | List KRs (filtered) | member+ |
| PUT | `/api/knowledge-requests/:id/answer` | Answer a KR | routed expert |
| GET | `/api/knowledge-requests/analytics` | Gap analytics | manager+ |
| GET | `/api/dashboard/pulse?team_id=X` | Team pulse overview | manager+ |
| GET | `/api/dashboard/activity?team_id=X` | Activity breakdown | manager+ |
| POST | `/webhooks/email` | Graph API email webhook | webhook secret |
| POST | `/webhooks/ado` | Azure DevOps service hook | webhook secret |
| POST | `/webhooks/git` | Git push/PR webhook | webhook secret |
| GET | `/api/admin/ingestion-status` | Connector health | admin |
| GET | `/api/admin/audit-log` | Query audit trail | admin |

### Query Request/Response Example

```json
// POST /api/query
{
    "query": "Who's worked on the billing API recently?",
    "team_id": "uuid-of-team",
    "scope": "team"
}

// Response
{
    "answer": "Deepa V. has the most recent work — PR #312 (billing auth) merged March 15...",
    "sources": [
        {
            "artifact_id": "uuid",
            "type": "pull_request",
            "title": "PR #312: Billing auth layer",
            "author": "Deepa V.",
            "date": "2026-03-15",
            "relevance": 0.94
        }
    ],
    "has_gap": false,
    "latency_ms": 1240
}
```

---

## 16. Phased Build Plan

### Phase 1 — Foundation (Weeks 1–3)

**Goal:** Core pipeline working end-to-end with one data source

- Set up project structure, Docker Compose, PostgreSQL, ChromaDB, Redis
- Build `work_artifacts` schema and Alembic migrations
- Build Git connector (simplest API, richest signal)
- Build normalizer + embedder pipeline
- Build basic query engine (embed → retrieve → LLM answer)
- Build CLI for testing: `python -m hive.cli "who worked on auth?"`
- **Milestone:** Ask a question about Git commits and get a sourced answer

### Phase 2 — Teams Bot (Weeks 4–5)

**Goal:** @Hive is live in Teams

- Register Azure Bot, create Teams app manifest
- Build bot message handler with query routing
- Build Adaptive Cards for answers and "raise KR" button
- Deploy bot (Azure or ngrok dev tunnel)
- Sideload in Teams for testing
- **Milestone:** `@Hive who wrote the most commits this week?` works in Teams

### Phase 3 — Tasks + Auto Status (Weeks 6–7)

**Goal:** Azure DevOps data flowing, auto-statuses generating

- Build Azure DevOps work item connector (pull + webhook)
- Build status generator — weekly per-person summaries
- Add `status` command to Teams bot
- Build expertise scorer
- Add `who-knows` command to Teams bot
- **Milestone:** Auto-generated weekly status for each team member

### Phase 4 — Knowledge Request Framework (Weeks 8–9)

**Goal:** Full KR loop working

- Build `knowledge_requests` table and API
- Build gap detection (query engine can't answer → offer KR)
- Build expert routing logic (expertise scores + load balancing)
- Build KR Adaptive Cards (submit, notify, answer form, confirmation)
- Build knowledge repo indexing (answered KR → vector DB)
- **Milestone:** Complete KR lifecycle in Teams

### Phase 5 — Email + Calls (Weeks 10–12)

**Goal:** All four data streams flowing

- Set up shared Hive mailbox, configure Graph API
- Build email connector with webhook subscriptions
- Build call/meeting transcript connector (or manual upload fallback)
- Enrich query engine with email + meeting context
- Build proactive dependency routing
- **Milestone:** Hive answers from all four data streams

### Phase 6 — Manager Dashboard (Weeks 13–16)

**Goal:** Full web dashboard live

- Set up Next.js with Azure AD auth (MSAL)
- Build Team Pulse page
- Build Status page with evidence drill-down
- Build Expertise Map (interactive D3 graph)
- Build Knowledge Repo browser
- Build Gap Analytics page
- Build Settings page
- **Milestone:** Manager sees full team picture without any other tool

### Phase 7 — Production Hardening (Weeks 17–20)

**Goal:** Reliable, secure, monitored, ready for real use

- Switch ChromaDB → Qdrant
- Add monitoring (Prometheus + Grafana)
- Error handling, retry logic, circuit breakers
- Rate limiting on LLM calls with cost tracking
- Security audit — scope enforcement, input sanitization
- Load testing
- Documentation
- **Milestone:** Hive running on one real team, stable, monitored

---

## Quick Start — First Session

1. `mkdir hive && cd hive && git init`
2. Copy the project structure from Section 4
3. `docker-compose up postgres redis chromadb`
4. Build the Git connector (Section 6.4)
5. Build the normalizer + embedder (Section 6.5)
6. Build the query engine (Section 7.1)
7. Test: `python -m hive.cli "who committed to the auth module?"`
8. Once working → Phase 2 (Teams bot)

---

*Hive Technical Blueprint v1.0 · Nivas · LevelShift · August 2026*
