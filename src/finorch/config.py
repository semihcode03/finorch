"""Uygulama ayarlari. Tum degerler ortam degiskenlerinden (.env) okunur."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Veritabani
    database_url: str = "postgresql+psycopg://finorch:change_me_please@localhost:5432/finorch"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Whisper
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Vision (cok-modlu; grafik/gorsel okuma) - gpt-4o-mini gorsel girdiyi destekler
    vision_enabled: bool = True
    vision_model: str = "gpt-4o-mini"
    # ffmpeg sahne degisimi esigi (0..1). Dusuk = daha cok kare.
    yt_frame_scene_threshold: float = 0.4
    # Video basina maksimum kare (maliyet siniri)
    yt_max_frames: int = 12

    # X / Twitter (burner hesap cookie'leri)
    x_auth_token: str = ""
    x_ct0: str = ""
    x_username: str = ""

    # Genel
    data_dir: Path = Path("./data")
    poll_interval_minutes: int = 30
    analysts_config: Path = Path("./config/analysts.yaml")
    log_level: str = "INFO"

    # Dashboard
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8000

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
