"""应用配置。"""

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_env_file_value(*keys: str) -> str:
    env_path = Path(".env")
    if not env_path.exists():
        return ""
    wanted = {key.lower() for key in keys}
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

    # Friendly aliases for local .env files.
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
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
        if self.deepseek_base_url:
            self.llm_base_url = self.deepseek_base_url
        if self.deepseek_model:
            self.llm_model = self.deepseek_model
        if self.llm_api_key:
            self.llm_enabled = True
        return self


settings = Settings()
