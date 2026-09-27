from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()

class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    async def generate_structured_output(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> BaseModel:
        """
        Generate a structured output from the AI model.
        Returns an instance of the response_model.
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