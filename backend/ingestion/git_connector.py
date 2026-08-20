"""Git ingestion: commits and pull requests (blueprint section 6.4).

Three providers. `local` reads a clone with the git CLI -- no credentials, so
Phase 1 is testable on day one; `azure_repos` and `github` are the real ones.
"""

from __future__ import annotations

import base64
import logging
import subprocess
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from api.core.config import Settings, get_settings
from ingestion.normalizer import WorkArtifact, as_utc

logger = logging.getLogger(__name__)

ADO_API_VERSION = "7.1"
COMMIT_TITLE_LIMIT = 200


def _commit_artifact(source_id: str, message: str, author_email: str | None,
                     author_name: str | None, occurred_at: datetime,
                     metadata: dict[str, Any]) -> WorkArtifact:
    message = (message or "").strip()
    return WorkArtifact(
        source="git",
        source_id=source_id,
        artifact_type="commit",
        title=message.split("\n")[0][:COMMIT_TITLE_LIMIT] or f"commit {source_id[:8]}",
        content=message,
        occurred_at=occurred_at,
        author_name=author_name,
        metadata={**metadata, "author_email": author_email},
    )


def _pr_artifact(source_id: str, title: str, description: str, status: str,
                 author_email: str | None, author_name: str | None,
                 occurred_at: datetime, metadata: dict[str, Any]) -> WorkArtifact:
    return WorkArtifact(
        source="git",
        source_id=source_id,
        artifact_type="pull_request",
        title=title,
        content=f"{title}\n{description or ''}\nStatus: {status}".strip(),
        occurred_at=occurred_at,
        author_name=author_name,
        metadata={**metadata, "author_email": author_email, "status": status},
    )


class GitProvider(ABC):
    name: str

    @abstractmethod
    def fetch(self, since: datetime) -> list[WorkArtifact]: ...


class LocalGitProvider(GitProvider):
    """Reads commits from a local clone via `git log`. No API credentials needed."""

    SEP = "\x1f"
    RECORD = "\x1e"

    def __init__(self, repo_path: str | Path) -> None:
        self.path = Path(repo_path).expanduser()
        self.repo_name = self.path.name
        self.name = f"git:local:{self.repo_name}"

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed.stdout

    def fetch(self, since: datetime) -> list[WorkArtifact]:
        if not (self.path / ".git").exists() and not (self.path / "HEAD").exists():
            raise RuntimeError(f"{self.path} is not a git repository")

        # The separator LEADS the format: --numstat output follows the format string,
        # so a trailing separator would attach each commit's files to the next record.
        pretty = self.RECORD + self.SEP.join(["%H", "%aE", "%aN", "%aI", "%B"])
        raw = self._git(
            "log",
            f"--since={since.isoformat()}",
            f"--pretty=format:{pretty}",
            "--numstat",
            "--no-merges",
        )

        artifacts: list[WorkArtifact] = []
        for record in raw.split(self.RECORD):
            if not record.strip():
                continue
            fields = record.split(self.SEP)
            if len(fields) < 5:
                logger.warning("skipping malformed git log record in %s", self.repo_name)
                continue
            sha, email, author, authored_at = (field.strip() for field in fields[:4])
            message_lines, files = self._split_numstat(fields[4].splitlines())

            artifacts.append(
                _commit_artifact(
                    source_id=sha,
                    message="\n".join(message_lines).strip(),
                    author_email=email.lower() or None,
                    author_name=author or None,
                    occurred_at=as_utc(authored_at),
                    metadata={
                        "repo": self.repo_name,
                        "provider": "local",
                        "sha": sha,
                        "files_changed": files,
                        "file_count": len(files),
                    },
                )
            )
        return artifacts

    @staticmethod
    def _split_numstat(lines: Iterable[str]) -> tuple[list[str], list[str]]:
        message: list[str] = []
        files: list[str] = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) == 3 and (parts[0].isdigit() or parts[0] == "-"):
                files.append(parts[2].strip())
            else:
                message.append(line)
        return message, files


