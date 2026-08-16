from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    # Gemini — powers both the voice agent (Live API, native SDK) and the
    # text agents (Agents SDK, via Gemini's OpenAI-compatible endpoint).
    gemini_api_key: str = ""
    gemini_openai_base_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    gemini_text_model: str = "gemini-2.5-flash"
    gemini_live_model: str = "gemini-live-2.5-flash-preview"

    # Postgres — schema owned by Prisma (web/), read/written here via SQLAlchemy.
    database_url: str = (
        "postgresql+asyncpg://sales_agent:sales_agent_dev@localhost:5432/sales_agent"
    )

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "company_knowledge"

    # Shared secret for Next.js -> FastAPI calls (never exposed to the browser).
    internal_api_secret: str = ""

    # HubSpot
    hubspot_private_app_token: str = ""

    # Slack
    slack_webhook_url: str = ""

    # Voice call guardrails
    call_max_duration_seconds: int = 600
    call_rate_limit_per_ip_per_hour: int = 10

    # Outbound email safety
    dry_run: bool = True

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
