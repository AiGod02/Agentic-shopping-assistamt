"""Payment Server Configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "payment-server"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8003

    database_url: str = "postgresql+asyncpg://commerce:commerce_secret@localhost:5432/commerce_platform"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    # Razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # JWT (for authenticating inbound requests)
    jwt_secret_key: str = "dev-jwt-secret-secure-32-byte-key-for-sha256-compliance-2024"
    jwt_algorithm: str = "HS256"

    from pydantic import field_validator

    @field_validator("jwt_secret_key", mode="after")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v or v == "change-me-jwt-secret":
            raise ValueError("JWT_SECRET_KEY environment variable must be set and cannot be default 'change-me-jwt-secret'")
        return v

    # Inter-service
    merchant_server_url: str = "http://localhost:8002"

    # Rate Limiting
    rate_limit_requests_per_minute: int = 120
    rate_limit_burst: int = 20

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
