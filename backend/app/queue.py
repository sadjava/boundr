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


def flush_queue() -> int:
    """Drop pending and never-delivered jobs. The consumer group stays intact."""
    r = get_redis()
    stream = settings.redis_stream
    try:
        pending = r.xpending_range(stream, settings.redis_group, min="-", max="+", count=10000)
        ids = [
            item["message_id"] if isinstance(item, dict) else item[0]
            for item in pending
        ]
        if ids:
            r.xack(stream, settings.redis_group, *ids)
    except redis.ResponseError:
        pass
    try:
        return int(r.xtrim(stream, maxlen=0, approximate=False))
    except redis.ResponseError:
        return 0
