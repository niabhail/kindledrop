from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str
    database_url: str = "sqlite+aiosqlite:///./data/kindledrop.db"
    epub_dir: Path = Path("/data/epubs")
    log_level: str = "INFO"

    # Delivery settings
    max_file_size_mb: int = 14  # Max EPUB size for email attachment
    calibre_timeout: int = 600  # Calibre recipe execution timeout in seconds
    epub_retention_hours: int = 24  # How long to keep EPUB files after delivery

    # Scheduler settings
    scheduler_poll_interval: int = 60  # Seconds between polling for due subscriptions
    scheduler_max_concurrent: int = 3  # Max parallel deliveries

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+aiosqlite", "")


settings = Settings()