class AzureReposProvider(GitProvider):  # pragma: no cover - network
    def __init__(self, org: str, project: str, pat: str, repo: str) -> None:
        self.base = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}"
        self.repo_name = repo
        self.name = f"git:ado:{repo}"
        token = base64.b64encode(f":{pat}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}

    def _get(self, client: httpx.Client, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = client.get(
            f"{self.base}/{path}",
            headers=self._headers,
            params={**params, "api-version": ADO_API_VERSION},
        )
        response.raise_for_status()
        return response.json()

    def fetch(self, since: datetime) -> list[WorkArtifact]:
        artifacts: list[WorkArtifact] = []
        with httpx.Client(timeout=60.0) as client:
            commits = self._get(
                client,
                "commits",
                {"searchCriteria.fromDate": since.isoformat(), "$top": 200},
            ).get("value", [])
            for commit in commits:
                author = commit.get("author", {})
                artifacts.append(
                    _commit_artifact(
                        source_id=commit["commitId"],
                        message=commit.get("comment", ""),
                        author_email=(author.get("email") or "").lower() or None,
                        author_name=author.get("name"),
                        occurred_at=as_utc(author.get("date")),
                        metadata={
                            "repo": self.repo_name,
                            "provider": "azure_repos",
                            "sha": commit["commitId"],
                            "change_counts": commit.get("changeCounts", {}),
                            "url": commit.get("remoteUrl"),
                        },
                    )
                )

            prs = self._get(
                client, "pullrequests", {"searchCriteria.status": "all", "$top": 100}
            ).get("value", [])
            for pr in prs:
                created = as_utc(pr.get("creationDate"))
                if created < since:
                    continue
                created_by = pr.get("createdBy", {})
                artifacts.append(
                    _pr_artifact(
                        source_id=f"pr-{self.repo_name}-{pr['pullRequestId']}",
                        title=pr.get("title", ""),
                        description=pr.get("description", ""),
                        status=pr.get("status", "unknown"),
                        author_email=(created_by.get("uniqueName") or "").lower() or None,
                        author_name=created_by.get("displayName"),
                        occurred_at=created,
                        metadata={
                            "repo": self.repo_name,
                            "provider": "azure_repos",
                            "pr_id": pr["pullRequestId"],
                            "source_branch": pr.get("sourceRefName"),
                            "target_branch": pr.get("targetRefName"),
                            "reviewers": [
                                reviewer.get("uniqueName")
                                for reviewer in pr.get("reviewers", [])
                                if reviewer.get("uniqueName")
                            ],
                        },
                    )
                )
        return artifacts


class GitHubProvider(GitProvider):  # pragma: no cover - network
    def __init__(self, token: str, repo: str) -> None:
        self.repo_full = repo
        self.repo_name = repo.split("/")[-1]
        self.name = f"git:github:{repo}"
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def fetch(self, since: datetime) -> list[WorkArtifact]:
        base = f"https://api.github.com/repos/{self.repo_full}"
        artifacts: list[WorkArtifact] = []
        with httpx.Client(timeout=60.0, headers=self._headers) as client:
            commits = client.get(
                f"{base}/commits", params={"since": since.isoformat(), "per_page": 100}
            )
            commits.raise_for_status()
            for commit in commits.json():
                detail = commit.get("commit", {})
                author = detail.get("author", {})
                artifacts.append(
                    _commit_artifact(
                        source_id=commit["sha"],
                        message=detail.get("message", ""),
                        author_email=(author.get("email") or "").lower() or None,
                        author_name=author.get("name"),
                        occurred_at=as_utc(author.get("date")),
                        metadata={
                            "repo": self.repo_name,
                            "provider": "github",
                            "sha": commit["sha"],
                            "url": commit.get("html_url"),
                        },
                    )
                )

            prs = client.get(
                f"{base}/pulls",
                params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 50},
            )
            prs.raise_for_status()
            for pr in prs.json():
                created = as_utc(pr.get("created_at"))
                if created < since:
                    continue
                artifacts.append(
                    _pr_artifact(
                        source_id=f"pr-{self.repo_name}-{pr['number']}",
                        title=pr.get("title", ""),
                        description=pr.get("body") or "",
                        status=pr.get("state", "unknown"),
                        author_email=None,
                        author_name=(pr.get("user") or {}).get("login"),
                        occurred_at=created,
                        metadata={
                            "repo": self.repo_name,
                            "provider": "github",
                            "pr_id": pr["number"],
                            "source_branch": (pr.get("head") or {}).get("ref"),
                            "target_branch": (pr.get("base") or {}).get("ref"),
                            "url": pr.get("html_url"),
                        },
                    )
                )
        return artifacts


def build_git_providers(settings: Settings | None = None) -> list[GitProvider]:
    settings = settings or get_settings()
    providers: list[GitProvider] = []

    for path in settings.csv(settings.git_local_repos):
        providers.append(LocalGitProvider(path))

    if settings.ado_org and settings.ado_project and settings.ado_pat:
        for repo in settings.csv(settings.ado_repos):
            providers.append(
                AzureReposProvider(settings.ado_org, settings.ado_project, settings.ado_pat, repo)
            )

    for repo in settings.csv(settings.github_repos):
        providers.append(GitHubProvider(settings.github_token or "", repo))

    return providers


def default_since(settings: Settings | None = None) -> datetime:
    settings = settings or get_settings()
    return datetime.now(UTC) - timedelta(days=settings.ingest_lookback_days)


def resolve_authors(session, artifacts: list[WorkArtifact],
                    team_id: uuid.UUID | None) -> list[WorkArtifact]:
    """Attach person rows to artifacts, creating people for unseen commit emails."""
    from ingestion.normalizer import resolve_person

    for artifact in artifacts:
        person = resolve_person(
            session,
            artifact.metadata.get("author_email"),
            artifact.author_name,
            team_id=team_id,
        )
        if person:
            artifact.author_id = person.id
            artifact.author_name = person.display_name
        artifact.team_id = team_id
    return artifacts
