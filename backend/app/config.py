from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://loopforge:loopforge@localhost:5432/loopforge"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    refresh_expire_days: int = 14
    openai_api_key: str = ""
    openai_model: str = ""
    max_iterations: int = 5
    max_execution_seconds: int = 120
    max_task_duration_seconds: int = 900
    max_token_budget: int = 30000
    environment: str = "development"
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> Self:
        if self.environment == "production" and (
            self.jwt_secret == "change-me" or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a random value (>=32 chars) in production")
        return self


settings = Settings()
