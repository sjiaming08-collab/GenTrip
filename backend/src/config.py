"""应用配置。"""

from pathlib import Path
import os
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV_FILE = PROJECT_ROOT / ".env"


def _read_env_file_value(*keys: str) -> str:
    wanted = {key.lower() for key in keys}
    for env_path in (Path(".env"), ROOT_ENV_FILE):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().lower() in wanted:
                return value.strip().strip('"').strip("'")
    return ""


class Settings(BaseSettings):
    app_name: str = "GenTrip"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]

    # DeepSeek / OpenAI 兼容 LLM
    llm_enabled: bool = False
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-pro"
    llm_timeout_sec: float = 30.0
    constraint_extract_mode: Literal["rule_only", "llm_with_fallback", "llm_only"] = "llm_with_fallback"

    # Runtime state. Leave both URLs empty for isolated unit tests only.
    database_url: str = ""
    redis_url: str = ""
    runtime_event_retention_hours: int = 24
    runtime_session_lock_seconds: int = 90
    runtime_session_cache_ttl_seconds: int = 86400
    route_bundle_cache_ttl_seconds: int = 1800
    route_bundle_min_match_score: float = 0.85
    tenant_api_keys_json: str = ""
    allow_insecure_tenant_id: bool = True
    auth_enabled: bool = False
    auth_jwt_secret: str = ""
    auth_access_token_minutes: int = 60
    auth_cookie_secure: bool = False
    auth_allow_registration: bool = True
    auth_login_rate_limit_enabled: bool = False
    auth_login_max_attempts: int = 5
    auth_login_window_seconds: int = 900
    runtime_execution_mode: Literal["inprocess", "redis_stream"] = "inprocess"
    runtime_queue_stream: str = "gentrip:plan-runs"
    runtime_queue_group: str = "gentrip-plan-workers"
    runtime_queue_claim_idle_ms: int = 60000
    runtime_queue_max_attempts: int = 3
    runtime_queue_dead_letter_stream: str = "gentrip:plan-runs:dlq"
    otel_service_name: str = "gentrip-api"
    otel_exporter_otlp_traces_endpoint: str = ""
    travel_time_provider: Literal["mock", "http"] = "mock"
    travel_time_http_url: str = ""
    travel_time_timeout_sec: float = 2.0

    # Friendly aliases for local .env files.
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def apply_deepseek_aliases(self) -> "Settings":
        if not self.llm_api_key and self.deepseek_api_key:
            self.llm_api_key = self.deepseek_api_key
        if not self.llm_api_key:
            self.llm_api_key = _read_env_file_value(
                "DEEPSEEK_API_KEY",
                "LLM_API_KEY",
                "DEEPSEEK_V4_PRO_API_KEY",
                "deepseek-v4-pro",
            )
        if not self.llm_api_key:
            # Keep compatibility with the original local .env key while the
            # Compose service injects that file into the container.
            self.llm_api_key = os.getenv("deepseek-v4-pro", "")
        if self.deepseek_base_url:
            self.llm_base_url = self.deepseek_base_url
        if self.deepseek_model:
            self.llm_model = self.deepseek_model
        if self.llm_api_key:
            self.llm_enabled = True
        if self.auth_enabled and len(self.auth_jwt_secret) < 32:
            raise ValueError("AUTH_JWT_SECRET must be at least 32 characters when AUTH_ENABLED=true")
        return self


settings = Settings()
