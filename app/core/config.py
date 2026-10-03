from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRES_IN: int = 3600
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    # Additional browser origins allowed to call this API, comma-separated. The PARIVART
    # frontend dev server runs on :8080; Vite's default is :5173. Production origins are
    # supplied through the environment. Never "*": credentialed requests require an
    # explicit origin, and the browser rejects a wildcard alongside credentials anyway.
    CORS_ORIGINS: str = "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173"

    @property
    def cors_allow_origins(self) -> List[str]:
        """FRONTEND_ORIGIN plus CORS_ORIGINS, de-duplicated, order preserved."""
        candidates = [self.FRONTEND_ORIGIN, *self.CORS_ORIGINS.split(",")]
        seen: List[str] = []
        for origin in candidates:
            cleaned = origin.strip().rstrip("/")
            if cleaned and cleaned != "*" and cleaned not in seen:
                seen.append(cleaned)
        return seen

    # --- Optional AI enrichment -------------------------------------------------
    # PARIVART's Impact Assessment engine is fully deterministic. AI only ever adds a
    # narrative layer on top of an assessment that already exists, so it is off by
    # default and a provider outage can never block an assessment.
    AI_ENRICHMENT_ENABLED: bool = False
    AI_PROVIDER: str = "ollama"
    AI_MODEL: str = "llama3.1"
    AI_TIMEOUT_SECONDS: float = 20.0
    # Bounded on purpose: one attempt, no backoff loop, no retry storm after a 429.
    AI_MAX_ATTEMPTS: int = 1

    # --- Ollama Cloud provider ---------------------------------------------------
    # A distinct, optional provider from the local Ollama provider above. Selected by
    # setting AI_PROVIDER=ollama_cloud. Disabled by default and requires both an API key
    # and a model to actually register -- see app/ai/startup.py. Never logged, never
    # exposed in an API response: see OllamaCloudProvider.health_status().
    OLLAMA_CLOUD_ENABLED: bool = False
    OLLAMA_API_KEY: Optional[str] = None
    # https://docs.ollama.com/api/introduction: cloud inference is served from
    # https://ollama.com/api (the /api/chat path is appended by the provider).
    OLLAMA_CLOUD_BASE_URL: str = "https://ollama.com"
    OLLAMA_CLOUD_MODEL: Optional[str] = None
    OLLAMA_CLOUD_CONNECT_TIMEOUT_SECONDS: float = 10.0
    OLLAMA_CLOUD_READ_TIMEOUT_SECONDS: float = 60.0

    # --- Demo authentication ----------------------------------------------------
    # Accepts ANY email with ANY password, auto-provisioning the caller into the demo
    # organization. It exists so a demo is never blocked by a forgotten credential, and
    # it is an authentication bypass -- so it is off by default and double-gated below.
    DEMO_AUTH_ALLOW_ANY: bool = False

    @property
    def demo_auth_active(self) -> bool:
        """
        Both the flag and a development APP_ENV are required.

        The second condition is the one that matters: setting DEMO_AUTH_ALLOW_ANY=true in a
        production environment does nothing, so the bypass cannot travel with a config file
        into a deployment where it would be a vulnerability.
        """
        return self.DEMO_AUTH_ALLOW_ANY and self.APP_ENV == "development"

settings = Settings()
