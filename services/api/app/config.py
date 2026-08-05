from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_prefix="CONTENT_AGENT_",
        extra="ignore",
    )

    provider: str = "auto"
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/content-agent.db"
    web_origin: str = "http://127.0.0.1:3000"
    text_model: str = "gpt-5.6-terra"
    image_model: str = "gpt-image-2"
    speech_model: str = "tts-1-hd"
    speech_voice: str = "alloy"
    project_budget_usd: float = Field(default=5.0, gt=0)
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    max_primary_bytes: int = 150 * 1024 * 1024
    max_primary_chars: int = 1_500_000
    max_supplement_chars: int = 100_000
    max_supplements: int = 5
    max_ai_images: int = 12

    @property
    def resolved_provider(self) -> str:
        if self.provider == "auto":
            return "openai" if self.openai_api_key else "mock"
        return self.provider

    def ensure_directories(self) -> None:
        for name in ("uploads", "projects", "tmp"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
