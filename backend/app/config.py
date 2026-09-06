from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://boundr:boundr@localhost:5432/boundr"
    redis_url: str = "redis://localhost:6379/0"
    redis_stream: str = "ml-jobs"
    redis_group: str = "ml-workers"

    jwt_secret: str = "change-me-in-prod"
    jwt_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"

    internal_api_token: str = "internal-secret"

    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "boundr"
    s3_region: str = "us-east-1"
    s3_presign_expires: int = 3600

    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    ml_url: str = "http://localhost:8001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
