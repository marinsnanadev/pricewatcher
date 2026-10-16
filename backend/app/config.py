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
    cors_origins: str = "http://localhost:5174,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
