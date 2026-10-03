"""
AI provider registration at application startup.

Before app/ai/startup.py existed, nothing ever called AIProviderFactory.register_provider
outside tests -- the registry was empty in every real run (see app/main.py, which now
calls register_configured_providers() on the FastAPI "startup" event). These tests call
the registration function directly rather than booting a real server, since the test
suite's ASGITransport-based client does not trigger ASGI lifespan events (confirmed: the
registry is empty before and after every other test in this suite, which would not be
true if startup fired implicitly).
"""

import pytest

from app.ai.base import AIProviderFactory
from app.ai.startup import register_configured_providers, shutdown_registered_providers
from app.core.config import settings


@pytest.fixture(autouse=True)
def _clean_registry():
    """Every test in this file starts and ends with an empty registry."""
    AIProviderFactory._providers.clear()
    yield
    AIProviderFactory._providers.clear()


def test_local_ollama_is_registered_by_default(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", False)

    register_configured_providers()

    assert "ollama" in AIProviderFactory._providers
    assert AIProviderFactory.get_provider("ollama").model_name == settings.AI_MODEL


def test_ollama_cloud_is_not_registered_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", False)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "a-key")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", "gpt-oss:20b")

    register_configured_providers()

    assert "ollama_cloud" not in AIProviderFactory._providers


def test_ollama_cloud_is_not_registered_without_an_api_key(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama_cloud")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", None)
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", "gpt-oss:20b")

    register_configured_providers()

    assert "ollama_cloud" not in AIProviderFactory._providers


def test_ollama_cloud_is_not_registered_without_a_model(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama_cloud")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "a-key")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", None)

    register_configured_providers()

    assert "ollama_cloud" not in AIProviderFactory._providers


def test_ollama_cloud_is_registered_when_fully_configured(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "a-key")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", "gpt-oss:20b")

    register_configured_providers()

    assert "ollama_cloud" in AIProviderFactory._providers
    provider = AIProviderFactory.get_provider("ollama_cloud")
    assert provider.model_name == "gpt-oss:20b"
    # The key itself must never be discoverable from the registered provider's
    # public status.
    assert "a-key" not in str(provider.health_status())


def test_registration_never_raises_on_bad_configuration(monkeypatch):
    """A startup-time registration failure must never crash the application."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "something-unregistered")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", None)
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", None)

    register_configured_providers()  # must not raise

    assert AIProviderFactory._providers == {}


async def test_shutdown_closes_every_registered_provider(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "a-key")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", "gpt-oss:20b")
    register_configured_providers()
    provider = AIProviderFactory.get_provider("ollama_cloud")

    await shutdown_registered_providers()

    assert provider._client.is_closed
