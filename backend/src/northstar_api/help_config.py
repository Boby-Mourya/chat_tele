from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HelpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    help_content_sync_on_startup: bool = True
    help_search_page_size_max: int = Field(default=50, ge=5, le=100)
    help_search_candidate_limit: int = Field(default=40, ge=5, le=200)
    help_ai_rate_limit_per_minute: int = Field(default=12, ge=1, le=1000)
    help_ai_min_score: float = Field(default=0.12, ge=0, le=1)


@lru_cache(maxsize=1)
def get_help_settings() -> HelpSettings:
    return HelpSettings()
