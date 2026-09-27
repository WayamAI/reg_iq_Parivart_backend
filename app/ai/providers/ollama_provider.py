import json
import httpx
from typing import Optional, Type
from pydantic import BaseModel
from app.ai.base import AIProvider
import structlog

logger = structlog.get_logger()

class OllamaProvider(AIProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=120.0)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self.model

    async def generate_structured_output(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> BaseModel:
        """Generate structured output using Ollama with JSON schema."""

        # Get JSON schema from the Pydantic model
        schema = response_model.model_json_schema()

        # Construct the system prompt with JSON schema instructions
        json_instructions = f"""
You are a precise data extraction system. You MUST output ONLY valid JSON that conforms to the following schema:
{json.dumps(schema, indent=2)}

Do not include any explanation, markdown, or text outside the JSON object.
"""

        full_system_prompt = (system_prompt or "") + "\n\n" + json_instructions

        last_error = None
        for attempt in range(max_retries):
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "system": full_system_prompt,
                        "temperature": temperature,
                        "stream": False,
                        "format": "json",
                    }
                )
                response.raise_for_status()
                result = response.json()

                # Parse the JSON response
                response_text = result.get("response", "")
                if not response_text:
                    raise ValueError("Empty response from Ollama")

                # Try to parse as JSON
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.warning("ollama_json_parse_failed", attempt=attempt + 1, error=str(e), response=response_text[:500])
                    last_error = e
                    continue

                # Validate against the Pydantic model
                try:
                    return response_model(**data)
                except Exception as e:
                    logger.warning("ollama_validation_failed", attempt=attempt + 1, error=str(e))
                    last_error = e
                    continue

            except httpx.RequestError as e:
                logger.warning("ollama_request_failed", attempt=attempt + 1, error=str(e))
                last_error = e
                continue
            except Exception as e:
                logger.warning("ollama_generation_failed", attempt=attempt + 1, error=str(e))
                last_error = e
                continue

        # If all retries failed
        raise RuntimeError(f"Failed to generate structured output after {max_retries} attempts: {last_error}")

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        """Generate plain text from Ollama."""
        try:
            response = await self._client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system_prompt,
                    "temperature": temperature,
                    "stream": False,
                }
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "")
        except Exception as e:
            logger.error("ollama_text_generation_failed", error=str(e))
            raise

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()