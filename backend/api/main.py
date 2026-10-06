"""FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from api.core.config import get_settings
from api.core.db import init_db
from api.models.schemas import HealthResponse
from api.routes import admin, dashboard, expertise, graph, knowledge, query, status

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("hive")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        # Dev convenience only; production schema comes from Alembic migrations.
        init_db()
        logger.info("schema ensured on %s", settings.database_url.split("@")[-1])
    yield


app = FastAPI(
    title="Hive API",
    version="0.1.0",
    description=(
        "Passive team knowledge layer: git ingestion, Q&A, expertise, "
        "status and knowledge requests"
    ),
    lifespan=lifespan,
)

@app.middleware("http")
async def json_errors(request: Request, call_next):
    # Registered before CORS so it sits inside it: an unhandled error otherwise
    # reaches the browser without CORS headers, and the dashboard can only report
    # "cannot reach the API" for what is really a 500 from a running server.
    try:
        return await call_next(request)
    except Exception as exc:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Hive hit an internal error: {type(exc).__name__}"},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query.router)
app.include_router(expertise.router)
app.include_router(status.router)
app.include_router(dashboard.router)
app.include_router(knowledge.router)
app.include_router(graph.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # A bare visit to the API host should land somewhere useful, not a 404.
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        embedding_provider=settings.embedding_provider,
        vector_provider=settings.vector_provider,
        graph_provider=settings.graph_provider,
        database="sqlite" if settings.is_sqlite else "postgresql",
    )
