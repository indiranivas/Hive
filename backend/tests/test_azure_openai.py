"""Azure OpenAI provider tests.

No live calls: an httpx MockTransport captures the request so the wire format
itself is asserted -- the deployment-path URL, the api-version query parameter,
the auth header, and the token-parameter switch. Those are exactly the things
that fail with a 404 or 400 against a real resource.
"""

from __future__ import annotations

import json

import httpx
import pytest

from api.core.azure_auth import build_auth_headers
from api.core.embeddings import AzureOpenAIEmbedder
from api.core.llm import NO_ANSWER_MARKER, AzureOpenAILLM

ENDPOINT = "https://levelshift-openai.openai.azure.com"
CHAT_BODY = {
    "model": "gpt-4o-2024-11-20",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Deepa V fixed it in PR #312."},
        }
    ],
    "usage": {"prompt_tokens": 812, "completion_tokens": 24},
}


def _client(capture: list[httpx.Request], body: dict, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _llm(capture: list[httpx.Request], *, body: dict | None = None, status: int = 200,
         deployment: str = "hive-gpt4o", **kwargs) -> AzureOpenAILLM:
    return AzureOpenAILLM(
        endpoint=ENDPOINT,
        deployment=deployment,
        api_version="2024-10-21",
        api_key="secret-key",
        client=_client(capture, body if body is not None else CHAT_BODY, status),
        **kwargs,
    )


# --- auth --------------------------------------------------------------------


def test_key_auth_uses_the_api_key_header():
    assert build_auth_headers("key", "abc123") == {"api-key": "abc123"}


def test_entra_auth_uses_a_bearer_token():
    headers = build_auth_headers("entra", None, token_provider=lambda: "token-xyz")
    assert headers == {"Authorization": "Bearer token-xyz"}


def test_key_auth_without_a_key_explains_both_options():
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_API_KEY"):
        build_auth_headers("key", None)


# --- chat --------------------------------------------------------------------


def test_chat_targets_the_deployment_path_with_api_version():
    capture: list[httpx.Request] = []
    _llm(capture).chat("system prompt", [{"role": "user", "content": "who fixed billing?"}])

    request = capture[0]
    assert request.method == "POST"
    assert request.url.path == "/openai/deployments/hive-gpt4o/chat/completions"
    assert request.url.params["api-version"] == "2024-10-21"
    assert request.headers["api-key"] == "secret-key"
    # The deployment carries the model; Azure rejects a `model` field here.
    assert "model" not in json.loads(request.content)


def test_chat_sends_system_prompt_first():
    capture: list[httpx.Request] = []
    _llm(capture).chat("you are Hive", [{"role": "user", "content": "hello"}])

    messages = json.loads(capture[0].content)["messages"]
    assert messages[0] == {"role": "system", "content": "you are Hive"}
    assert messages[1] == {"role": "user", "content": "hello"}


def test_chat_parses_text_and_usage():
    capture: list[httpx.Request] = []
    response = _llm(capture).chat("s", [{"role": "user", "content": "q"}])

    assert response.text == "Deepa V fixed it in PR #312."
    assert response.model == "gpt-4o-2024-11-20"
    assert response.input_tokens == 812
    assert response.output_tokens == 24


def test_standard_deployment_sends_max_tokens_and_temperature():
    capture: list[httpx.Request] = []
    _llm(capture, max_tokens=1234, temperature=0.2).chat("s", [{"role": "user", "content": "q"}])

    payload = json.loads(capture[0].content)
    assert payload["max_tokens"] == 1234
    assert payload["temperature"] == 0.2
    assert "max_completion_tokens" not in payload


def test_reasoning_deployment_switches_token_param_and_drops_temperature():
    """o-series and gpt-5 deployments 400 on max_tokens and on any temperature."""
    for deployment in ("o3-mini-hive", "gpt-5-hive", "O1-Preview"):
        capture: list[httpx.Request] = []
        _llm(capture, deployment=deployment, max_tokens=999).chat(
            "s", [{"role": "user", "content": "q"}]
        )
        payload = json.loads(capture[0].content)
        assert payload["max_completion_tokens"] == 999, deployment
        assert "max_tokens" not in payload, deployment
        assert "temperature" not in payload, deployment


def test_token_param_can_be_forced():
    capture: list[httpx.Request] = []
    _llm(capture, token_param="max_completion_tokens").chat(
        "s", [{"role": "user", "content": "q"}]
    )
    assert "max_completion_tokens" in json.loads(capture[0].content)


def test_content_filtered_response_falls_back_to_the_gap_answer():
    """Azure returns 200 with an empty completion when a filter trips."""
    filtered = {
        "choices": [{"finish_reason": "content_filter", "message": {"content": ""}}],
        "usage": {},
    }
    capture: list[httpx.Request] = []
    response = _llm(capture, body=filtered).chat("s", [{"role": "user", "content": "q"}])
    assert response.text == NO_ANSWER_MARKER


def test_http_errors_propagate():
    capture: list[httpx.Request] = []
    client = _llm(capture, body={"error": {"message": "deployment not found"}}, status=404)
    with pytest.raises(httpx.HTTPStatusError):
        client.chat("s", [{"role": "user", "content": "q"}])


def test_endpoint_trailing_slash_does_not_double_up():
    capture: list[httpx.Request] = []
    AzureOpenAILLM(
        endpoint=ENDPOINT + "/",
        deployment="d",
        api_version="2024-10-21",
        api_key="k",
        client=_client(capture, CHAT_BODY),
    ).chat("s", [{"role": "user", "content": "q"}])
    assert "//openai" not in str(capture[0].url)


def test_missing_endpoint_or_deployment_fails_with_the_env_var_name():
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAILLM(endpoint="", deployment="d", api_version="v")
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_DEPLOYMENT"):
        AzureOpenAILLM(endpoint=ENDPOINT, deployment="", api_version="v")


# --- embeddings --------------------------------------------------------------


def _embed_body(count: int, dim: int = 4) -> dict:
    return {
        "data": [
            {"index": index, "embedding": [float(index)] * dim} for index in range(count)
        ],
        "usage": {"prompt_tokens": 10},
    }


def test_embedder_targets_the_embedding_deployment():
    capture: list[httpx.Request] = []
    embedder = AzureOpenAIEmbedder(
        endpoint=ENDPOINT,
        deployment="hive-embed-3-small",
        api_version="2024-10-21",
        api_key="secret-key",
        dim=4,
        client=_client(capture, _embed_body(2)),
    )
    vectors = embedder.encode(["one", "two"])

    assert capture[0].url.path == "/openai/deployments/hive-embed-3-small/embeddings"
    assert json.loads(capture[0].content)["input"] == ["one", "two"]
    assert vectors == [[0.0] * 4, [1.0] * 4]


def test_embedder_sends_dimensions_only_when_asked():
    capture: list[httpx.Request] = []
    AzureOpenAIEmbedder(
        endpoint=ENDPOINT, deployment="d", api_version="v", api_key="k", dim=256,
        send_dimensions=True, client=_client(capture, _embed_body(1, dim=256)),
    ).encode(["x"])
    assert json.loads(capture[0].content)["dimensions"] == 256

    capture.clear()
    AzureOpenAIEmbedder(
        endpoint=ENDPOINT, deployment="d", api_version="v", api_key="k", dim=256,
        client=_client(capture, _embed_body(1, dim=256)),
    ).encode(["x"])
    assert "dimensions" not in json.loads(capture[0].content)


def test_embedder_batches_large_inputs():
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        count = len(json.loads(request.content)["input"])
        return httpx.Response(200, json=_embed_body(count))

    embedder = AzureOpenAIEmbedder(
        endpoint=ENDPOINT, deployment="d", api_version="v", api_key="k", dim=4,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    vectors = embedder.encode([f"chunk {index}" for index in range(37)])

    assert len(capture) == 3  # 16 + 16 + 5
    assert len(vectors) == 37


def test_embedder_reorders_by_index():
    """Azure may return embeddings out of order; alignment with chunks matters."""
    scrambled = {
        "data": [
            {"index": 1, "embedding": [1.0]},
            {"index": 0, "embedding": [0.0]},
        ]
    }
    capture: list[httpx.Request] = []
    vectors = AzureOpenAIEmbedder(
        endpoint=ENDPOINT, deployment="d", api_version="v", api_key="k", dim=1,
        client=_client(capture, scrambled),
    ).encode(["first", "second"])
    assert vectors == [[0.0], [1.0]]


def test_embedder_no_texts_makes_no_request():
    capture: list[httpx.Request] = []
    embedder = AzureOpenAIEmbedder(
        endpoint=ENDPOINT, deployment="d", api_version="v", api_key="k",
        client=_client(capture, _embed_body(0)),
    )
    assert embedder.encode([]) == []
    assert capture == []


# --- wiring ------------------------------------------------------------------


def test_settings_select_the_azure_providers(monkeypatch, tmp_path):
    from api.core import config, embeddings, llm

    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "hive-gpt4o")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "hive-embed")
    monkeypatch.setenv("EMBEDDING_DIM", "1536")
    for cached in (config.get_settings, llm.get_llm, embeddings.get_embedder):
        cached.cache_clear()

    try:
        client = llm.get_llm()
        embedder = embeddings.get_embedder()
        assert isinstance(client, llm.AzureOpenAILLM)
        assert client.model == "hive-gpt4o"
        assert client.url.endswith(
            "/openai/deployments/hive-gpt4o/chat/completions?api-version=2024-10-21"
        )
        assert isinstance(embedder, embeddings.AzureOpenAIEmbedder)
        assert embedder.dim == 1536
    finally:
        for cached in (config.get_settings, llm.get_llm, embeddings.get_embedder):
            cached.cache_clear()
