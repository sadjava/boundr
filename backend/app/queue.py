from functools import lru_cache

import redis

from app.config import get_settings

settings = get_settings()


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_job(
    job_id: str, video_id: str, s3_key: str, pipeline: str = "overlap", project_id: str = ""
) -> None:
    get_redis().xadd(
        settings.redis_stream,
        {
            "job_id": job_id,
            "video_id": video_id,
            "s3_key": s3_key,
            "pipeline": pipeline,
            "project_id": project_id,
        },
    )
