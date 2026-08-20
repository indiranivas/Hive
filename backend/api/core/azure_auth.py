"""Azure OpenAI authentication.

Two supported modes:
  key   -- the resource's api-key header. Simplest; needs a secret in .env.
  entra -- Entra ID (managed identity / workload identity / az login) via
           azure-identity. Preferred in production: no long-lived secret, and
           many tenants disable local key auth on Cognitive Services outright.

Tokens are cached until shortly before expiry, so the credential is not hit on
every request.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
TOKEN_REFRESH_MARGIN_SECONDS = 120


class TokenProvider(Protocol):
    def __call__(self) -> str: ...


def entra_token_provider(scope: str = COGNITIVE_SERVICES_SCOPE) -> TokenProvider:
    """Bearer tokens from the ambient Azure identity, cached until near expiry."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "AZURE_OPENAI_AUTH=entra requires `pip install azure-identity`"
        ) from exc

    credential = DefaultAzureCredential()
    cache: dict[str, float | str] = {"token": "", "expires_on": 0.0}

    def provide() -> str:
        now = time.time()
        expires_on = float(cache["expires_on"])
        if cache["token"] and now < expires_on - TOKEN_REFRESH_MARGIN_SECONDS:
            return str(cache["token"])
        token = credential.get_token(scope)
        cache["token"] = token.token
        cache["expires_on"] = float(token.expires_on)
        return token.token

    return provide


def build_auth_headers(auth_mode: str, api_key: str | None,
                       token_provider: Callable[[], str] | None = None) -> dict[str, str]:
    """Header set for one Azure OpenAI request.

    Called per request so an Entra token is always current.
    """
    if auth_mode == "entra":
        provider = token_provider or entra_token_provider()
        return {"Authorization": f"Bearer {provider()}"}
    if not api_key:
        raise RuntimeError(
            "Azure OpenAI needs AZURE_OPENAI_API_KEY, or AZURE_OPENAI_AUTH=entra "
            "to use the ambient Azure identity."
        )
    return {"api-key": api_key}
