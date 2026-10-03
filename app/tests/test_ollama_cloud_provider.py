"""
OllamaCloudProvider: fully mocked, no network access and no live API key required.

Covers construction/validation, the request shape sent to /api/chat, authentication
header, structured-output parsing, and every failure mode the existing AI-enrichment
error classifier (app/services/ai_enrichment.classify_provider_error) distinguishes:
timeout, rate limit, auth error, server error, connection failure, and a malformed/empty
response. A live smoke test against the real Ollama Cloud service is intentionally NOT
included here -- see app/tests/test_ollama_cloud_live_smoke.py, which skips unless a real
API key is explicitly provided and the developer opts in.
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.ai.base import AIProviderFactory
from app.ai.providers.ollama_cloud_provider import OllamaCloudAuthError, OllamaCloudProvider


class Narrative(BaseModel):
    narrative: str


def _provider(handler, **kwargs) -> OllamaCloudProvider:
    provider = OllamaCloudProvider(api_key="test-key", model="gpt-oss:20b", **kwargs)
    provider._client = httpx.AsyncClient(
        base_url=provider._base_url,
        headers=provider._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return provider


# --- construction / validation -----------------------------------------------------


def test_requires_an_api_key():
    with pytest.raises(OllamaCloudAuthError):
        OllamaCloudProvider(api_key="", model="gpt-oss:20b")


def test_requires_a_model():
    with pytest.raises(ValueError):
        OllamaCloudProvider(api_key="test-key", model="")


def test_health_status_never_includes_the_api_key():
    provider = OllamaCloudProvider(api_key="super-secret-value", model="gpt-oss:20b")
    status = provider.health_status()

    assert "super-secret-value" not in json.dumps(status)
    assert status["provider"] == "ollama_cloud"
    assert status["model"] == "gpt-oss:20b"
    assert status["credential_configured"] is True


# --- request shape -------------------------------------------------------------------


async def test_sends_bearer_auth_header_and_chat_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": '{"narrative": "ok"}'}}
        )

    provider = _provider(handler)
    result = await provider.generate_structured_output(
        prompt="Summarise this.", response_model=Narrative, system_prompt="Be terse."
    )

    assert captured["url"].endswith("/api/chat")
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == "gpt-oss:20b"
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"][-1]["content"] == "Summarise this."
    assert isinstance(result, Narrative)
    assert result.narrative == "ok"


async def test_never_logs_or_leaks_the_api_key_in_an_error(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    provider = _provider(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )

    assert "test-key" not in caplog.text


# --- failure modes, mapped by the existing classifier --------------------------------


async def test_timeout_raises_the_original_exception_type():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _provider(handler)

    with pytest.raises(httpx.ReadTimeout):
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )


async def test_connection_failure_raises_the_original_exception_type():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(handler)

    with pytest.raises(httpx.ConnectError):
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )


async def test_rate_limit_raises_http_status_error_with_status_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"}, json={"error": "rate limited"})

    provider = _provider(handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )
    assert exc_info.value.response.status_code == 429


async def test_auth_error_raises_http_status_error_with_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    provider = _provider(handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )
    assert exc_info.value.response.status_code == 401


async def test_server_error_raises_http_status_error_with_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "server error"})

    provider = _provider(handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )
    assert exc_info.value.response.status_code == 503


async def test_malformed_json_raises_json_decode_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "not json at all"}}
        )

    provider = _provider(handler)

    with pytest.raises(json.JSONDecodeError):
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )


async def test_empty_message_content_raises_value_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": ""}})

    provider = _provider(handler)

    with pytest.raises(ValueError):
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=1
        )


async def test_retries_then_succeeds_within_max_retries():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            return httpx.Response(503, json={"error": "transient"})
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": '{"narrative": "ok"}'}}
        )

    provider = _provider(handler)
    result = await provider.generate_structured_output(
        prompt="x", response_model=Narrative, max_retries=3
    )

    assert calls["count"] == 2
    assert result.narrative == "ok"


async def test_does_not_retry_beyond_max_retries():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, json={"error": "down"})

    provider = _provider(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await provider.generate_structured_output(
            prompt="x", response_model=Narrative, max_retries=2
        )

    assert calls["count"] == 2


# --- generate_text ---------------------------------------------------------------------


async def test_generate_text_returns_message_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "plain text reply"}}
        )

    provider = _provider(handler)
    text = await provider.generate_text("hello")

    assert text == "plain text reply"


# --- lifecycle --------------------------------------------------------------------------


async def test_aclose_releases_the_http_client():
    provider = OllamaCloudProvider(api_key="test-key", model="gpt-oss:20b")
    await provider.aclose()
    assert provider._client.is_closed


# --- registry integration ---------------------------------------------------------------


def test_registers_under_ollama_cloud_name():
    provider = OllamaCloudProvider(api_key="test-key", model="gpt-oss:20b")
    try:
        AIProviderFactory.register_provider(provider)
        assert AIProviderFactory.get_provider("ollama_cloud") is provider
    finally:
        AIProviderFactory._providers.pop("ollama_cloud", None)
