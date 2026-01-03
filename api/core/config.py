# C:\work-spaces\lead-gen\lead-gen\api\core\config.py
from __future__ import annotations

import secrets
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore"
    )

    # Environment
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    
    # Server
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    api_prefix: str = Field(default="/api", validation_alias="API_PREFIX")
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://leadgen:leadgen_secure@postgres:5432/leadgen",
        validation_alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=20, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, validation_alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout: int = Field(default=30, validation_alias="DATABASE_POOL_TIMEOUT")
    database_pool_recycle: int = Field(default=3600, validation_alias="DATABASE_POOL_RECYCLE")
    
    # Redis
    redis_url: str = Field(default="redis://redis:6379/0", validation_alias="REDIS_URL")
    redis_max_connections: int = Field(default=50, validation_alias="REDIS_MAX_CONNECTIONS")
    redis_socket_timeout: int = Field(default=5, validation_alias="REDIS_SOCKET_TIMEOUT")
    redis_socket_connect_timeout: int = Field(default=5, validation_alias="REDIS_SOCKET_CONNECT_TIMEOUT")
    
    # Security
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32), validation_alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=30, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    algorithm: str = Field(default="HS256", validation_alias="ALGORITHM")
    
    # Logging
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: str = Field(default="json", validation_alias="LOG_FORMAT")
    log_file: Optional[str] = Field(default=None, validation_alias="LOG_FILE")
    
    # CORS
    allowed_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", validation_alias="ALLOWED_ORIGINS")
    allowed_methods: str = Field(default="GET,POST,PUT,DELETE,OPTIONS", validation_alias="ALLOWED_METHODS")
    allowed_headers: str = Field(default="*", validation_alias="ALLOWED_HEADERS")
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_period: int = Field(default=60, validation_alias="RATE_LIMIT_PERIOD")
    
    # Webhook
    webhook_timeout_seconds: int = Field(default=5, validation_alias="WEBHOOK_TIMEOUT_SECONDS")
    webhook_max_retries: int = Field(default=3, validation_alias="WEBHOOK_MAX_RETRIES")
    webhook_retry_delay_seconds: int = Field(default=5, validation_alias="WEBHOOK_RETRY_DELAY_SECONDS")
    webhook_max_content_size: int = Field(default=1048576, validation_alias="WEBHOOK_MAX_CONTENT_SIZE")  # 1MB
    
    # Delivery Queue
    delivery_queue_max_concurrent: int = Field(default=50, validation_alias="DELIVERY_QUEUE_MAX_CONCURRENT")
    delivery_queue_max_retries: int = Field(default=5, validation_alias="DELIVERY_QUEUE_MAX_RETRIES")
    delivery_queue_retry_delays: str = Field(default="1,5,15,30,60", validation_alias="DELIVERY_QUEUE_RETRY_DELAYS")
    delivery_queue_dead_letter_retention_days: int = Field(default=30, validation_alias="DELIVERY_QUEUE_DEAD_LETTER_RETENTION_DAYS")
    
    # Business Logic
    allowed_zip_prefixes: str = Field(default="", validation_alias="ALLOWED_ZIP_PREFIXES")
    duplicate_window_hours: int = Field(default=24, validation_alias="DUPLICATE_WINDOW_HOURS")
    lead_validation_timeout: int = Field(default=30, validation_alias="LEAD_VALIDATION_TIMEOUT")
    
    # Monitoring
    sentry_dsn: Optional[str] = Field(default=None, validation_alias="SENTRY_DSN")
    metrics_port: int = Field(default=9090, validation_alias="METRICS_PORT")
    health_check_timeout: int = Field(default=5, validation_alias="HEALTH_CHECK_TIMEOUT")
    
    # Email/SMS
    email_provider: str = Field(default="console", validation_alias="EMAIL_PROVIDER")
    sms_provider: str = Field(default="console", validation_alias="SMS_PROVIDER")
    smtp_host: Optional[str] = Field(default=None, validation_alias="SMTP_HOST")
    smtp_port: Optional[int] = Field(default=None, validation_alias="SMTP_PORT")
    smtp_username: Optional[str] = Field(default=None, validation_alias="SMTP_USERNAME")
    smtp_password: Optional[str] = Field(default=None, validation_alias="SMTP_PASSWORD")
    
    # File Upload
    max_upload_size_mb: int = Field(default=10, validation_alias="MAX_UPLOAD_SIZE_MB")
    allowed_file_types: str = Field(default=".csv,.json,.xlsx", validation_alias="ALLOWED_FILE_TYPES")
    
    @field_validator("environment")
    def validate_environment(cls, v):
        valid_envs = ["development", "testing", "staging", "production"]
        if v not in valid_envs:
            raise ValueError(f"environment must be one of {valid_envs}")
        return v
    
    @field_validator("log_level")
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()
    
    @field_validator("log_format")
    def validate_log_format(cls, v):
        valid_formats = ["json", "console", "plain"]
        if v not in valid_formats:
            raise ValueError(f"log_format must be one of {valid_formats}")
        return v
    
    @field_validator("secret_key")
    def validate_secret_key(cls, v):
        if len(v) < 32:
            raise ValueError("secret_key must be at least 32 characters")
        return v
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        return self.environment == "development"
    
    @property
    def is_testing(self) -> bool:
        return self.environment == "testing"
    
    def origins(self) -> List[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
    
    def methods(self) -> List[str]:
        return [method.strip() for method in self.allowed_methods.split(",") if method.strip()]
    
    def zip_prefixes(self) -> List[str]:
        return [prefix.strip() for prefix in self.allowed_zip_prefixes.split(",") if prefix.strip()]
    
    def retry_delays(self) -> List[int]:
        return [int(delay.strip()) for delay in self.delivery_queue_retry_delays.split(",") if delay.strip()]
    
    def file_types(self) -> List[str]:
        return [ext.strip() for ext in self.allowed_file_types.split(",") if ext.strip()]


settings = Settings()