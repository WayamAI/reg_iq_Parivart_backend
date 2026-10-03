from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, TypeAdapter
import structlog

logger = structlog.get_logger()


def structured_output_schema(response_model: Any) -> dict:
    """
    JSON schema for a structured-output target that may be a BaseModel subclass OR a
    generic type such as ``list[ExtractedChange]``.

    ``response_model.model_json_schema()`` only exists on BaseModel subclasses; a bare
    generic alias like ``list[X]`` has no such method, so callers used to crash before
    ever reaching the provider (or, in practice, the provider's "any exception during
    prompting" catch swallowed it and no schema was ever sent to the model at all).
    ``TypeAdapter`` builds a schema for either shape.
    """
    return TypeAdapter(response_model).json_schema()


def parse_structured_output(response_model: Any, data: Any) -> Any:
    """
    Validate a provider's parsed JSON payload against a structured-output target.

    ``response_model(**data)`` only works when ``response_model`` is a BaseModel
    subclass and ``data`` is a mapping. For a generic target such as
    ``list[ExtractedChange]`` it raises ``TypeError`` immediately, because ``list``
    does not accept keyword expansion -- so every AI-assisted extraction that asked
    for a list of items was guaranteed to fail validation, silently, every time.
    ``TypeAdapter.validate_python`` validates either shape correctly.
    """
    return TypeAdapter(response_model).validate_python(data)


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    async def generate_structured_output(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> Any:
        """
        Generate a structured output from the AI model.

        ``response_model`` may be a ``BaseModel`` subclass or a generic type such as
        ``list[SomeModel]``; implementations should validate the parsed response with
        ``parse_structured_output`` (or an equivalent ``TypeAdapter``) rather than
        calling ``response_model(**data)`` directly, which only works for the first
        case. Returns a validated instance of ``response_model``.
        """
        pass

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        """Generate plain text from the AI model."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of the provider (e.g., 'ollama', 'openai')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name being used."""
        pass

    async def aclose(self) -> None:
        """
        Release any held resources (e.g. a pooled HTTP client).

        Default no-op so existing providers that hold nothing closeable remain valid
        without change. A provider that owns a client should override this.
        """
        return None

    def health_status(self) -> Dict[str, Any]:
        """
        Non-secret status info suitable for an operator-facing endpoint (e.g. /status).

        Must never include an API key, token, or other credential. Default implementation
        exposes only the provider and model name; a provider with more to report (e.g.
        whether its credential is configured, without revealing it) should override this.
        """
        return {"provider": self.provider_name, "model": self.model_name}


class AIProviderFactory:
    """Factory for creating AI provider instances."""

    _providers: Dict[str, AIProvider] = {}

    @classmethod
    def register_provider(cls, provider: AIProvider):
        cls._providers[provider.provider_name] = provider

    @classmethod
    def get_provider(cls, name: str) -> AIProvider:
        if name not in cls._providers:
            raise ValueError(f"Provider '{name}' not registered. Available: {list(cls._providers.keys())}")
        return cls._providers[name]

    @classmethod
    def get_default_provider(cls) -> AIProvider:
        # Return the first registered provider as default
        if not cls._providers:
            raise ValueError("No AI providers registered")
        return list(cls._providers.values())[0]