import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRES_IN: int = 3600
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    class Config:
        env_file = ".env"

settings = Settings()
