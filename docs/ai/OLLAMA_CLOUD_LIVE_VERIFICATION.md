# Ollama Cloud — Live Verification Record

Date: 2026-10-03.

## What was run

```bash
OLLAMA_API_KEY=<redacted> OLLAMA_CLOUD_MODEL=gpt-oss:20b RUN_OLLAMA_CLOUD_LIVE_SMOKE=1 \
  .venv/bin/python -m pytest app/tests/test_ollama_cloud_live_smoke.py -v
```

Result: **`test_live_generate_text_round_trip` PASSED** (1 passed in 1.83s).

This exercised the real `OllamaCloudProvider` (`app/ai/providers/ollama_cloud_provider.py`) against the live `https://ollama.com/api/chat` endpoint with `Authorization: Bearer`, using the `gpt-oss:20b` model. The test asserts only that a response was returned and is non-empty plain text — it does not validate structured-output schema fidelity for this specific model, prompt quality, or latency under load.

## What this confirms

- The Bearer-auth + `/api/chat` request shape implemented this session is correct against the real service, not just plausible against documentation.
- A real API key, once configured, authenticates successfully.
- `generate_text` round-trips correctly end to end.

## What this does NOT confirm

- `generate_structured_output` (the JSON-schema-constrained path used by `AIService.analyze_document` and `ai_enrichment.enrich_assessment`) was not exercised live — only the mocked tests in `test_ollama_cloud_provider.py` (17 tests) cover that path. The live smoke test intentionally only proves the simpler `generate_text` path works, per its own module docstring.
- No AI-enrichment or document-analysis run against this model was performed live in this session.
- Startup registration against this specific key was not run — see the security note below for why this key should not be placed in this repository's own `.env` going forward.

## Security note on this key

This key was pasted directly into a chat conversation by the user, rather than configured directly in the backend's local `.env` as instructed. **A key that has appeared in chat/conversation history should be treated as exposed** and rotated in the Ollama account as a precaution, regardless of whether anything indicates actual misuse. This record intentionally does not reproduce the key value anywhere (not in this file, not in any command run, not in any log this session wrote to disk beyond the ephemeral shell environment variable used for the one pytest invocation above).

## Recommended next step for the project owner

1. Rotate the Ollama Cloud API key used above.
2. Add the new key directly to the local `.env` (never via chat) following `.env.example`'s `OLLAMA_CLOUD_*` template (added this session).
3. Set `AI_PROVIDER=ollama_cloud` and `OLLAMA_CLOUD_ENABLED=true` in the same file if Ollama Cloud should be the active provider going forward, rather than the default local `ollama` provider.
