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
    # Ana sayfada baskasinin paylasimlari (retweet) da cikar; varsayilan olarak elenir
    # cunku hedef analistin KENDI gorusunu ogrenmek.
    x_include_reposts: bool = False
    # Baskasina verilen kisa cevaplar genelde analiz icermez
    x_include_replies: bool = False
    # Bu esigin altinda etkilesim alan gonderiler atlanir (0 = filtre yok)
    x_min_engagement: int = 0
    # Ayni konusma zincirindeki (thread) gonderileri tek icerik olarak birlestir
    x_stitch_threads: bool = True

    # Piyasa verisi (Faz 2: canli fiyat + kosul takibi)
    market_enabled: bool = True
    # Fiyat sorgusu onbellek suresi (saniye); ayni sembol tekrar tekrar cekilmesin
    market_cache_ttl_sec: int = 300
    # Gecmis mumlar bu sure boyunca tazelenmez (saat)
    market_history_ttl_hours: int = 6
    # Kosulun "yaklasma" bandi (%): tetik fiyatina bu kadar uzaklik progress=0 sayilir
    watch_band_pct: float = 10.0
    # Bu kadar gun sonra tetiklenmemis izlemeler "expired" olur
    watch_expire_days: int = 90
    # BIST sembolleri icin Yahoo Finance soneki
    bist_suffix: str = ".IS"

    # Piyasa seridi (dashboard ustundeki kayan bant)
    ticker_enabled: bool = True
    # Seritteki semboller. Bos birakilirsa market/ticker.py'daki varsayilan liste
    # kullanilir. Bicim: "sembol|etiket" ciftleri, virgulle ayrilmis.
    # Ornek: "XU100.IS|BIST 100,USDTRY=X|USD/TRY,GRAMALTIN|Gram Altin"
    ticker_symbols: str = ""
    # Serit verisi kac dakikada bir tazelensin (scheduler isi)
    ticker_refresh_minutes: int = 5
    # Tarayici seridi kac saniyede bir yeniden ceksin
    ticker_poll_seconds: int = 60

    # Efloud'dan turetilen, aciklanabilir BTC 15dk teyit takipcisi.
    # Seviyeler ortam degiskenleriyle degistirilebilir; kod bir analistin
    # gelecekteki kararlarini tahmin ettigini iddia etmez.
    efloud_signal_enabled: bool = True
    efloud_signal_refresh_minutes: int = 5
    efloud_btc_support: float = 76400.0
    efloud_btc_invalidation: float = 76000.0
    efloud_btc_downside_target: float = 72500.0
    efloud_btc_reclaim: float = 82300.0
    efloud_zone_pct: float = 0.35

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
