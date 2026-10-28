from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./pricewatcher.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    redis_url: str = "redis://localhost:6379/0"
    default_check_interval_minutes: int = 360  # 6h
    dispatch_every_seconds: int = 60  # how often beat looks for due products
    dispatch_batch_size: int = 200
    start_jitter_seconds: int = 120  # random delay before a job starts
    # --- realtime (WebSocket) ---
    ws_auth_timeout_seconds: float = 5.0  # client must authenticate this fast after connecting
    ws_heartbeat_seconds: float = 25.0  # keeps proxies from closing idle sockets

    # --- alerts ---
    alert_cooldown_hours: int = 6  # min gap before a "further drop" re-alert
    alert_further_drop_percent: float = 3.0  # how much lower than the last alert counts as news
    webhook_timeout_seconds: float = 10.0
    allow_private_webhooks: bool = False  # True only for local dev (localhost receivers)
    email_backend: str = "console"  # console (just logs) | smtp
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_from: str = "Price Watcher <alerts@pricewatcher.local>"
    cors_origins: str = "http://localhost:5174,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
