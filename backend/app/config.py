from typing import Literal, Self

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
    max_attempts_per_failure: int = 2
    resume_on_startup: bool = False
    max_token_budget: int = 30000
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_max_retries: int = 3
    llm_backoff_base_seconds: float = 1.0
    llm_backoff_max_seconds: float = 20.0
    llm_timeout_seconds: float = 60.0
    workspace_root: str = "./workspaces"
    sandbox_backend: Literal["docker", "fake"] = "docker"
    sandbox_image: str = "loopforge-sandbox"
    sandbox_memory_mb: int = 256
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 64
    sandbox_max_output_bytes: int = 200_000
    environment: str = "development"
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> Self:
        if self.environment == "production" and (
            self.jwt_secret == "change-me" or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a random value (>=32 chars) in production")
        if self.environment == "production" and self.llm_provider == "fake":
            raise ValueError("LLM_PROVIDER=fake is not allowed in production")
        if self.environment == "production" and self.sandbox_backend == "fake":
            raise ValueError("SANDBOX_BACKEND=fake is not allowed in production")
        return self


settings = Settings()
