"""
AI provider registration at application startup.

Before this module existed, AIProviderFactory._providers was never populated outside
tests: nothing in app/main.py (or anywhere else) ever called register_provider. The
registry was empty in every real run, so settings.AI_PROVIDER was never resolvable and
`/status`'s provider_registered field was always false, and any attempt at AI enrichment
or document analysis always failed closed with "no provider available" -- correctly
handled, but a configured provider could never actually run.

This module registers whichever provider(s) are safely constructible from current
configuration. It never raises: a misconfigured or disabled provider is logged and
skipped, not a startup failure, because AI is optional everywhere it is used in this
codebase (see app/matching/engine.py and app/services/ai_enrichment.py).
"""

import structlog

from app.ai.base import AIProvider, AIProviderFactory
from app.ai.providers.ollama_cloud_provider import OllamaCloudAuthError, OllamaCloudProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.core.config import settings

logger = structlog.get_logger()


def _build_local_ollama() -> AIProvider:
    return OllamaProvider(model=settings.AI_MODEL)


def _build_ollama_cloud() -> AIProvider:
    return OllamaCloudProvider(
        api_key=settings.OLLAMA_API_KEY or "",
        model=settings.OLLAMA_CLOUD_MODEL or "",
        base_url=settings.OLLAMA_CLOUD_BASE_URL,
        connect_timeout_seconds=settings.OLLAMA_CLOUD_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=settings.OLLAMA_CLOUD_READ_TIMEOUT_SECONDS,
    )


def register_configured_providers() -> None:
    """
    Register every provider that is safely constructible right now.

    Local Ollama needs no credential, so it is registered whenever it is the
    configured default provider (AI_PROVIDER == "ollama", itself the default), even
    though nothing guarantees a local Ollama daemon is actually reachable -- that is a
    call-time concern (connection errors), not a registration-time one.

    Ollama Cloud is registered only when explicitly enabled AND both an API key and a
    model are configured. Neither the key nor any part of it is ever logged.
    """
    if settings.AI_PROVIDER == "ollama":
        try:
            AIProviderFactory.register_provider(_build_local_ollama())
            logger.info(
                "ai_provider_registered", provider="ollama", model=settings.AI_MODEL
            )
        except Exception as exc:  # pragma: no cover - construction has no failure mode today
            logger.warning("ai_provider_registration_failed", provider="ollama", error=str(exc))

    if settings.OLLAMA_CLOUD_ENABLED:
        if not settings.OLLAMA_API_KEY or not settings.OLLAMA_CLOUD_MODEL:
            logger.warning(
                "ollama_cloud_not_registered_missing_config",
                api_key_configured=bool(settings.OLLAMA_API_KEY),
                model_configured=bool(settings.OLLAMA_CLOUD_MODEL),
            )
        else:
            try:
                AIProviderFactory.register_provider(_build_ollama_cloud())
                logger.info(
                    "ai_provider_registered",
                    provider="ollama_cloud",
                    model=settings.OLLAMA_CLOUD_MODEL,
                    base_url=settings.OLLAMA_CLOUD_BASE_URL,
                )
            except OllamaCloudAuthError as exc:
                logger.warning(
                    "ollama_cloud_registration_failed", error=str(exc)
                )


async def shutdown_registered_providers() -> None:
    """Release any resources held by registered providers (e.g. pooled HTTP clients)."""
    for provider in list(AIProviderFactory._providers.values()):
        try:
            await provider.aclose()
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            logger.warning(
                "ai_provider_shutdown_failed", provider=provider.provider_name, error=str(exc)
            )
