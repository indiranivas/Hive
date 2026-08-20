"""LLM abstraction -- swap providers via LLM_PROVIDER without touching callers.

`stub` is the default so a fresh checkout runs with no API key: it produces an
extractive, cited answer straight from the retrieved context. It never invents
prose, which makes it a safe offline stand-in and keeps tests deterministic.

Production at LevelShift is `azure_openai` -- the data stays inside the tenant,
which is what the blueprint's privacy section requires.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import httpx

from api.core.azure_auth import build_auth_headers
from api.core.config import get_settings

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"

# Deployments whose API rejects `max_tokens` and `temperature` (the reasoning
# families). Azure returns a 400 rather than ignoring them, so detect by name.
REASONING_DEPLOYMENT_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt5")
NO_ANSWER_MARKER = (
    "I could not find anything in the team's work trail that answers this. "
    "I can raise a Knowledge Request and route it to the most likely expert."
)


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(ABC):
    model: str

    @abstractmethod
    def chat(self, system: str, messages: list[dict[str, str]]) -> LLMResponse: ...


class StubLLM(LLMClient):
    """Extractive fallback. Reads the context block the query engine composed and
    reflects the strongest evidence back with its citations intact."""

    model = "stub-extractive"
    _source_line = re.compile(r"^\[(\d+)\]\s*(.+)$")

    def chat(self, system: str, messages: list[dict[str, str]]) -> LLMResponse:
        prompt = messages[-1]["content"] if messages else ""
        _, _, context = prompt.partition("Context:")
        entries: list[tuple[str, str]] = []
        header: str | None = None
        for raw_line in context.splitlines():
            line = raw_line.strip()
            match = self._source_line.match(line)
            if match:
                header = match.group(2)
            elif header and line.startswith("Title:"):
                entries.append((header, line.removeprefix("Title:").strip()))
                header = None

        if not entries:
            return LLMResponse(text=NO_ANSWER_MARKER, model=self.model)

        lines = ["Closest evidence in the team's work trail:"]
        lines.extend(f"- {title} ({header})" for header, title in entries[:5])
        lines.append(
            "(No LLM configured -- this is a verbatim evidence list, not a synthesized "
            "answer. Set LLM_PROVIDER and LLM_API_KEY for prose answers.)"
        )
        return LLMResponse(text="\n".join(lines), model=self.model)


class MistralLLM(LLMClient):  # pragma: no cover - network
    URL = "https://api.mistral.ai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float,
                 timeout: float) -> None:
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=mistral requires LLM_API_KEY")
        self._api_key = api_key
        self.model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout

    def chat(self, system: str, messages: list[dict[str, str]]) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        usage = body.get("usage", {})
        return LLMResponse(
            text=body["choices"][0]["message"]["content"],
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class AzureOpenAILLM(LLMClient):
    """Azure OpenAI Service chat completions.

    Raw HTTPS rather than the openai SDK: it keeps this file's provider set
    consistent, adds no dependency, and makes the request shape assertable in
    tests via an injected transport.

    Azure quirks handled here:
      * the model is a *deployment* name in the URL, not a request field;
      * api-version is required and pinned per resource;
      * reasoning deployments reject `max_tokens`/`temperature`.
    """

    def __init__(self, endpoint: str, deployment: str, api_version: str,
                 api_key: str | None = None, auth_mode: str = "key",
                 max_tokens: int = 2048, temperature: float = 0.1,
                 timeout: float = 60.0, token_param: str = "auto",
                 client: httpx.Client | None = None,
                 token_provider: Callable[[], str] | None = None) -> None:
        if not endpoint:
            raise RuntimeError("LLM_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT")
        if not deployment:
            raise RuntimeError(
                "LLM_PROVIDER=azure_openai requires AZURE_OPENAI_DEPLOYMENT "
                "(the deployment name, not the model name)"
            )
        self._endpoint = endpoint.rstrip("/")
        self.model = deployment
        self._api_version = api_version
        self._api_key = api_key
        self._auth_mode = auth_mode
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout
        self._token_param = token_param
        self._client = client
        self._token_provider = token_provider

    @property
    def url(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self.model}/chat/completions"
            f"?api-version={self._api_version}"
        )

    def _is_reasoning_deployment(self) -> bool:
        name = self.model.lower()
        return any(name.startswith(prefix) for prefix in REASONING_DEPLOYMENT_PREFIXES)

    def build_payload(self, system: str, messages: list[dict[str, str]]) -> dict:
        payload: dict = {
            "messages": [{"role": "system", "content": system}, *messages],
        }
        reasoning = self._is_reasoning_deployment()
        if self._token_param == "max_completion_tokens" or (
            self._token_param == "auto" and reasoning
        ):
            payload["max_completion_tokens"] = self._max_tokens
        else:
            payload["max_tokens"] = self._max_tokens
        # Reasoning deployments reject a temperature other than the default.
        if not reasoning:
            payload["temperature"] = self._temperature
        return payload

    def chat(self, system: str, messages: list[dict[str, str]]) -> LLMResponse:
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(self._auth_mode, self._api_key, self._token_provider),
        }
        payload = self.build_payload(system, messages)

        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = client.post(self.url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        finally:
            if self._client is None:
                client.close()

        choice = (body.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason") == "content_filter" and not text.strip():
            # Azure content filtering returns 200 with an empty completion.
            text = NO_ANSWER_MARKER
        usage = body.get("usage", {})
        return LLMResponse(
            text=text,
            model=body.get("model") or self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class AnthropicLLM(LLMClient):  # pragma: no cover - network
    """Official Anthropic SDK. Note: `temperature` is rejected by current Claude
    models, so LLM_TEMPERATURE is intentionally ignored here."""

    def __init__(self, api_key: str, model: str, max_tokens: int, timeout: float) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("LLM_PROVIDER=anthropic requires `pip install anthropic`") from exc
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires LLM_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.model = model if model.startswith("claude") else DEFAULT_ANTHROPIC_MODEL
        self._max_tokens = max_tokens

    def chat(self, system: str, messages: list[dict[str, str]]) -> LLMResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
        )
        if response.stop_reason == "refusal":
            return LLMResponse(text=NO_ANSWER_MARKER, model=self.model)
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "mistral":
        return MistralLLM(
            api_key=settings.llm_api_key or "",
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == "azure_openai":
        return AzureOpenAILLM(
            endpoint=settings.azure_openai_endpoint or "",
            deployment=settings.azure_openai_deployment or "",
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key,
            auth_mode=settings.azure_openai_auth,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            token_param=settings.azure_openai_token_param,
        )
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(
            api_key=settings.llm_api_key or "",
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
    return StubLLM()
