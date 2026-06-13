"""应用配置。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GenTrip"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
