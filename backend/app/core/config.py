"""All settings come from env vars (prefix SORTLENS_) or a local .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SORTLENS_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".sortlens"  # SQLite DB, thumbnails, undo log live here
    host: str = "127.0.0.1"  # local only, never exposed to the network by default
    port: int = 8765
    frontend_origin: str = "http://localhost:3000"
    batch_size: int = 50  # small batches for low-end CPU laptops

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sortlens.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def undo_log_path(self) -> Path:
        return self.data_dir / "undo_log.jsonl"


settings = Settings()
