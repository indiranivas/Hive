"""Central configuration. Every provider choice is env-driven so the same code
runs offline on SQLite and in production on Postgres + Qdrant/Chroma."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
DATA_DIR = BACKEND_ROOT / ".data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = f"sqlite:///{(DATA_DIR / 'hive.db').as_posix()}"
    auto_create_schema: bool = True
    redis_url: str = "redis://localhost:6379/0"

    vector_provider: Literal["sql", "chroma"] = "sql"
    chroma_url: str | None = None
    chroma_path: str = (DATA_DIR / "chroma").as_posix()

    # Knowledge graph: `memory` derives it from SQL on demand (no service);
    # `neo4j` mirrors it into Neo4j (Community Edition or Aura) for Cypher access.
    graph_provider: Literal["memory", "neo4j"] = "memory"
    # Artifact nodes are capped so a repo with 50k commits cannot blow up the
    # graph payload. The most recent ones win; aggregate edges (WORKED_IN) are
    # still derived from every artifact.
    graph_max_artifacts: int = 300
    neo4j_uri: str = "bolt://localhost:7687"
    # Aura's downloadable .env uses NEO4J_USERNAME; accept both spellings.
    neo4j_user: str = Field(
        default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME")
    )
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    # Embeddings are open source only: `hashing` is offline and dependency-free,
    # `sentence-transformers` runs local models with no egress.
    embedding_provider: Literal["hashing", "sentence-transformers"] = "hashing"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # The LLM is the one non-open-source piece: Azure OpenAI, inside the tenant.
    llm_provider: Literal["stub", "azure_openai"] = "stub"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0

    # --- Azure OpenAI Service ---
    # `deployment` is the name you gave the deployment in the Azure portal, not
    # the underlying model name -- Azure routes on the deployment.
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str | None = None
    azure_openai_auth: Literal["key", "entra"] = "key"
    # "auto" picks max_completion_tokens for reasoning deployments (o-series,
    # gpt-5) and max_tokens for the rest. Override if your resource disagrees.
    azure_openai_token_param: Literal["auto", "max_tokens", "max_completion_tokens"] = "auto"

    chunk_max_tokens: int = 512
    chunk_overlap_ratio: float = 0.2
    retrieval_top_k: int = 15
    retrieval_kr_top_k: int = 5
    # Calibrated for the lexical `hashing` embedder: on this corpus relevant hits
    # score 0.48-0.77 and irrelevant ones peak at 0.11. Re-tune when switching
    # to a semantic embedder.
    retrieval_min_score: float = 0.15
    retrieval_context_char_budget: int = 12000
    # graded = LangGraph loop that grades retrieval and retries with a rewritten
    # query before giving up; linear = single retrieval pass.
    retrieval_mode: Literal["graded", "linear"] = "graded"
    retrieval_max_rewrites: int = 1

    auth_mode: Literal["dev", "azure_ad"] = "dev"
    azure_ad_tenant_id: str | None = None
    azure_ad_client_id: str | None = None
    azure_ad_client_secret: str | None = None
    dev_user_email: str = "dev@levelshift.com"

    bot_app_id: str | None = None
    bot_app_password: str | None = None

    ado_org: str | None = None
    ado_project: str | None = None
    ado_pat: str | None = None
    ado_repos: str = ""

    github_token: str | None = None
    github_repos: str = ""

    git_local_repos: str = ""

    hive_mailbox: str | None = None
    ingest_interval_minutes: int = 10
    ingest_lookback_days: int = 30
    webhook_secret: str | None = None

    cors_origins: str = "http://localhost:3000"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def csv(self, raw: str) -> list[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return self.csv(self.cors_origins)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return settings
