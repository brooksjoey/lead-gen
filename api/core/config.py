from __future__ import annotations

from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    environment: str = Field('development')
    api_host: str = Field('0.0.0.0')
    api_port: int = Field(8000)
    database_url: str = Field('postgresql+asyncpg://leadgen:leadgen_secure@postgres:5432/leadgen')
    redis_url: str = Field('redis://redis:6379/0')
    secret_key: str = Field('replace-this-with-a-secret')
    log_level: str = Field('INFO')
    log_format: str = Field('json')
    allowed_origins: str = Field('*')
    webhook_timeout_seconds: int = Field(5)
    webhook_max_retries: int = Field(3)
    webhook_retry_delay_seconds: int = Field(5)
    allowed_zip_prefixes: str = Field('')
    duplicate_window_hours: int = Field(24)

    def zip_prefixes(self) -> List[str]:
        prefixes = [p.strip() for p in self.allowed_zip_prefixes.split(',') if p.strip()]
        return prefixes

settings = Settings()
