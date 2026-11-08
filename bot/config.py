"""Bot configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings populated from .env file."""

    # Telegram
    bot_token: str

    # Database
    database_url: str = (
        "postgresql+asyncpg://botuser:botpass@localhost:5432/filebot"
    )

    # Admin Telegram user IDs (comma-separated string → list[int])
    admin_ids: str = ""

    # Optional: channel username users must join (e.g. "@yourchannel")
    force_sub_channel: str | None = None

    # Rate limit: max messages per minute per user
    rate_limit: int = 30

    # Auto-delete sent files after N minutes (0 to disable)
    auto_delete_minutes: int = 10

    # Optional: channel for user requests (if not set, sent to admin DMs)
    request_channel: str | None = None

    # Optional: public channel to post new episode updates
    update_channel: str | None = None

    # Optional: private storage channel for sub-bot media ingestion
    storage_channel: str | None = None


    # Pagination
    page_size: int = 8

    # Optional: Google Gemini AI API key for conversational anime concierge
    gemini_api_key: str | None = None

    # Telegram MTProto streaming credentials
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def admin_id_list(self) -> list[int]:
        """Return admin IDs as a list of integers."""
        if not self.admin_ids:
            return []
        return [int(uid.strip()) for uid in self.admin_ids.split(",") if uid.strip()]


settings = Settings()  # type: ignore[call-arg]
