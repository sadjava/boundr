from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    redis_stream: str = "ml-finetune"
    redis_group: str = "ft-workers"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "boundr"
    s3_region: str = "us-east-1"
    backend_url: str = "http://localhost:8000"
    internal_api_token: str = "internal-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
