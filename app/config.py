from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5433/label_check"
    vision_provider: Literal["gemini", "groq"] = "gemini"
    # Empty = no fallback. Groq as the fallback takes only requests of <= 3 photos.
    vision_fallback_provider: Literal["", "gemini", "groq"] = ""
    gemini_api_key: str = ""
    vision_model: str = "gemini-3.5-flash-lite"
    groq_api_key: str = ""
    groq_vision_model: str = "qwen/qwen3.8-27b"
    vision_timeout_seconds: float = 30.0  # one HTTP attempt
    vision_deadline_seconds: float = 90.0  # the whole extraction: retries, fallback, re-ask
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def check_fallback(self) -> "Settings":
        if self.vision_fallback_provider == self.vision_provider:
            raise ValueError(
                "VISION_FALLBACK_PROVIDER must differ from VISION_PROVIDER (or be empty)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
