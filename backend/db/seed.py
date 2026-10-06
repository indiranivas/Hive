"""Dev seed data: a plausible team work trail so the pipeline is queryable
immediately, with no connector credentials.

Fictional people and repos -- nothing here is real LevelShift data.

The dataset is deliberately overlapping: several people touch the same repos and
the same modules, PRs carry reviewers, and Knowledge Requests cite the commits
they came from. That overlap is what gives the knowledge graph something to
traverse -- a trail where everyone works alone produces a star, not a graph.

Three teams, ~10 weeks of activity relative to now, with every person active in
the last seven days so the weekly status and team pulse pages are populated. A
few modules (the SAP IDoc connector, the SAML fallback, the retention sweep)
deliberately rest on one person, to surface bus-factor risk.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from api.core.config import get_settings
from api.models.orm import Base, KnowledgeRequest, Org, Person, Team, WorkArtifact
from api.services.knowledge_repo import index_knowledge_request
from ingestion.embedder import persist_artifacts
from ingestion.normalizer import WorkArtifact as ArtifactDTO

NOW = datetime.now(UTC)

ORG_NAME = "LevelShift"

# team key -> display name. The dev user lands on `platform`.
TEAMS = {
    "platform": "Platform",
    "data": "Data & Insights",
    "delivery": "Client Delivery",
}
HOME_TEAM = "platform"

# (email, display_name, role, team key)
PEOPLE = [
    ("nivas.s@levelshift.com", "Nivas S", "manager", "platform"),
    ("deepa.v@levelshift.com", "Deepa V", "member", "platform"),
    ("arun.k@levelshift.com", "Arun K", "member", "platform"),
    ("priya.r@levelshift.com", "Priya R", "member", "platform"),
    ("karthik.m@levelshift.com", "Karthik M", "member", "platform"),
    ("meera.j@levelshift.com", "Meera J", "manager", "data"),
    ("sanjay.p@levelshift.com", "Sanjay P", "member", "data"),
    ("lakshmi.n@levelshift.com", "Lakshmi N", "member", "data"),
    ("suresh.l@levelshift.com", "Suresh L", "member", "platform"),
    ("kavya.d@levelshift.com", "Kavya D", "member", "data"),
    ("rahul.t@levelshift.com", "Rahul T", "manager", "delivery"),
    ("anitha.g@levelshift.com", "Anitha G", "member", "delivery"),
    ("vikram.s@levelshift.com", "Vikram S", "member", "delivery"),
    ("divya.b@levelshift.com", "Divya B", "member", "delivery"),
]

# team key -> the person who manages it
MANAGERS = {
    "platform": "nivas.s@levelshift.com",
    "data": "meera.j@levelshift.com",
    "delivery": "rahul.t@levelshift.com",
}

# (author_email, days_ago, repo, sha, title, body, files)
COMMITS = [
    # --- billing-service: Deepa leads, Karthik and Nivas cross into it ----------
    (
        "deepa.v@levelshift.com", 2, "billing-service", "a1b2c3d4e5f60718",
        "Fix JWT refresh loop in billing auth middleware",
        "The refresh token was re-issued on every 401 which stampeded the identity\n"
        "provider. Cache the refreshed token for its full TTL and retry once.",
        ["services/billing/auth_middleware.py", "tests/billing/test_auth_middleware.py"],
    ),
    (
        "deepa.v@levelshift.com", 5, "billing-service", "b2c3d4e5f6071829",
        "Add idempotency keys to invoice creation endpoint",
        "Duplicate invoices appeared when the client retried a timed-out POST.\n"
        "Invoice creation now requires an idempotency key stored in Redis.",
        ["services/billing/invoices.py", "services/billing/redis_client.py"],
    ),
    (
        "deepa.v@levelshift.com", 12, "billing-service", "c3d4e5f607182930",
        "Migrate invoice tables to Alembic revision 0007",
        "Adds the invoice_line_items table and backfills currency codes.",
        ["db/migrations/versions/0007_invoice_line_items.py"],
    ),
    (
        "deepa.v@levelshift.com", 21, "billing-service", "1a2b3c4d5e6f7081",
        "Retry Stripe webhook delivery with exponential backoff",
        "Stripe retries for 3 days; we were dropping the event on the first 500.\n"
        "Queue failed webhooks and back off up to 15 minutes.",
        ["services/billing/webhooks.py", "services/billing/queue.py"],
    ),
    (
        "karthik.m@levelshift.com", 8, "billing-service", "2b3c4d5e6f708192",
        "Move billing auth onto the shared identity client",
        "Billing was minting its own tokens. Point it at identity-service so the\n"
        "refresh policy lives in one place.",
        ["services/billing/auth_middleware.py", "services/billing/identity_client.py"],
    ),
    (
        "karthik.m@levelshift.com", 26, "billing-service", "3c4d5e6f70819203",
        "Add currency rounding rules for JPY and KRW",
        "Zero-decimal currencies were being multiplied by 100 twice.",
        ["services/billing/invoices.py", "services/billing/currency.py"],
    ),
    (
        "nivas.s@levelshift.com", 33, "billing-service", "4d5e6f7081920314",
        "Rate limit the invoice export endpoint",
        "A single tenant pulling a full export saturated the read replica.",
        ["services/billing/exports.py"],
    ),

    # --- hive-api: Arun leads, Nivas and Karthik cross in ------------------------
    (
        "arun.k@levelshift.com", 1, "hive-api", "d4e5f60718293041",
        "Add Azure DevOps work item connector skeleton",
        "Pulls work items via WIQL and normalizes them into WorkArtifact.\n"
        "Webhook handling comes next.",
        ["ingestion/task_connector.py", "tests/ingestion/test_task_connector.py"],
    ),
    (
        "arun.k@levelshift.com", 4, "hive-api", "e5f6071829304152",
        "Chunk transcripts by speaker turn before embedding",
        "Whole-meeting embeddings washed out topic signal. Chunk on speaker turns\n"
        "with 20 percent overlap.",
        ["ingestion/normalizer.py", "ingestion/embedder.py"],
    ),
    (
        "arun.k@levelshift.com", 9, "hive-api", "f607182930415263",
        "Cache Microsoft Graph tokens in Redis",
        "Graph token requests were rate limited during backfill. Cache per tenant.",
        ["ingestion/graph_auth.py"],
    ),
    (
        "arun.k@levelshift.com", 16, "hive-api", "5e6f708192031425",
        "Make ingestion watermarks per connector",
        "One global cursor meant a slow connector rewound the fast ones. Each\n"
        "connector now carries its own cursor, status and last error.",
        ["ingestion/runner.py", "api/models/orm.py"],
    ),
    (
        "arun.k@levelshift.com", 29, "hive-api", "6f70819203142536",
        "Merge keyword hits into vector retrieval 75/25",
        "Vector search alone missed exact identifiers like PR numbers and SHAs.",
        ["api/services/query_engine.py"],
    ),
    (
        "nivas.s@levelshift.com", 6, "hive-api", "3041526374859607",
        "Tighten scope enforcement on query endpoint",
        "Members can no longer pass an arbitrary team_id. Scope falls back to\n"
        "their own team unless they hold can_query_org.",
        ["api/routes/query.py", "api/core/security.py"],
    ),
    (
        "nivas.s@levelshift.com", 18, "hive-api", "4152637485960718",
        "Add query audit log with latency tracking",
        "Every question is logged with user, sources used, surface and latency.",
        ["api/services/query_engine.py", "db/migrations/versions/0003_query_log.py"],
    ),
    (
        "nivas.s@levelshift.com", 40, "hive-api", "7081920314253647",
        "Grade retrieval and retry once with a rewritten query",
        "A weak first pass now gets one rewrite instead of an immediate I-don't-know.",
        ["api/services/retrieval_graph.py", "api/core/prompts.py"],
    ),
    (
        "karthik.m@levelshift.com", 13, "hive-api", "8192031425364758",
        "Validate Entra tokens against tenant JWKS",
        "AUTH_MODE=azure_ad now verifies RS256 signatures and maps oid to a person.",
        ["api/core/security.py", "tests/test_api.py"],
    ),
    (
        "sanjay.p@levelshift.com", 24, "hive-api", "9203142536475869",
        "Expose artifact counts per source for the warehouse export",
        "Data team needs daily counts by source to reconcile the pipeline.",
        ["api/routes/admin.py"],
    ),

    # --- identity-service: Karthik leads, Deepa crosses in -----------------------
    (
        "karthik.m@levelshift.com", 3, "identity-service", "0314253647586970",
        "Rotate signing keys without invalidating live sessions",
        "Publish the new JWKS entry an hour before switching the signing key so\n"
        "in-flight tokens still verify.",
        ["identity/keys.py", "identity/jwks.py"],
    ),
    (
        "karthik.m@levelshift.com", 11, "identity-service", "1425364758697081",
        "Add refresh token reuse detection",
        "A replayed refresh token now revokes the whole family and audits it.",
        ["identity/tokens.py", "tests/identity/test_tokens.py"],
    ),
    (
        "karthik.m@levelshift.com", 22, "identity-service", "2536475869708192",
        "Move session store from memory to Redis",
        "Sessions vanished on every deploy. Back them with Redis and a TTL.",
        ["identity/sessions.py", "identity/redis_client.py"],
    ),
    (
        "deepa.v@levelshift.com", 17, "identity-service", "3647586970819203",
        "Expose token introspection for billing",
        "Billing needs to check scope without decoding the token itself.",
        ["identity/tokens.py", "identity/api.py"],
    ),
    (
        "deepa.v@levelshift.com", 35, "identity-service", "4758697081920314",
        "Document the SAML fallback for the legacy tenant",
        "One tenant is still on SAML; record how the assertion maps to claims.",
        ["identity/saml.py", "docs/identity/saml-fallback.md"],
    ),

    # --- web-dashboard: Priya leads, Karthik crosses in --------------------------
    (
        "priya.r@levelshift.com", 3, "web-dashboard", "0718293041526374",
        "Build team pulse activity bars",
        "Weekly commit, PR and ticket counts per person, with a stale-task flag.",
        ["src/components/ActivityBars.tsx", "src/app/page.tsx"],
    ),
    (
        "priya.r@levelshift.com", 7, "web-dashboard", "1829304152637485",
        "Wire MSAL login and protect dashboard routes",
        "Azure AD sign-in with silent token refresh; managers only past /status.",
        ["src/lib/auth.ts", "src/middleware.ts"],
    ),
    (
        "priya.r@levelshift.com", 15, "web-dashboard", "2930415263748596",
        "Add expertise map force graph",
        "Force layout linking topics to people, sized by expertise score.",
        ["src/components/ExpertiseGraph.tsx"],
    ),
    (
        "priya.r@levelshift.com", 27, "web-dashboard", "5869708192031425",
        "Separate light and dark palettes instead of inverting",
        "Inverted dark mode washed out the categorical series. Pick both by hand.",
        ["src/app/globals.css", "src/lib/format.ts"],
    ),
    (
        "priya.r@levelshift.com", 44, "web-dashboard", "6970819203142536",
        "State missing data instead of faking a percentage",
        "On-track reads em-dash with the reason when the connector is absent.",
        ["src/app/page.tsx", "src/components/ui.tsx"],
    ),
    (
        "karthik.m@levelshift.com", 19, "web-dashboard", "7081920314253648",
        "Refresh the dashboard token silently on 401",
        "Reuse the identity-service refresh policy rather than bouncing to login.",
        ["src/lib/auth.ts"],
    ),

    # --- data-pipeline: Sanjay and Lakshmi, Arun crosses in ----------------------
    (
        "sanjay.p@levelshift.com", 2, "data-pipeline", "8192031425364759",
        "Backfill warehouse dimensions from the artifact stream",
        "Nightly job rebuilds dim_person and dim_repo from work_artifacts.",
        ["pipeline/dimensions.py", "pipeline/warehouse.py"],
    ),
    (
        "sanjay.p@levelshift.com", 10, "data-pipeline", "9203142536475870",
        "Partition the fact table by ingestion day",
        "Full scans on a 200M row fact table were timing out the dashboard query.",
        ["pipeline/facts.py", "db/warehouse/0004_partition_facts.sql"],
    ),
    (
        "sanjay.p@levelshift.com", 23, "data-pipeline", "0314253647586971",
        "Add dead letter queue for malformed artifact payloads",
        "One bad payload aborted the whole batch. Park it and keep going.",
        ["pipeline/ingest.py", "pipeline/deadletter.py"],
    ),
    (
        "lakshmi.n@levelshift.com", 6, "data-pipeline", "1425364758697082",
        "Deduplicate artifacts on source and source_id in the warehouse",
        "Re-ingested commits produced duplicate fact rows and doubled the counts.",
        ["pipeline/facts.py", "pipeline/dedupe.py"],
    ),
    (
        "lakshmi.n@levelshift.com", 14, "data-pipeline", "2536475869708193",
        "Track pipeline freshness as a first class metric",
        "Emit lag per stage so a stalled backfill is visible before anyone asks.",
        ["pipeline/metrics.py", "pipeline/warehouse.py"],
    ),
    (
        "lakshmi.n@levelshift.com", 31, "data-pipeline", "3647586970819204",
        "Rewrite the retention sweep as an incremental job",
        "The full-table delete locked the warehouse for 40 minutes each Sunday.",
        ["pipeline/retention.py"],
    ),
    (
        "arun.k@levelshift.com", 20, "data-pipeline", "4758697081920315",
        "Publish the artifact stream to the pipeline over Redis",
        "Data team was polling the API. Push normalized artifacts onto a stream.",
        ["pipeline/ingest.py", "ingestion/runner.py"],
    ),

    # --- infra-terraform: Nivas owns it, Karthik and Meera cross in --------------
    (
        "nivas.s@levelshift.com", 9, "infra-terraform", "5869708192031426",
        "Move state to a locked Azure storage backend",
        "Two concurrent applies corrupted local state. Remote backend with a lease.",
        ["environments/prod/backend.tf", "modules/state/main.tf"],
    ),
    (
        "nivas.s@levelshift.com", 28, "infra-terraform", "6970819203142537",
        "Pin provider versions and add a plan gate to CI",
        "An unpinned provider upgrade rewrote half the plan overnight.",
        ["environments/prod/versions.tf", ".github/workflows/terraform.yml"],
    ),
    (
        "karthik.m@levelshift.com", 37, "infra-terraform", "7081920314253649",
        "Add the identity-service module and its key vault",
        "Signing keys move into Key Vault with a rotation policy.",
        ["modules/identity/main.tf", "modules/identity/keyvault.tf"],
    ),
    (
        "meera.j@levelshift.com", 42, "infra-terraform", "8192031425364760",
        "Provision the warehouse and its private endpoint",
        "Warehouse is reachable only from the pipeline subnet.",
        ["modules/warehouse/main.tf", "environments/prod/warehouse.tf"],
    ),
    (
        "nivas.s@levelshift.com", 41, "infra-terraform", "ec518a269384d0f2",
        "Add a budget alert per environment",
        "Dev quietly cost more than prod last month. Alert at 80 and 100 percent.",
        ["modules/budget/main.tf", "environments/prod/budget.tf"],
    ),
    (
        "nivas.s@levelshift.com", 69, "infra-terraform", "cae6b6d6556b711e",
        "Bootstrap the Terraform repo layout",
        "One folder per environment, shared modules, and a README on how to plan.",
        ["environments/prod/main.tf", "modules/README.md"],
    ),
    (
        "suresh.l@levelshift.com", 9, "infra-terraform", "64ae62370be071e2",
        "Add the client-portal app service and slot swap",
        "Delivery needs zero-downtime deploys for client demos. Staging slot plus\n"
        "a swap step gated on the health check.",
        ["modules/client_portal/main.tf", "environments/prod/client_portal.tf"],
    ),
    (
        "suresh.l@levelshift.com", 23, "infra-terraform", "2678450a36326352",
        "Put a Front Door WAF in front of the API",
        "OWASP rule set in prevention mode; the query endpoint gets a rate rule.",
        ["modules/frontdoor/main.tf", "modules/frontdoor/waf.tf"],
    ),
    (
        "vikram.s@levelshift.com", 39, "infra-terraform", "c0655bd8db9c7000",
        "Provision a Service Bus namespace for integration-hub",
        "Standard tier with one queue per connector and a shared dead letter.",
        ["modules/servicebus/main.tf", "environments/prod/integration_hub.tf"],
    ),
    (
        "rahul.t@levelshift.com", 47, "infra-terraform", "b22a5d42632114f1",
        "Tag every delivery resource with client and contract id",
        "Finance could not split the Azure bill by client. Tag policy enforced.",
        ["modules/policy/tags.tf"],
    ),
    (
        "meera.j@levelshift.com", 2, "infra-terraform", "bca061ec0496db4e",
        "Restrict warehouse access to the analyst role",
        "Engineers had db_owner on the warehouse. Read-only analyst role instead.",
        ["modules/warehouse/rbac.tf"],
    ),

    # --- client-portal: Anitha leads, Divya builds, Priya and Rahul cross in ------
    (
        "anitha.g@levelshift.com", 0, "client-portal", "5e18da5c4d92f9ab",
        "Add tenant-scoped feature flags to the portal shell",
        "Two clients want the deliverables view before the others. Flags resolve\n"
        "per tenant from the identity claim, defaulting off.",
        ["src/lib/flags.ts", "src/app/layout.tsx"],
    ),
    (
        "anitha.g@levelshift.com", 4, "client-portal", "4c69d0306f5a71fa",
        "Cache client project summaries for 60 seconds",
        "The home page fanned out to four services per load. Cache the summary\n"
        "per tenant and bust it on milestone updates.",
        ["src/lib/summary.ts", "src/app/page.tsx"],
    ),
    (
        "anitha.g@levelshift.com", 11, "client-portal", "991c64252ee395ce",
        "Paginate the deliverables table server-side",
        "The largest client has 3,000 deliverables; the table froze the tab.",
        ["src/app/deliverables/page.tsx", "src/lib/api.ts"],
    ),
    (
        "anitha.g@levelshift.com", 19, "client-portal", "833d21cccde90a1c",
        "Sign clients in through the shared identity client",
        "Portal had its own password table. Move it onto identity-service with\n"
        "the same refresh policy the dashboard uses.",
        ["src/lib/auth.ts", "src/lib/identity.ts"],
    ),
    (
        "anitha.g@levelshift.com", 33, "client-portal", "56846678f67d8e6f",
        "Scaffold the client portal on the Next.js app router",
        "Server components for data pages, client components only where needed.",
        ["src/app/layout.tsx", "src/app/page.tsx", "package.json"],
    ),
    (
        "anitha.g@levelshift.com", 47, "client-portal", "106ca1f93bd540ef",
        "Add the project milestone timeline",
        "Milestones render on a horizontal timeline with slip markers.",
        ["src/components/MilestoneTimeline.tsx"],
    ),
    (
        "anitha.g@levelshift.com", 61, "client-portal", "95b3397c8ab56c64",
        "Initial client portal design tokens",
        "Spacing, type scale and neutral palette agreed with the client team.",
        ["src/app/globals.css", "src/lib/tokens.ts"],
    ),
    (
        "divya.b@levelshift.com", 1, "client-portal", "62ca863f9f03199e",
        "Fix timezone drift in milestone due dates",
        "Due dates were stored as local midnight and rendered a day early for US\n"
        "clients. Store dates as plain calendar dates, never timestamps.",
        ["src/lib/dates.ts", "src/components/MilestoneTimeline.tsx"],
    ),
    (
        "divya.b@levelshift.com", 5, "client-portal", "bb07d0d604b8c0f4",
        "Add Playwright smoke tests for sign-in and deliverables",
        "Runs against a seeded demo tenant on every PR; traces kept on failure.",
        ["tests/e2e/signin.spec.ts", "tests/e2e/deliverables.spec.ts",
         "playwright.config.ts"],
    ),
    (
        "divya.b@levelshift.com", 13, "client-portal", "7c7117cf233082a3",
        "Make the deliverables table keyboard navigable",
        "Accessibility review flagged it. Arrow keys move rows, Enter opens.",
        ["src/components/DeliverablesTable.tsx"],
    ),
    (
        "divya.b@levelshift.com", 26, "client-portal", "7160170fd6ce3f85",
        "Add CSV export for client status reports",
        "Account managers were screenshotting the page into slides.",
        ["src/app/reports/export/route.ts", "src/lib/csv.ts"],
    ),
    (
        "divya.b@levelshift.com", 40, "client-portal", "9e94580d61f1014d",
        "Show sign-off state on each deliverable",
        "Pending, approved or changes requested, with who signed and when.",
        ["src/components/DeliverablesTable.tsx", "src/lib/api.ts"],
    ),
    (
        "divya.b@levelshift.com", 54, "client-portal", "69682a9d3c98f2fc",
        "Add empty and error states to portal pages",
        "A new client saw a blank page on day one. Say what is missing and why.",
        ["src/components/EmptyState.tsx", "src/app/error.tsx"],
    ),
    (
        "priya.r@levelshift.com", 9, "client-portal", "00431fe2ddfe6d7c",
        "Share the chart palette between dashboard and portal",
        "Portal charts drifted from the dashboard colours. Import the same tokens.",
        ["src/lib/tokens.ts", "src/components/StatusChart.tsx"],
    ),
    (
        "priya.r@levelshift.com", 52, "client-portal", "39b63e2b5b2b6c88",
        "Extract the shared UI kit into a package",
        "Buttons, cards and tables now come from one place for both front ends.",
        ["packages/ui/index.ts", "package.json"],
    ),
    (
        "rahul.t@levelshift.com", 3, "client-portal", "f945640d58faea54",
        "Add delivery health summary to the portal home",
        "RAG status per workstream with the reason, pulled from the milestone feed.",
        ["src/components/HealthSummary.tsx", "src/app/page.tsx"],
    ),
    (
        "rahul.t@levelshift.com", 66, "client-portal", "4d70e60a2c376f28",
        "Write the client portal acceptance criteria as e2e specs",
        "Each contract acceptance criterion maps to a named Playwright test.",
        ["tests/e2e/acceptance.spec.ts", "docs/acceptance.md"],
    ),

    # --- integration-hub: Vikram owns the SAP path; Arun, Sanjay, Kavya cross in --
    (
        "vikram.s@levelshift.com", 0, "integration-hub", "8d48a5028c3e2174",
        "Retry SAP IDoc posts with a poison message cap",
        "A malformed IDoc was retried forever and blocked the queue. Cap retries\n"
        "at five, then park it on the dead letter queue with the SAP status code.",
        ["hub/connectors/sap_idoc.py", "hub/queue.py"],
    ),
    (
        "vikram.s@levelshift.com", 2, "integration-hub", "8668c4eb15c9976f",
        "Map Salesforce opportunity stages to delivery phases",
        "Closed Won now opens a delivery project with the right phase template.",
        ["hub/connectors/salesforce.py", "hub/mappings/stages.yaml"],
    ),
    (
        "vikram.s@levelshift.com", 6, "integration-hub", "a69f9a3fc98635a5",
        "Verify HMAC signatures on inbound webhooks",
        "Unsigned webhooks are rejected with 401; secrets rotate via Key Vault.",
        ["hub/webhooks.py", "tests/hub/test_webhooks.py"],
    ),
    (
        "vikram.s@levelshift.com", 12, "integration-hub", "491ba81f7d91ab0a",
        "Add SAP IDoc parser for ORDERS05",
        "Parses header and item segments into the hub order model.",
        ["hub/connectors/sap_idoc.py", "hub/models/order.py"],
    ),
    (
        "vikram.s@levelshift.com", 18, "integration-hub", "1c472c3815ebb604",
        "Throttle outbound Salesforce calls to the API limit",
        "A bulk sync burned the daily API quota by noon. Token bucket per org.",
        ["hub/connectors/salesforce.py", "hub/ratelimit.py"],
    ),
    (
        "vikram.s@levelshift.com", 25, "integration-hub", "a41671ce8d3fe03d",
        "Add the connector registry and health endpoint",
        "Each connector reports last success, lag and error count at /health.",
        ["hub/registry.py", "hub/api.py"],
    ),
    (
        "vikram.s@levelshift.com", 32, "integration-hub", "f7474d20aa3f753a",
        "Store connector credentials as Key Vault references",
        "No more client secrets in app settings; the hub resolves them at start.",
        ["hub/secrets.py", "hub/config.py"],
    ),
    (
        "vikram.s@levelshift.com", 46, "integration-hub", "00729170d35d63f8",
        "Handle SAP IDoc segment version drift",
        "One client upgraded SAP and segment E1EDK01 grew two fields. Parse by\n"
        "name, not position, and log unknown fields instead of failing.",
        ["hub/connectors/sap_idoc.py"],
    ),
    (
        "vikram.s@levelshift.com", 58, "integration-hub", "d978014187b7c5f2",
        "Scaffold integration-hub with FastAPI and a worker",
        "API for webhooks, a separate worker for outbound sync.",
        ["hub/api.py", "hub/worker.py", "pyproject.toml"],
    ),
    (
        "vikram.s@levelshift.com", 68, "integration-hub", "252b4767ae6a5b9e",
        "Spike: compare Azure Service Bus and Redis streams",
        "Service Bus wins on dead lettering and sessions; notes in docs/adr.",
        ["docs/adr/0001-queue-choice.md"],
    ),
    (
        "arun.k@levelshift.com", 15, "integration-hub", "4edf33aa69c0519e",
        "Reuse the Hive watermark model for hub connectors",
        "Same per-connector cursor, status and last error as Hive ingestion.",
        ["hub/watermarks.py", "ingestion/runner.py"],
    ),
    (
        "arun.k@levelshift.com", 38, "integration-hub", "2d6d04504136e1cf",
        "Share the normalizer contract with integration-hub",
        "Hub events now emit the same WorkArtifact shape Hive ingests.",
        ["hub/normalizer.py", "ingestion/normalizer.py"],
    ),
    (
        "sanjay.p@levelshift.com", 5, "integration-hub", "bc21246f4e25ba1a",
        "Land hub events in the warehouse staging schema",
        "Orders and opportunities go to stg_hub_events for the nightly load.",
        ["hub/sinks/warehouse.py", "pipeline/staging.py"],
    ),
    (
        "kavya.d@levelshift.com", 3, "integration-hub", "f43f0235b81bc3ae",
        "Validate hub events against a schema before staging",
        "Bad events were failing the nightly load. Reject them at the edge.",
        ["hub/sinks/schema.py", "tests/hub/test_schema.py"],
    ),
    (
        "rahul.t@levelshift.com", 5, "integration-hub", "530ce0984574cc9f",
        "Document client onboarding steps for a new connector",
        "Checklist from credential request to first successful sync.",
        ["docs/onboarding.md"],
    ),

    # --- more billing-service ----------------------------------------------------
    (
        "deepa.v@levelshift.com", 0, "billing-service", "e9f9a33598d388ed",
        "Add proration for mid-cycle plan changes",
        "Upgrades were billed for the full month. Prorate by day, credit downgrades.",
        ["services/billing/proration.py", "services/billing/invoices.py"],
    ),
    (
        "deepa.v@levelshift.com", 30, "billing-service", "1cf21e195ab4343b",
        "Reconcile Stripe payouts against invoice totals",
        "Daily job flags payouts that do not match the sum of paid invoices.",
        ["services/billing/reconcile.py"],
    ),
    (
        "deepa.v@levelshift.com", 50, "billing-service", "d5fb803480189ec6",
        "Render invoice PDFs with tenant branding",
        "Logo and address per tenant; fonts embedded so PDFs match on every OS.",
        ["services/billing/pdf.py", "services/billing/templates/invoice.html"],
    ),
    (
        "deepa.v@levelshift.com", 64, "billing-service", "378101efa3b38c91",
        "Introduce the invoice state machine",
        "Draft, issued, paid, void. Illegal transitions now raise instead of saving.",
        ["services/billing/state.py", "services/billing/invoices.py"],
    ),
    (
        "karthik.m@levelshift.com", 45, "billing-service", "15062be069c7f48f",
        "Fix Decimal serialization in invoice API responses",
        "Amounts went out as floats and lost cents. Serialize Decimal as string.",
        ["services/billing/serializers.py"],
    ),
    (
        "suresh.l@levelshift.com", 4, "billing-service", "d7a9dd8e952df622",
        "Add OpenTelemetry traces to the billing request path",
        "Spans for auth, Redis and Stripe calls; trace id returned in a header.",
        ["services/billing/telemetry.py", "services/billing/app.py"],
    ),
    (
        "rahul.t@levelshift.com", 20, "billing-service", "9895af491d0e4fa3",
        "Support client-specific invoice terms for delivery contracts",
        "Some delivery contracts are net-45 or milestone billed. Terms come from\n"
        "the contract record instead of the global net-30 default.",
        ["services/billing/terms.py", "services/billing/invoices.py"],
    ),

    # --- more hive-api -----------------------------------------------------------
    (
        "arun.k@levelshift.com", 0, "hive-api", "09f5775ac4744b80",
        "Verify Azure DevOps webhook signatures",
        "Closes the open item on PR 118. Basic auth secret checked per hook.",
        ["ingestion/webhooks.py", "tests/ingestion/test_webhooks.py"],
    ),
    (
        "arun.k@levelshift.com", 36, "hive-api", "cd146ba27e696c5b",
        "Add an HNSW index for chunk embeddings",
        "Brute-force similarity crossed 400ms at 200k chunks.",
        ["db/migrations/versions/0005_chunk_hnsw.py", "ingestion/embedder.py"],
    ),
    (
        "arun.k@levelshift.com", 48, "hive-api", "6f501736e1e0f694",
        "Normalize Teams messages into WorkArtifact",
        "Thread replies fold into the parent so a discussion is one artifact.",
        ["ingestion/normalizer.py", "ingestion/teams_connector.py"],
    ),
    (
        "arun.k@levelshift.com", 62, "hive-api", "009a7695dc4660f3",
        "Bootstrap the ingestion runner and connector protocol",
        "Connectors implement fetch_since(cursor); the runner owns scheduling.",
        ["ingestion/runner.py", "ingestion/base.py"],
    ),
    (
        "nivas.s@levelshift.com", 1, "hive-api", "c57d6ca1329419c6",
        "Add manager-only weekly status endpoint",
        "Generates a per-person status from the last seven days of artifacts.",
        ["api/routes/status.py", "api/services/status_generator.py"],
    ),
    (
        "nivas.s@levelshift.com", 3, "hive-api", "dbb6dbea3900da76",
        "Cap Ask Hive context to 12 chunks with source diversity",
        "One chatty PR crowded out everything else. At most four chunks per artifact.",
        ["api/services/query_engine.py", "api/core/prompts.py"],
    ),
    (
        "nivas.s@levelshift.com", 53, "hive-api", "bf761d4ea0094579",
        "Add role-based route guards for manager pages",
        "Status and gap analytics are manager-only; members get a 403 with a reason.",
        ["api/core/security.py", "api/routes/dashboard.py"],
    ),
    (
        "nivas.s@levelshift.com", 67, "hive-api", "4ab8508674680abd",
        "Write the Hive architecture decision record",
        "Why read-only connectors, why Postgres plus vectors, why no write-back.",
        ["docs/adr/0001-architecture.md"],
    ),
    (
        "suresh.l@levelshift.com", 2, "hive-api", "397e035bd0cba790",
        "Add structured JSON logging with request ids",
        "Every log line carries request_id and user so a trace is one grep away.",
        ["api/core/logging.py", "api/main.py"],
    ),
    (
        "suresh.l@levelshift.com", 6, "hive-api", "56bebbce44a23fcd",
        "Add a readiness probe that checks the vector store",
        "The pod reported ready while the vector store was still loading.",
        ["api/routes/health.py"],
    ),
    (
        "suresh.l@levelshift.com", 16, "hive-api", "0424137d3575747e",
        "Run the API under gunicorn with uvicorn workers",
        "Single uvicorn process pinned one core during backfill queries.",
        ["Dockerfile", "gunicorn.conf.py"],
    ),
    (
        "suresh.l@levelshift.com", 34, "hive-api", "8e48b08f7c7f2848",
        "Multi-stage Docker build for the API",
        "Image dropped from 1.4GB to 310MB; build tools stay in the first stage.",
        ["Dockerfile", ".dockerignore"],
    ),
    (
        "karthik.m@levelshift.com", 39, "hive-api", "ff5c4427e1281141",
        "Map Entra group claims onto Hive roles",
        "Managers come from the Hive-Managers group instead of a manual flag.",
        ["api/core/security.py", "api/models/orm.py"],
    ),
    (
        "sanjay.p@levelshift.com", 44, "hive-api", "665a819183c98073",
        "Add warehouse export endpoint with cursor pagination",
        "Offset pagination skipped rows when artifacts landed mid-export.",
        ["api/routes/admin.py"],
    ),
    (
        "lakshmi.n@levelshift.com", 57, "hive-api", "ce208bdc6abb8b4e",
        "Include knowledge request tags in the export",
        "Analytics needs tags to rank the most requested topics.",
        ["api/routes/admin.py", "api/services/knowledge_repo.py"],
    ),

    # --- more identity-service ---------------------------------------------------
    (
        "karthik.m@levelshift.com", 0, "identity-service", "e6835b6413d46b74",
        "Add a per-client tenant claim for the client portal",
        "Portal tokens carry client_tenant so every API call is scoped server side.",
        ["identity/tokens.py", "identity/claims.py"],
    ),
    (
        "karthik.m@levelshift.com", 5, "identity-service", "c3b4e799a549a2eb",
        "Shorten access token TTL to 15 minutes",
        "Security review finding. Refresh handles the rest silently.",
        ["identity/tokens.py", "identity/config.py"],
    ),
    (
        "karthik.m@levelshift.com", 31, "identity-service", "f2804c49a40c13bf",
        "Add PKCE to the authorization code flow",
        "Required for the public SPA clients; confidential clients unaffected.",
        ["identity/authorize.py", "tests/identity/test_pkce.py"],
    ),
    (
        "karthik.m@levelshift.com", 59, "identity-service", "4049952efcde1e2f",
        "Rate limit the token endpoint per client",
        "A misconfigured client hammered /token in a loop. 30 per minute per client.",
        ["identity/api.py", "identity/ratelimit.py"],
    ),
    (
        "deepa.v@levelshift.com", 49, "identity-service", "df1ceaedd138858f",
        "Map SAML group attributes onto roles for the legacy tenant",
        "The legacy tenant sends groups as a semicolon list in one attribute.",
        ["identity/saml.py"],
    ),
    (
        "anitha.g@levelshift.com", 24, "identity-service", "f6f4e0b468e00801",
        "Register the client portal as a confidential client",
        "Redirect URIs per environment and the openid profile portal.read scopes.",
        ["identity/clients.yaml"],
    ),

    # --- more web-dashboard ------------------------------------------------------
    (
        "priya.r@levelshift.com", 0, "web-dashboard", "1179819b2ff4aa06",
        "Add gap analytics weekly trend chart",
        "Opened versus answered per week, with median resolution time on hover.",
        ["src/app/gaps/page.tsx", "src/components/TrendChart.tsx"],
    ),
    (
        "priya.r@levelshift.com", 1, "web-dashboard", "baa03eea1005a473",
        "Add org map view of people and repos",
        "Chords between teams show where work crosses a team boundary.",
        ["src/app/graph/page.tsx", "src/components/graph.tsx"],
    ),
    (
        "priya.r@levelshift.com", 37, "web-dashboard", "5c8ab417c29184d2",
        "Add the knowledge repo search page",
        "Answered requests searchable by tag and text, newest first.",
        ["src/app/knowledge/page.tsx", "src/lib/api.ts"],
    ),
    (
        "priya.r@levelshift.com", 60, "web-dashboard", "bb9739ad9553e571",
        "Set up the Next.js dashboard with Tailwind",
        "App router, strict TypeScript, and a typed API client.",
        ["package.json", "src/app/layout.tsx", "tailwind.config.ts"],
    ),
    (
        "karthik.m@levelshift.com", 63, "web-dashboard", "fbcdb746f14b43c5",
        "Add CSP headers to the dashboard",
        "Script sources locked to self; MSAL popup origin allowed explicitly.",
        ["src/middleware.ts", "next.config.js"],
    ),
    (
        "divya.b@levelshift.com", 22, "web-dashboard", "c699fc73801690b3",
        "Fix chart tooltips clipping on narrow screens",
        "Tooltips now flip inside the viewport instead of overflowing it.",
        ["src/components/ActivityBars.tsx", "src/components/ui.tsx"],
    ),

    # --- more data-pipeline ------------------------------------------------------
    (
        "sanjay.p@levelshift.com", 0, "data-pipeline", "8c02832bdbb21c0f",
        "Add resolution time metric for knowledge requests",
        "Median and p90 hours from asked to answered, per week and per team.",
        ["pipeline/metrics.py", "pipeline/knowledge.py"],
    ),
    (
        "sanjay.p@levelshift.com", 30, "data-pipeline", "54f07c30a8abbdfb",
        "Incremental load for the pull request fact table",
        "Only PRs updated since the last watermark are reloaded.",
        ["pipeline/facts.py", "pipeline/watermarks.py"],
    ),
    (
        "sanjay.p@levelshift.com", 51, "data-pipeline", "e0d8a4b1e8fa50c9",
        "Add tests for warehouse dimensions",
        "Uniqueness and not-null checks on dim_person and dim_repo keys.",
        ["tests/pipeline/test_dimensions.py"],
    ),
    (
        "sanjay.p@levelshift.com", 65, "data-pipeline", "226642b5e52dfb94",
        "Initial warehouse schema for work artifacts",
        "Star schema: fact_artifact with person, repo and day dimensions.",
        ["db/warehouse/0001_initial.sql"],
    ),
    (
        "lakshmi.n@levelshift.com", 1, "data-pipeline", "d8b235f0ab5b4546",
        "Make the backfill job resumable from the last partition",
        "A failed backfill restarted from day one. It now checkpoints each\n"
        "completed partition and resumes from the first missing one.",
        ["pipeline/backfill.py", "pipeline/checkpoints.py"],
    ),
    (
        "lakshmi.n@levelshift.com", 4, "data-pipeline", "0626ed5d8242d290",
        "Alert when pipeline freshness lag passes two hours",
        "Pages the data on-call through the existing metrics stream.",
        ["pipeline/metrics.py", "pipeline/alerts.py"],
    ),
    (
        "lakshmi.n@levelshift.com", 43, "data-pipeline", "3d62bee8b555e74a",
        "Tag PII columns in warehouse tables",
        "Email and display name columns carry a pii tag the retention sweep reads.",
        ["pipeline/retention.py", "db/warehouse/0006_pii_tags.sql"],
    ),
    (
        "kavya.d@levelshift.com", 1, "data-pipeline", "02981df19fbcf57f",
        "Add weekly trend rollup for gap analytics",
        "Opened and answered knowledge requests per ISO week, backfilled 12 weeks.",
        ["pipeline/knowledge.py", "pipeline/rollups.py"],
    ),
    (
        "kavya.d@levelshift.com", 5, "data-pipeline", "e7b20dd6e3dba352",
        "Add most-requested topics view over request tags",
        "Ranks tags by request count with the share still unanswered.",
        ["pipeline/knowledge.py", "db/warehouse/0008_topic_view.sql"],
    ),
    (
        "kavya.d@levelshift.com", 17, "data-pipeline", "5940dafc72759931",
        "Add expertise score snapshot table",
        "Weekly snapshot so we can show how expertise shifts over time.",
        ["pipeline/expertise.py", "db/warehouse/0007_expertise_snapshot.sql"],
    ),
    (
        "kavya.d@levelshift.com", 29, "data-pipeline", "020319234725eec5",
        "Add data quality checks on artifact authors",
        "Flags artifacts whose author email does not resolve to a person.",
        ["pipeline/quality.py"],
    ),
    (
        "kavya.d@levelshift.com", 55, "data-pipeline", "063900890de90b1d",
        "Profile null rates across the artifact stream",
        "Baseline report before we add quality gates.",
        ["notebooks/null_profile.py"],
    ),
    (
        "meera.j@levelshift.com", 6, "data-pipeline", "d74be4e8a145757d",
        "Add retention flags to warehouse table definitions",
        "Each table declares a retention class; the sweep enforces it next.",
        ["pipeline/retention.py", "db/warehouse/0009_retention_class.sql"],
    ),
    (
        "meera.j@levelshift.com", 27, "data-pipeline", "28335708a87380cb",
        "Define the warehouse SLA metrics",
        "Freshness under two hours, completeness over 99.5 percent, daily.",
        ["docs/warehouse-sla.md", "pipeline/metrics.py"],
    ),
    (
        "meera.j@levelshift.com", 56, "data-pipeline", "73106ced5e7fc4ec",
        "Set up the data-pipeline repo and CI",
        "Lint, type check and unit tests on every PR; nightly integration run.",
        [".github/workflows/ci.yml", "pyproject.toml"],
    ),
]

# (author_email, days_ago, repo, pr_id, title, description, status, branch, reviewers)
PULL_REQUESTS = [
    (
        "deepa.v@levelshift.com", 2, "billing-service", 312,
        "Billing auth layer hardening",
        "Fixes the JWT refresh loop, adds idempotency keys, and raises auth test\n"
        "coverage on the invoice path.",
        "completed", "feature/billing-auth",
        ["nivas.s@levelshift.com", "arun.k@levelshift.com"],
    ),
    (
        "karthik.m@levelshift.com", 8, "billing-service", 327,
        "Point billing at the shared identity client",
        "Removes the second token minting path. Blocked on the billing team\n"
        "confirming the scope list.",
        "active", "feature/shared-identity",
        ["deepa.v@levelshift.com"],
    ),
    (
        "arun.k@levelshift.com", 1, "hive-api", 118,
        "Work item connector + transcript chunking",
        "Azure DevOps WIQL pull plus speaker-turn transcript chunking. Still open:\n"
        "webhook signature verification.",
        "active", "feature/ado-connector",
        ["nivas.s@levelshift.com"],
    ),
    (
        "nivas.s@levelshift.com", 18, "hive-api", 131,
        "Query audit log and scope enforcement",
        "Server-side scope fallback plus the query_log table and its migration.",
        "completed", "feature/audit-log",
        ["arun.k@levelshift.com", "karthik.m@levelshift.com"],
    ),
    (
        "karthik.m@levelshift.com", 11, "identity-service", 45,
        "Key rotation and refresh reuse detection",
        "Overlapping JWKS publication and token family revocation on replay.",
        "completed", "feature/key-rotation",
        ["deepa.v@levelshift.com", "nivas.s@levelshift.com"],
    ),
    (
        "priya.r@levelshift.com", 3, "web-dashboard", 74,
        "Team pulse page",
        "Activity bars, blocker count and highlights. Blocked on the pulse API\n"
        "endpoint returning stale task counts.",
        "active", "feature/team-pulse",
        ["nivas.s@levelshift.com"],
    ),
    (
        "priya.r@levelshift.com", 27, "web-dashboard", 81,
        "Separate light and dark palettes",
        "Hand-picked palettes for both themes, applied before first paint.",
        "completed", "feature/theme-palettes",
        ["karthik.m@levelshift.com"],
    ),
    (
        "sanjay.p@levelshift.com", 10, "data-pipeline", 22,
        "Partitioned fact table and dead letter queue",
        "Daily partitions plus a parking lot for malformed payloads.",
        "completed", "feature/fact-partitions",
        ["meera.j@levelshift.com", "lakshmi.n@levelshift.com"],
    ),
    (
        "lakshmi.n@levelshift.com", 9, "data-pipeline", 29,
        "Warehouse deduplication on source and source_id",
        "Waiting on a decision about whether re-ingests should update or version.",
        "active", "feature/warehouse-dedupe",
        ["sanjay.p@levelshift.com"],
    ),
    (
        "anitha.g@levelshift.com", 33, "client-portal", 3,
        "Client portal scaffold",
        "App router skeleton, layout and the first data page.",
        "completed", "feature/scaffold",
        ["rahul.t@levelshift.com", "priya.r@levelshift.com"],
    ),
    (
        "divya.b@levelshift.com", 26, "client-portal", 9,
        "CSV export for client status reports",
        "Streams the report as CSV; columns match the status slide template.",
        "completed", "feature/csv-export",
        ["anitha.g@levelshift.com"],
    ),
    (
        "anitha.g@levelshift.com", 4, "client-portal", 12,
        "Portal SSO and project summary cache",
        "Moves sign-in onto identity-service and caches the home summary.",
        "completed", "feature/portal-sso",
        ["karthik.m@levelshift.com", "divya.b@levelshift.com"],
    ),
    (
        "divya.b@levelshift.com", 1, "client-portal", 15,
        "Milestone timezone fix and Playwright smoke suite",
        "Calendar dates instead of timestamps, plus sign-in and deliverables e2e.",
        "active", "fix/milestone-timezone",
        ["anitha.g@levelshift.com", "priya.r@levelshift.com"],
    ),
    (
        "vikram.s@levelshift.com", 58, "integration-hub", 2,
        "integration-hub scaffold",
        "FastAPI webhook receiver and a separate outbound worker.",
        "completed", "feature/scaffold",
        ["nivas.s@levelshift.com"],
    ),
    (
        "vikram.s@levelshift.com", 18, "integration-hub", 33,
        "Salesforce throttling and connector registry",
        "Token bucket per Salesforce org and a /health view of every connector.",
        "completed", "feature/sf-throttle",
        ["arun.k@levelshift.com", "sanjay.p@levelshift.com"],
    ),
    (
        "sanjay.p@levelshift.com", 5, "integration-hub", 39,
        "Hub events into warehouse staging",
        "New warehouse sink for orders and opportunities.",
        "active", "feature/warehouse-sink",
        ["vikram.s@levelshift.com", "kavya.d@levelshift.com"],
    ),
    (
        "rahul.t@levelshift.com", 5, "integration-hub", 40,
        "Connector onboarding guide",
        "Step-by-step checklist for bringing a new client connector live.",
        "completed", "docs/onboarding",
        ["vikram.s@levelshift.com"],
    ),
    (
        "vikram.s@levelshift.com", 0, "integration-hub", 41,
        "SAP IDoc retries and webhook HMAC",
        "Poison message cap on IDoc posts and signed inbound webhooks. Needs a\n"
        "second reviewer who knows the SAP side.",
        "active", "feature/idoc-retries",
        ["arun.k@levelshift.com", "rahul.t@levelshift.com"],
    ),
    (
        "karthik.m@levelshift.com", 0, "identity-service", 52,
        "Client portal tenant claim and shorter token TTL",
        "Adds client_tenant to portal tokens and drops access TTL to 15 minutes.",
        "active", "feature/client-tenant-claim",
        ["anitha.g@levelshift.com", "deepa.v@levelshift.com"],
    ),
    (
        "nivas.s@levelshift.com", 3, "hive-api", 122,
        "Weekly status endpoint and Ask Hive context cap",
        "Manager status generation plus per-artifact chunk limits in retrieval.",
        "completed", "feature/weekly-status",
        ["arun.k@levelshift.com", "suresh.l@levelshift.com"],
    ),
    (
        "suresh.l@levelshift.com", 6, "hive-api", 124,
        "Observability: JSON logs and readiness probe",
        "Request-scoped structured logs and a probe that waits for the vector store.",
        "active", "feature/observability",
        ["nivas.s@levelshift.com", "arun.k@levelshift.com"],
    ),
    (
        "priya.r@levelshift.com", 1, "web-dashboard", 88,
        "Gap analytics and org map views",
        "Weekly trend chart, resolution time and the people/repo chord view.",
        "active", "feature/gap-analytics",
        ["nivas.s@levelshift.com", "divya.b@levelshift.com"],
    ),
    (
        "lakshmi.n@levelshift.com", 4, "data-pipeline", 31,
        "Resumable backfill and freshness alerts",
        "Partition checkpoints and a two hour freshness alert.",
        "completed", "feature/resumable-backfill",
        ["sanjay.p@levelshift.com", "meera.j@levelshift.com"],
    ),
    (
        "kavya.d@levelshift.com", 3, "data-pipeline", 34,
        "Gap analytics rollups",
        "Weekly trend rollup and the most-requested topics view.",
        "active", "feature/gap-rollups",
        ["lakshmi.n@levelshift.com", "sanjay.p@levelshift.com"],
    ),
    (
        "deepa.v@levelshift.com", 0, "billing-service", 340,
        "Mid-cycle proration",
        "Day-based proration for upgrades and credits for downgrades.",
        "active", "feature/proration",
        ["karthik.m@levelshift.com", "rahul.t@levelshift.com"],
    ),
    (
        "suresh.l@levelshift.com", 9, "infra-terraform", 18,
        "Client portal app service",
        "App service, staging slot and a health-gated swap for client-portal.",
        "completed", "feature/client-portal-infra",
        ["nivas.s@levelshift.com", "anitha.g@levelshift.com"],
    ),
]

# (requester, answerer, question, answer, tags, related_shas, asked_days, answered_days)
KNOWLEDGE = [
    (
        "arun.k@levelshift.com",
        "nivas.s@levelshift.com",
        "Which Azure DevOps PAT scopes does the Hive task connector need?",
        "Read-only is enough: Work Items (Read), Code (Read) and Project and Team "
        "(Read). Do not grant write scopes -- Hive is read-only by design. Create the "
        "PAT on the service account, not a personal account, and set a 90 day expiry "
        "with a calendar reminder to rotate it.",
        ["azure-devops-api", "personal-access-token", "ingestion"],
        ["d4e5f60718293041"],
        10, 8,
    ),
    (
        "priya.r@levelshift.com",
        "karthik.m@levelshift.com",
        "How do we rotate a signing key without logging everyone out?",
        "Publish the new key into the JWKS document about an hour before you switch "
        "the signer, so tokens minted with the old key still verify while they live "
        "out their TTL. Only remove the old JWKS entry once the longest token TTL has "
        "passed. identity/keys.py does the overlap; the rotation policy itself lives "
        "in the Key Vault module in infra-terraform.",
        ["identity-service", "key-rotation", "jwks"],
        ["0314253647586970", "7081920314253649"],
        14, 13,
    ),
    (
        "sanjay.p@levelshift.com",
        "deepa.v@levelshift.com",
        "Why did invoice retries create duplicate rows in the warehouse?",
        "Because invoice creation was not idempotent before revision 0007. A client "
        "retry after a timeout produced a second invoice with a new id, so the "
        "warehouse saw two legitimate rows. Invoice creation now requires an "
        "idempotency key held in Redis; anything older than that migration needs the "
        "warehouse dedupe job to collapse it.",
        ["billing-service", "idempotency", "warehouse"],
        ["b2c3d4e5f6071829", "1425364758697082"],
        20, 18,
    ),
    (
        "lakshmi.n@levelshift.com",
        "arun.k@levelshift.com",
        "What chunk size did we settle on for meeting transcripts?",
        "512 tokens with 20 percent overlap, split on speaker turns rather than a "
        "fixed window. Whole-meeting embeddings washed out the topic signal and a "
        "fixed window cut people off mid-sentence. Sentence-aligned chunking with a "
        "hard word-count split as the backstop is in ingestion/normalizer.py.",
        ["chunking", "embeddings", "transcript"],
        ["e5f6071829304152"],
        30, 29,
    ),
    (
        "deepa.v@levelshift.com",
        "suresh.l@levelshift.com",
        "How do I find a single billing request in the traces?",
        "Every billing response carries an X-Trace-Id header; paste it into the "
        "trace search and you get the auth, Redis and Stripe spans for that call. "
        "If you only have a log line, the request_id field on it is the same id. "
        "Spans are kept for 7 days, so grab the id while the incident is fresh.",
        ["observability", "billing-service", "tracing"],
        ["d7a9dd8e952df622", "397e035bd0cba790"],
        2, 2,
    ),
    (
        "sanjay.p@levelshift.com",
        "vikram.s@levelshift.com",
        "How do SAP IDoc failures get retried, and where do poison messages go?",
        "The hub retries an IDoc post five times with backoff, then parks it on the "
        "Service Bus dead letter queue with the SAP status code attached. Fix the "
        "data in SAP or the mapping, then resubmit from the dead letter with "
        "`hub replay --queue sap-idoc`. Never purge the dead letter -- each message "
        "is a client order that has not landed yet.",
        ["integration-hub", "sap", "retries"],
        ["8d48a5028c3e2174", "491ba81f7d91ab0a"],
        3, 1,
    ),
    (
        "divya.b@levelshift.com",
        "anitha.g@levelshift.com",
        "How do I run the client portal Playwright suite locally against a seeded tenant?",
        "Run `npm run seed:demo` to create the demo tenant, then `npx playwright test "
        "--project=smoke`. The suite reads PORTAL_TEST_USER from .env.local; use the "
        "demo account, never a real client login. Failed runs leave a trace in "
        "test-results/ that opens with `npx playwright show-trace`.",
        ["client-portal", "testing", "ci"],
        ["bb07d0d604b8c0f4"],
        5, 4,
    ),
    (
        "kavya.d@levelshift.com",
        "sanjay.p@levelshift.com",
        "How are fact table partitions pruned when the dashboard queries the warehouse?",
        "The fact table is partitioned by ingestion day, so any query that filters "
        "on ingested_on prunes to just those partitions. Filtering on occurred_at "
        "alone does not prune and falls back to a full scan. Always add an "
        "ingested_on range a day wider than the occurred_at window you want.",
        ["warehouse", "partitioning", "data-pipeline"],
        ["9203142536475870"],
        12, 10,
    ),
    (
        "suresh.l@levelshift.com",
        "nivas.s@levelshift.com",
        "What is the process to apply a Terraform change to prod?",
        "Open a PR; CI runs terraform plan with pinned providers and posts the plan "
        "as a comment. A second person approves the plan, not just the code, and "
        "the apply runs from CI against the locked remote state -- never from a "
        "laptop. If the plan touches state or networking, post it in the platform "
        "channel before merging.",
        ["terraform", "infra", "ci"],
        ["6970819203142537", "5869708192031426"],
        16, 16,
    ),
    (
        "rahul.t@levelshift.com",
        "deepa.v@levelshift.com",
        "How do client-specific invoice terms override the default net-30?",
        "Billing reads payment terms from the contract record first and only falls "
        "back to the global net-30 when the contract has none. Set terms on the "
        "contract (net-45, net-60 or milestone) before the first invoice is issued; "
        "changing them later only affects new invoices, not ones already issued.",
        ["billing-service", "invoices", "client-portal"],
        ["9895af491d0e4fa3"],
        19, 17,
    ),
    (
        "anitha.g@levelshift.com",
        "karthik.m@levelshift.com",
        "Which redirect URIs and scopes does the client portal need in identity-service?",
        "Register one redirect URI per environment in identity/clients.yaml -- "
        "wildcards are rejected. The portal needs openid, profile and portal.read; "
        "add portal.write only for the sign-off flow. It is a confidential client, so "
        "the secret lives in Key Vault and is rotated with the signing keys.",
        ["identity-service", "client-portal", "oauth"],
        ["f6f4e0b468e00801", "833d21cccde90a1c"],
        25, 23,
    ),
    (
        "vikram.s@levelshift.com",
        "arun.k@levelshift.com",
        "Can integration-hub reuse the Hive connector watermark model?",
        "Yes -- copy the per-connector watermark rather than a global cursor. Each "
        "connector stores its own cursor, status and last error, so a slow SAP sync "
        "never rewinds Salesforce. Advance the cursor only after the batch is "
        "committed, otherwise a crash mid-batch silently skips records.",
        ["ingestion", "integration-hub", "watermarks"],
        ["4edf33aa69c0519e", "5e6f708192031425"],
        40, 37,
    ),
    (
        "lakshmi.n@levelshift.com",
        "sanjay.p@levelshift.com",
        "Where do malformed artifact payloads end up and how do I replay them?",
        "They land in the pipeline dead letter table with the raw payload and the "
        "validation error. Fix the producer first, then replay with "
        "`pipeline deadletter replay --since <date>`; replay is idempotent because "
        "the warehouse dedupes on source and source_id.",
        ["warehouse", "dead-letter", "ingestion"],
        ["0314253647586971", "1425364758697082"],
        44, 43,
    ),
    (
        "karthik.m@levelshift.com",
        "deepa.v@levelshift.com",
        "How does the legacy tenant's SAML assertion map onto Hive roles?",
        "The legacy tenant sends all groups as one semicolon-separated attribute, "
        "not repeated attributes. identity/saml.py splits it and maps Hive-Managers "
        "to manager and everything else to member. If a user shows up with no role, "
        "check the attribute name first -- it changed once when they upgraded ADFS.",
        ["identity-service", "saml", "legacy-tenant"],
        ["df1ceaedd138858f", "4758697081920314"],
        55, 50,
    ),
    (
        "priya.r@levelshift.com",
        "karthik.m@levelshift.com",
        "Why does the dashboard get a 401 right after login on Safari?",
        "Safari blocks the third-party cookie the silent refresh relied on, so the "
        "first API call goes out with an expired token. The dashboard now refreshes "
        "on 401 using the identity-service policy and retries once. If it still "
        "loops, clear the MSAL cache in local storage -- a stale account entry wins.",
        ["identity-service", "web-dashboard", "tokens"],
        ["7081920314253648", "1829304152637485"],
        60, 58,
    ),
]

# (requester, question, context, days_ago) -- left open so routing runs for real
OPEN_QUESTIONS = [
    (
        "priya.r@levelshift.com",
        "Who owns the Terraform state bucket and how do we unlock a stuck lease?",
        "A plan died halfway and the state lease is still held.",
        2,
    ),
    (
        "meera.j@levelshift.com",
        "Is there a runbook for restarting a failed data-pipeline backfill?",
        "The nightly dimension backfill failed twice this week.",
        4,
    ),
    (
        "deepa.v@levelshift.com",
        "What is our customer data retention policy in the warehouse?",
        "Asked by a customer during a security review.",
        6,
    ),
    (
        "rahul.t@levelshift.com",
        "What delivery SLA can we commit to for SAP IDoc orders in a client contract?",
        "A new client wants a contractual time from order creation to landing.",
        0,
    ),
    (
        "divya.b@levelshift.com",
        "Who can approve a new redirect URI for a client tenant in production?",
        "A client is moving the portal to their own subdomain next sprint.",
        1,
    ),
    (
        "kavya.d@levelshift.com",
        "How do we purge one client's data from the warehouse on request?",
        "Contract exit clause; need the steps and who signs off.",
        3,
    ),
]


def _commit_artifacts(team_of, people):
    artifacts = []
    for email, days_ago, repo, sha, title, body, files in COMMITS:
        person = people[email]
        artifacts.append(
            ArtifactDTO(
                source="git",
                source_id=sha,
                artifact_type="commit",
                title=title,
                content=f"{title}\n\n{body}",
                occurred_at=NOW - timedelta(days=days_ago),
                author_id=person.id,
                author_name=person.display_name,
                team_id=team_of(email),
                metadata={
                    "repo": repo,
                    "provider": "seed",
                    "sha": sha,
                    "author_email": email,
                    "files_changed": files,
                    "file_count": len(files),
                },
            )
        )
    return artifacts


def _pr_artifacts(team_of, people):
    artifacts = []
    for entry in PULL_REQUESTS:
        email, days_ago, repo, pr_id, title, description, status, branch, reviewers = entry
        person = people[email]
        artifacts.append(
            ArtifactDTO(
                source="git",
                source_id=f"pr-{repo}-{pr_id}",
                artifact_type="pull_request",
                title=f"PR #{pr_id}: {title}",
                content=f"{title}\n{description}\nStatus: {status}",
                occurred_at=NOW - timedelta(days=days_ago),
                author_id=person.id,
                author_name=person.display_name,
                team_id=team_of(email),
                metadata={
                    "repo": repo,
                    "provider": "seed",
                    "pr_id": pr_id,
                    "status": status,
                    "source_branch": branch,
                    "target_branch": "main",
                    "author_email": email,
                    # Reviewers are how the graph learns who reads whose code.
                    "reviewers": reviewers,
                },
            )
        )
    return artifacts


# Only the org chart survives a reset; everything else is derived data.
KEPT_TABLES = {"orgs", "teams", "people"}


def reset_data(session) -> None:
    """Clear derived data, then the seeded people.

    Tables are emptied in reverse dependency order taken from the metadata rather
    than a hand-written list -- a new table that references people (the
    notification outbox did) would otherwise break this with a foreign key error.
    """
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in KEPT_TABLES:
            session.execute(table.delete())

    # teams.manager_id still points at a seeded person -- clear it before the delete.
    session.execute(update(Team).values(manager_id=None))
    session.execute(delete(Person).where(Person.email.in_([row[0] for row in PEOPLE])))
    session.flush()


def _artifact_ids_by_source_id(session, source_ids: list[str]) -> dict[str, str]:
    """Map the shas the Knowledge Requests cite onto the rows they became."""
    if not source_ids:
        return {}
    rows = session.execute(
        select(WorkArtifact.source_id, WorkArtifact.id).where(
            WorkArtifact.source_id.in_(source_ids)
        )
    ).all()
    return {source_id: str(artifact_id) for source_id, artifact_id in rows}


def seed_demo_data(session, reset: bool = False) -> dict[str, int]:
    if reset:
        reset_data(session)

    org = session.execute(select(Org).where(Org.name == ORG_NAME)).scalar_one_or_none()
    if org is None:
        org = Org(name=ORG_NAME)
        session.add(org)
        session.flush()

    teams: dict[str, Team] = {}
    for key, name in TEAMS.items():
        team = session.execute(select(Team).where(Team.name == name)).scalar_one_or_none()
        if team is None:
            team = Team(name=name, org_id=org.id)
            session.add(team)
            session.flush()
        teams[key] = team

    people: dict[str, Person] = {}
    team_key_of: dict[str, str] = {}
    for email, display_name, role, team_key in PEOPLE:
        team_key_of[email] = team_key
        person = session.execute(
            select(Person).where(Person.email == email)
        ).scalar_one_or_none()
        if person is None:
            person = Person(
                email=email, display_name=display_name, role=role, team_id=teams[team_key].id
            )
            session.add(person)
            session.flush()
        else:
            person.team_id = person.team_id or teams[team_key].id
        people[email] = person

    for team_key, manager_email in MANAGERS.items():
        teams[team_key].manager_id = people[manager_email].id

    # Put the local dev user on the demo team so the dashboard has a scope that
    # actually contains data.
    dev_email = get_settings().dev_user_email.lower()
    dev_user = session.execute(
        select(Person).where(func.lower(Person.email) == dev_email)
    ).scalar_one_or_none()
    if dev_user is None:
        dev_user = Person(email=dev_email, display_name="Hive Dev User", role="admin")
        session.add(dev_user)
    dev_user.team_id = teams[HOME_TEAM].id
    dev_user.role = "admin"
    session.flush()

    def team_of(email: str):
        return teams[team_key_of[email]].id

    artifacts = _commit_artifacts(team_of, people) + _pr_artifacts(team_of, people)
    result = persist_artifacts(session, artifacts)

    artifact_ids = _artifact_ids_by_source_id(
        session, [sha for entry in KNOWLEDGE for sha in entry[5]]
    )

    knowledge_indexed = 0
    for requester, answerer, question, answer, tags, shas, asked, answered in KNOWLEDGE:
        existing = session.execute(
            select(KnowledgeRequest).where(KnowledgeRequest.question == question)
        ).scalar_one_or_none()
        if existing:
            continue
        kr = KnowledgeRequest(
            requester_id=people[requester].id,
            question=question,
            context="Raised from a question Hive could not answer from the work trail.",
            status="answered",
            routed_to_id=people[answerer].id,
            answer=answer,
            answered_by_id=people[answerer].id,
            created_at=NOW - timedelta(days=asked),
            answered_at=NOW - timedelta(days=answered),
            tags=tags,
            # Cited evidence: the graph turns these into (KR)-[:REFERENCES]->(Artifact).
            related_artifacts=[artifact_ids[sha] for sha in shas if sha in artifact_ids],
        )
        session.add(kr)
        session.flush()
        if index_knowledge_request(session, kr):
            knowledge_indexed += 1

    # Open questions go through the real capture path so routing, the expert
    # ranking and the notification outbox are all exercised by a fresh seed.
    from api.services.kr_manager import create_knowledge_request

    open_raised = 0
    for requester, question, context, days_ago in OPEN_QUESTIONS:
        # Match on the question alone: create_knowledge_request only dedupes rows
        # still in `open`, and routing moves them to `routed` immediately.
        existing = session.execute(
            select(KnowledgeRequest).where(KnowledgeRequest.question == question)
        ).scalar_one_or_none()
        if existing:
            continue
        kr = create_knowledge_request(session, people[requester].id, question, context)
        kr.created_at = NOW - timedelta(days=days_ago)
        session.flush()
        open_raised += 1

    return {
        "people": len(people),
        "artifacts": result.created + result.updated,
        "chunks": result.chunks,
        "knowledge": knowledge_indexed,
        "open_requests": open_raised,
    }
