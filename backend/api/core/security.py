"""Auth and role gates (blueprint section 11).

AUTH_MODE=dev resolves every request to a local admin user so the CLI and a
fresh checkout work without Entra ID. AUTH_MODE=azure_ad validates the bearer
token against the tenant's JWKS and maps the `oid` claim to a person.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.db import get_db
from api.models.orm import Person

ROLES: dict[str, dict[str, bool]] = {
    "member": {
        "can_query": True,
        "can_query_org": True,
        "can_create_kr": True,
        "can_answer_kr": True,
        "can_view_own_status": True,
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
        "can_query": True,
        "can_query_org": True,
        "can_create_kr": True,
        "can_answer_kr": True,
        "can_view_own_status": True,
        "can_view_team_status": True,
        "can_view_dashboard": True,
        "can_view_gap_analytics": True,
        "can_manage_teams": True,
        "can_manage_connectors": True,
        "can_view_audit_log": True,
    },
}

_jwks_cache: dict[str, Any] = {"fetched_at": 0.0, "keys": None}
_JWKS_TTL_SECONDS = 3600


def has_permission(role: str, permission: str) -> bool:
    return bool(ROLES.get(role, ROLES["member"]).get(permission, False))


def _jwks(tenant_id: str) -> dict[str, Any]:  # pragma: no cover - network
    now = time.time()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
        keys = response.json()
    _jwks_cache.update({"keys": keys, "fetched_at": now})
    return keys


def _decode_azure_token(token: str) -> dict[str, Any]:  # pragma: no cover - network
    settings = get_settings()
    if not settings.azure_ad_tenant_id or not settings.azure_ad_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_MODE=azure_ad requires AZURE_AD_TENANT_ID and AZURE_AD_CLIENT_ID",
        )
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_MODE=azure_ad requires `pip install pyjwt[crypto]`",
        ) from exc

    jwks_url = (
        f"https://login.microsoftonline.com/{settings.azure_ad_tenant_id}/discovery/v2.0/keys"
    )
    try:
        signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.azure_ad_client_id,
            issuer=f"https://login.microsoftonline.com/{settings.azure_ad_tenant_id}/v2.0",
        )
    except Exception as exc:  # noqa: BLE001 - any validation failure is a 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {exc}"
        ) from exc


def resolve_dev_user(session: Session) -> Person:
    settings = get_settings()
    email = settings.dev_user_email.lower()
    person = session.execute(
        select(Person).where(func.lower(Person.email) == email)
    ).scalar_one_or_none()
    if person is None:
        person = Person(email=email, display_name="Hive Dev User", role="admin")
        session.add(person)
        session.flush()
    return person


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Person:
    settings = get_settings()
    if settings.auth_mode == "dev":
        return resolve_dev_user(db)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token"
        )
    claims = _decode_azure_token(authorization.split(" ", 1)[1])
    azure_ad_id = claims.get("oid")
    email = (claims.get("preferred_username") or claims.get("email") or "").lower()
    if not azure_ad_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing oid/email claim"
        )

    person = db.execute(
        select(Person).where(Person.azure_ad_id == azure_ad_id)
    ).scalar_one_or_none()
    if person is None:
        person = db.execute(
            select(Person).where(func.lower(Person.email) == email)
        ).scalar_one_or_none()
    if person is None:
        person = Person(
            azure_ad_id=azure_ad_id,
            email=email,
            display_name=claims.get("name") or email,
        )
        db.add(person)
    else:
        person.azure_ad_id = person.azure_ad_id or azure_ad_id
    db.flush()
    return person


def require(permission: str) -> Callable[[Person], Person]:
    def dependency(user: Person = Depends(get_current_user)) -> Person:
        if not has_permission(user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{user.role}' lacks '{permission}'",
            )
        return user

    return dependency


def verify_webhook_secret(x_hive_secret: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="WEBHOOK_SECRET not configured"
        )
    if x_hive_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret"
        )
