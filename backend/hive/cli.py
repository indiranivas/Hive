"""Hive CLI -- the Phase 1 test harness.

    python -m hive.cli init-db
    python -m hive.cli seed
    python -m hive.cli ingest-git --repo ../..
    python -m hive.cli ask "who worked on the auth module?"
    python -m hive.cli experts jwt-auth
    python -m hive.cli bot "who knows billing-service"
    python -m hive.cli status

Output is deliberately ASCII-only so it renders in any Windows console codepage.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from api.core.config import get_settings
from api.core.db import init_db, session_scope
from api.core.security import resolve_dev_user
from api.core.vectorstore import ARTIFACT_COLLECTION, KNOWLEDGE_COLLECTION, get_vector_store
from api.models.orm import IngestionState, Person, WorkArtifact
from api.services.expertise_mapper import find_experts
from api.services.query_engine import answer_query
from ingestion.git_connector import LocalGitProvider
from ingestion.runner import default_team_id, run_git_ingestion, run_provider

WRAP = textwrap.TextWrapper(width=96, subsequent_indent="  ")


def _out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def cmd_init_db(_: argparse.Namespace) -> int:
    init_db()
    _out(f"schema ready: {get_settings().database_url}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from db.seed import seed_demo_data

    init_db()
    with session_scope() as session:
        summary = seed_demo_data(session, reset=args.reset)
    _out(
        "seeded: {people} people, {artifacts} artifacts, {chunks} chunks, "
        "{knowledge} answered KRs".format(**summary)
    )
    return 0


def cmd_ingest_git(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        team_id = default_team_id(session)
        since = (
            datetime.now(UTC) - timedelta(days=args.days)
            if args.days
            else None
        )
        if args.repo:
            runs = [
                run_provider(session, LocalGitProvider(repo), team_id, since)
                for repo in args.repo
            ]
        else:
            runs = run_git_ingestion(session, team_id=team_id, since=since)

    if not runs:
        _out("no git providers configured. Pass --repo PATH or set GIT_LOCAL_REPOS in .env")
        return 1
    for run in runs:
        if run.status == "ok":
            _out(
                f"[ok] {run.connector}: fetched={run.fetched} new={run.result.created} "
                f"updated={run.result.updated} skipped={run.result.skipped} "
                f"chunks={run.result.chunks}"
            )
        else:
            _out(f"[error] {run.connector}: {run.error}")
    return 0 if all(run.status == "ok" for run in runs) else 1


def cmd_ask(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip()
    if not question:
        _out("ask what?")
        return 2
    with session_scope() as session:
        user = resolve_dev_user(session)
        result = answer_query(
            session,
            question,
            user_id=user.id,
            team_id=user.team_id or default_team_id(session),
            scope=args.scope,
            surface="dashboard",
        )

    _out(f"Q: {question}")
    _out()
    for line in result.answer.splitlines():
        _out(WRAP.fill(line) if line.strip() else "")
    if result.sources:
        _out()
        _out("Sources:")
        for index, source in enumerate(result.sources[: args.sources], start=1):
            reference = f" [{source.reference}]" if source.reference else ""
            _out(
                f"  {index}. {source.type} | {source.author or 'unknown'} | "
                f"{source.date or '-'}{reference} (rel {source.relevance})"
            )
            _out(f"     {source.title}")
    _out()
    _out(
        f"[model={result.model} sources={len(result.sources)} gap={result.has_gap} "
        f"{result.latency_ms}ms]"
    )
    return 0


def cmd_experts(args: argparse.Namespace) -> int:
    with session_scope() as session:
        experts = find_experts(session, args.topic, limit=args.limit)
    if not experts:
        _out(f"no expertise evidence for '{args.topic}' yet")
        return 0
    _out(f"Experts on '{args.topic}':")
    for rank, expert in enumerate(experts, start=1):
        seen = expert.last_seen.date().isoformat() if expert.last_seen else "-"
        _out(
            f"  {rank}. {expert.display_name} <{expert.email}> "
            f"score={expert.score:.2f} evidence={expert.evidence_count} last_seen={seen}"
        )
        _out(f"     topics: {', '.join(expert.topics[:6])}")
    return 0


def _card_to_text(card: dict) -> list[str]:
    """Flatten an Adaptive Card into console lines."""
    lines: list[str] = []

    def walk(blocks: list[dict], indent: str = "") -> None:
        for block in blocks:
            kind = block.get("type")
            if kind == "TextBlock":
                text = (block.get("text") or "").strip()
                if text:
                    lines.extend(
                        indent + part.strip()
                        for part in text.splitlines()
                        if part.strip()
                    )
            elif kind == "FactSet":
                for fact in block.get("facts", []):
                    lines.append(f"{indent}- {fact.get('title')}: {fact.get('value')}")
            elif kind == "Container":
                walk(block.get("items", []), indent)

    walk(card.get("body", []))
    for action in card.get("actions", []):
        lines.append(f"[button] {action.get('title')} ({action.get('type')})")
    return lines


def cmd_bot(args: argparse.Namespace) -> int:
    """Drive the Teams dispatch path locally -- no Bot Framework SDK, no tunnel."""
    from bot.handlers import BotUser, handle_activity

    message = " ".join(args.message).strip()
    with session_scope() as session:
        user = resolve_dev_user(session)
        reply = handle_activity(
            session,
            text=message,
            user=BotUser(aad_object_id=user.azure_ad_id, email=user.email,
                         name=user.display_name),
        )
        kind = reply.kind
        card = reply.card

    if args.json:
        _out(json.dumps(card, indent=2))
        return 0

    _out(f"@Hive <- {message or '(empty)'}")
    _out(f"[{kind}]")
    _out()
    for line in _card_to_text(card or {}):
        _out(WRAP.fill(line) if not line.startswith("[button]") else line)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    settings = get_settings()
    with session_scope() as session:
        artifacts = session.execute(select(func.count(WorkArtifact.id))).scalar_one()
        # Count via the active vector store so chroma reports correctly too.
        store = get_vector_store()
        chunks = store.count(session, ARTIFACT_COLLECTION) + store.count(
            session, KNOWLEDGE_COLLECTION
        )
        people = session.execute(select(func.count(Person.id))).scalar_one()
        by_type = session.execute(
            select(WorkArtifact.artifact_type, func.count(WorkArtifact.id)).group_by(
                WorkArtifact.artifact_type
            )
        ).all()
        states = session.execute(select(IngestionState)).scalars().all()

    _out("Hive status")
    _out(f"  db={settings.database_url}")
    _out(
        f"  llm={settings.llm_provider} embeddings={settings.embedding_provider} "
        f"vectors={settings.vector_provider}"
    )
    _out(f"  people={people} artifacts={artifacts} chunks={chunks}")
    for artifact_type, count in sorted(by_type):
        _out(f"    {artifact_type}: {count}")
    if states:
        _out("  connectors:")
        for state in states:
            last_run = state.last_run_at.isoformat(timespec="seconds") if state.last_run_at else "-"
            _out(
                f"    {state.connector}: {state.last_status} last_run={last_run} "
                f"ingested={state.artifacts_ingested}"
            )
            if state.last_error:
                _out(f"      error: {state.last_error[:160]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hive", description="Hive Phase 1 CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="create tables").set_defaults(func=cmd_init_db)

    seed = sub.add_parser("seed", help="load demo org, people and artifacts")
    seed.add_argument("--reset", action="store_true", help="delete existing data first")
    seed.set_defaults(func=cmd_seed)

    ingest = sub.add_parser("ingest-git", help="ingest commits and PRs")
    ingest.add_argument("--repo", action="append", help="local repo path (repeatable)")
    ingest.add_argument("--days", type=int, default=None, help="override lookback window")
    ingest.set_defaults(func=cmd_ingest_git)

    ask = sub.add_parser("ask", help="ask Hive a question")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--scope", choices=["team", "org"], default="team")
    ask.add_argument("--sources", type=int, default=5, help="how many sources to print")
    ask.set_defaults(func=cmd_ask)

    experts = sub.add_parser("experts", help="find who knows a topic")
    experts.add_argument("topic")
    experts.add_argument("--limit", type=int, default=5)
    experts.set_defaults(func=cmd_experts)

    bot = sub.add_parser("bot", help="simulate a Teams message to @Hive")
    bot.add_argument("message", nargs="*")
    bot.add_argument("--json", action="store_true", help="print the raw Adaptive Card")
    bot.set_defaults(func=cmd_bot)

    sub.add_parser("status", help="pipeline health").set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    known = {"init-db", "seed", "ingest-git", "ask", "experts", "bot", "status",
             "-h", "--help"}
    # `hive.cli "who wrote this?"` is shorthand for `hive.cli ask "..."`.
    if argv and argv[0] not in known:
        argv = ["ask", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
