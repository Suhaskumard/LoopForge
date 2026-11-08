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
    # Phase 9 model routing (ADR-0016): empty = use OPENAI_MODEL.
    # Typical: a cheap model for Planner/Documentation, a stronger one for Repair/Reviewer.
    model_planner: str = ""
    model_builder: str = ""
    model_repair: str = ""
    model_reviewer: str = ""
    model_documentation: str = ""
    max_iterations: int = 5
    max_execution_seconds: int = 120
    max_task_duration_seconds: int = 900
    max_attempts_per_failure: int = 2
    resume_on_startup: bool = False
    max_token_budget: int = 30000
    documentation_agent_enabled: bool = True  # README generation after a terminal state
    approval_max_repair_files: int = 5  # larger repairs wait for a human
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_max_retries: int = 3
    llm_backoff_base_seconds: float = 1.0
    llm_backoff_max_seconds: float = 20.0
    llm_timeout_seconds: float = 60.0
    workspace_root: str = "./workspaces"
    sandbox_backend: Literal["docker", "fake"] = "docker"
    sandbox_image: str = "loopforge-sandbox"
    sandbox_image_js: str = "loopforge-sandbox-node"
    sandbox_memory_mb: int = 256
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 64
    sandbox_max_output_bytes: int = 200_000
    environment: str = "development"
    login_max_attempts: int = 5
    login_window_seconds: int = 300
    # Phase 5
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ws_poll_seconds: float = 1.0
    ws_max_connections_per_user: int = 10
    # Estimated blended price per 1k tokens (USD). There is no billing data: cost is tokens x rate.
    cost_per_1k_tokens: float = 0.002
    # Phase 8: repository import (untrusted input limits, ADR-0015)
    repo_max_archive_bytes: int = 20_000_000
    repo_max_files: int = 2000
    repo_max_file_bytes: int = 500_000
    repo_max_total_bytes: int = 20_000_000
    repo_max_depth: int = 12
    repo_git_timeout_seconds: int = 60
    repo_git_allowed_hosts: str = ""  # comma list; empty = any public https host
    # Phase 7: scale-out. inline = FastAPI background task (default); queue = jobs table + worker.
    run_mode: Literal["inline", "queue"] = "inline"
    lease_ttl_seconds: float = 30.0
    worker_poll_seconds: float = 1.0
    # Number of reverse proxies in front of the API whose X-Forwarded-For entry is trusted.
    trusted_proxy_count: int = 0

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

    def model_for(self, agent: str) -> str | None:
        """Model override for an agent name (Planner, Builder, Repair, Reviewer, Documentation)."""
        override = getattr(self, f"model_{agent.lower()}", "")
        return override or None


settings = Settings()
