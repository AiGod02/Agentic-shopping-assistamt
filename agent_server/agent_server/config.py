import os
import pathlib
from pydantic_settings import BaseSettings
import dotenv
dotenv.load_dotenv()
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
    app_name: str = "agent-server"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8001

    database_url: str = "postgresql+asyncpg://commerce:commerce_secret@localhost:5432/agenticcommerce"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"

    # LLM Providers
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    default_llm_provider: str = "groq"

    # Search
    search_backend: str = "chromadb"
    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: str = ""

    # JWT
    jwt_secret_key: str = "dev-jwt-secret-secure-32-byte-key-for-sha256-compliance-2024"
    jwt_algorithm: str = "HS256"

    # Inter-service
    merchant_server_url: str = "http://localhost:8002"
    payment_server_url: str = "http://localhost:8003"

    # Agent Settings
    max_tool_calls_per_turn: int = 5
    session_ttl_minutes: int = 30
    context_window_messages: int = 20

    # Rate Limiting
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    model_config = {"env_file": _env_file, "extra": "ignore"}


settings = Settings()
