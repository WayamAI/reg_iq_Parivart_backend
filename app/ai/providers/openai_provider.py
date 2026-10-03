import json
from typing import Any, Optional
from pydantic import BaseModel
from openai import AsyncOpenAI
from app.ai.base import AIProvider, parse_structured_output, structured_output_schema
import structlog

logger = structlog.get_logger()

class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: Optional[str] = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self.model

    async def generate_structured_output(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> Any:
        """Generate structured output using OpenAI with JSON schema."""

        # Get JSON schema for the target type (a BaseModel subclass or a generic type
        # such as list[SomeModel]; see app.ai.base.structured_output_schema).
        schema = structured_output_schema(response_model)

        # Construct the system prompt
        full_system_prompt = (system_prompt or "") + f"""

You must output ONLY valid JSON that conforms to this schema:
{json.dumps(schema, indent=2)}

Do not include any explanation, markdown, or text outside the JSON object.
"""

        last_error = None
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": full_system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )

                response_text = response.choices[0].message.content
                if not response_text:
                    raise ValueError("Empty response from OpenAI")

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.warning("openai_json_parse_failed", attempt=attempt + 1, error=str(e), response=response_text[:500])
                    last_error = e
                    continue

                try:
                    return parse_structured_output(response_model, data)
                except Exception as e:
                    logger.warning("openai_validation_failed", attempt=attempt + 1, error=str(e))
                    last_error = e
                    continue

            except Exception as e:
                logger.warning("openai_generation_failed", attempt=attempt + 1, error=str(e))
                last_error = e
                continue

        raise RuntimeError(f"Failed to generate structured output after {max_retries} attempts: {last_error}")

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        """Generate plain text from OpenAI."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt or ""},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("openai_text_generation_failed", error=str(e))
            raise

    async def close(self):
        """Close the OpenAI client."""
        await self.client.close()