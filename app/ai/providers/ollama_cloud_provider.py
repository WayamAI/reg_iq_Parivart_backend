"""
Ollama Cloud provider.

Verified against https://docs.ollama.com/api/introduction and
https://docs.ollama.com/api/authentication (fetched 2026-10-03):

  - Base URL: https://ollama.com/api (the local Ollama API shares the same /api/chat
    shape; only the base URL and the addition of an Authorization header differ).
  - Auth: `Authorization: Bearer $OLLAMA_API_KEY` on every request. The docs are
    explicit that `x-api-key` alone is not accepted.
  - Endpoint: POST /api/chat, body `{"model": ..., "messages": [{"role", "content"}],
    "stream": false}`. The reply text is `response["message"]["content"]`.
  - No documented JSON error-body schema; errors surface as ordinary HTTP status codes
    (401/403 for bad credentials, 429 for rate limiting, 5xx for server errors), which is
    exactly what `httpx.Response.raise_for_status()` and the existing error classifier in
    app/services/ai_enrichment.classify_provider_error already distinguish.

Distinct from OllamaProvider (app/ai/providers/ollama_provider.py), which talks to a
*local* Ollama daemon's /api/generate endpoint and sends no credentials. This provider is
selected by setting AI_PROVIDER=ollama_cloud (see app/ai/startup.py for registration).
"""

import json
from typing import Any, Dict, Optional

import httpx
import structlog

from app.ai.base import AIProvider, parse_structured_output, structured_output_schema

logger = structlog.get_logger()

DEFAULT_BASE_URL = "https://ollama.com"
CHAT_PATH = "/api/chat"


class OllamaCloudAuthError(RuntimeError):
    """Raised when no API key is configured; never constructed with the key itself."""


class OllamaCloudProvider(AIProvider):
    """
    Ollama Cloud chat-completions provider.

    The HTTP client is created once and reused for the provider's lifetime (connection
    pooling), per the existing local-provider convention. Call `aclose()` on shutdown to
    release it cleanly.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 60.0,
    ):
        if not api_key:
            # Fails fast at construction, not on the first real request, and never
            # includes any part of a key (there isn't one) in the error.
            raise OllamaCloudAuthError(
                "OllamaCloudProvider requires an API key; none was configured."
            )
        if not model:
            raise ValueError(
                "OllamaCloudProvider requires a model name; none was configured."
            )

        self._model = model
        self._base_url = base_url.rstrip("/")
        # The key is held only as a private attribute, used solely to build the request
        # header below. It is never logged, never included in an exception message, and
        # never returned by health_status().
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds, read=read_timeout_seconds,
                write=connect_timeout_seconds, pool=connect_timeout_seconds,
            ),
        )

    @property
    def provider_name(self) -> str:
        return "ollama_cloud"

    @property
    def model_name(self) -> str:
        return self._model

    def health_status(self) -> Dict[str, Any]:
        """Never includes the API key -- only whether one is configured, implicitly
        true here since construction requires it."""
        return {
            "provider": self.provider_name,
            "model": self._model,
            "base_url": self._base_url,
            "credential_configured": True,
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    def _messages(self, prompt: str, system_prompt: Optional[str]) -> list:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _chat(self, messages: list, temperature: float = 0.1) -> str:
        """
        One request/response round trip. Raises the underlying httpx exception on
        failure -- callers are responsible for retry/backoff and for mapping the
        exception to a status (see app/services/ai_enrichment.classify_provider_error,
        which already distinguishes httpx.TimeoutException, httpx.HTTPStatusError by
        status code, and httpx.RequestError).
        """
        response = await self._client.post(
            CHAT_PATH,
            json={
                "model": self._model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        response.raise_for_status()
        body = response.json()
        content = (body.get("message") or {}).get("content")
        if not content:
            raise ValueError("Ollama Cloud returned an empty message content")
        return content

    async def generate_structured_output(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> Any:
        """
        Request JSON matching response_model's schema, then validate it.

        Unlike the bundled local providers (which swallow every attempt's exception and
        raise a fresh, generically-typed RuntimeError once retries are exhausted), this
        provider re-raises the LAST underlying exception on exhaustion, preserving its
        real type (httpx.TimeoutException, httpx.HTTPStatusError, etc.) for
        classify_provider_error to distinguish correctly, per this feature's requirement
        to preserve exception/status information the existing classifier depends on.
        """
        schema = structured_output_schema(response_model)
        json_instructions = (
            "You must respond with ONLY valid JSON conforming to this schema. "
            "No markdown, no commentary, no text outside the JSON.\n"
            f"{json.dumps(schema)}"
        )
        full_system_prompt = f"{system_prompt or ''}\n\n{json_instructions}".strip()
        messages = self._messages(prompt, full_system_prompt)

        last_error: Optional[BaseException] = None
        attempts = max(1, max_retries)
        for attempt in range(attempts):
            try:
                content = await self._chat(messages, temperature=temperature)
            except httpx.HTTPError as exc:
                logger.warning(
                    "ollama_cloud_request_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                last_error = exc
                continue

            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "ollama_cloud_json_parse_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                    # Bounded, and never the full document/content being analysed --
                    # only the model's own (short) reply, for debugging a bad response.
                    response=content[:500],
                )
                last_error = exc
                continue

            try:
                return parse_structured_output(response_model, data)
            except Exception as exc:
                logger.warning(
                    "ollama_cloud_validation_failed", attempt=attempt + 1, error=str(exc)
                )
                last_error = exc
                continue

        assert last_error is not None
        raise last_error

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        messages = self._messages(prompt, system_prompt)
        return await self._chat(messages, temperature=temperature)
