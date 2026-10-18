"""
Merchant Server Configuration — environment-driven settings.
"""

from __future__ import annotations

import os
import pathlib
from pydantic_settings import BaseSettings

_base_dir = pathlib.Path(__file__).resolve().parent.parent.parent
_env_files = [
    str(pathlib.Path.cwd() / ".env"),
    str(_base_dir / ".env"),
    str(_base_dir.parent / ".env"),
    ".env",
]
_valid_env_files = [f for f in _env_files if os.path.exists(f)]
_env_file = _valid_env_files if _valid_env_files else ".env"


class Settings(BaseSettings):
    """Merchant server settings loaded from environment variables."""

    # App
    app_name: str = "merchant-server"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8002

    # Database
    database_url: str = "postgresql+asyncpg://commerce:commerce_secret@localhost:5432/commerce_platform"
    db_pool_size: int = 20
    db_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"

    # Weaviate
    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: str = ""

    # JWT
    jwt_secret_key: str = "dev-jwt-secret-secure-32-byte-key-for-sha256-compliance-2024"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    from pydantic import field_validator

    @field_validator("jwt_secret_key", mode="after")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v or v == "change-me-jwt-secret":
            raise ValueError("JWT_SECRET_KEY environment variable must be set and cannot be default 'change-me-jwt-secret'")
        return v

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Inter-service
    agent_server_url: str = "http://localhost:8001"
    payment_server_url: str = "http://localhost:8003"

    # Rate limiting
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    model_config = {"env_file": _env_file, "extra": "ignore"}


settings = Settings()
