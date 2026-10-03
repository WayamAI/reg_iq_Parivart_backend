"""
Optional LIVE smoke test against the real Ollama Cloud service.

Skipped by default and in ordinary CI. It only runs when a developer explicitly opts in
by setting BOTH environment variables below -- conftest.py does not set either of them,
and this file does not import or depend on anything in conftest's auto-used fixtures
beyond what pytest provides for every test.

    OLLAMA_API_KEY=<a real key>
    RUN_OLLAMA_CLOUD_LIVE_SMOKE=1

    .venv/bin/python -m pytest app/tests/test_ollama_cloud_live_smoke.py -q

This file must never run as part of the ordinary test suite, and the key must never be
printed, asserted into a failure message, or written anywhere.
"""

import os

import pytest

from app.ai.providers.ollama_cloud_provider import OllamaCloudProvider

LIVE_KEY = os.environ.get("OLLAMA_API_KEY")
OPTED_IN = os.environ.get("RUN_OLLAMA_CLOUD_LIVE_SMOKE") == "1"
MODEL = os.environ.get("OLLAMA_CLOUD_MODEL", "gpt-oss:20b")

pytestmark = pytest.mark.skipif(
    not (LIVE_KEY and OPTED_IN),
    reason=(
        "Live Ollama Cloud smoke test skipped: set OLLAMA_API_KEY and "
        "RUN_OLLAMA_CLOUD_LIVE_SMOKE=1 to run it explicitly. Never runs in ordinary "
        "test/CI runs."
    ),
)


async def test_live_generate_text_round_trip():
    """
    Proves only that: a real API key authenticates, the configured model answers, and
    the provider returns plain text back out. It does not validate prompt quality,
    structured-output schema fidelity for a specific model, or latency/throughput.
    """
    provider = OllamaCloudProvider(api_key=LIVE_KEY, model=MODEL)
    try:
        text = await provider.generate_text(
            prompt="Reply with exactly the single word: pong",
            system_prompt="You are a terse test fixture. Reply with one word only.",
        )
        assert isinstance(text, str)
        assert len(text.strip()) > 0
    finally:
        await provider.aclose()
