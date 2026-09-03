from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.consumer import start_consumer, stop_consumer
from app.inference import get_pipeline

settings = get_settings()


class JobIn(BaseModel):
    job_id: str
    video_id: str
    s3_key: str
    project_id: str = ""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_consumer()
    yield
    stop_consumer()


app = FastAPI(title="Boundr ML", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "pipeline": settings.pipeline}


@app.get("/inference/{name}")
def inference_info(name: str) -> dict:
    try:
        pipe = get_pipeline(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"id": pipe.name, "version": pipe.version}


@app.post("/jobs", status_code=202)
def enqueue_job(body: JobIn) -> dict:
    import redis

    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    r.xadd(
        settings.redis_stream,
        {
            "job_id": body.job_id,
            "video_id": body.video_id,
            "s3_key": body.s3_key,
            "pipeline": "overlap",
            "project_id": body.project_id,
        },
    )
    return {"status": "queued", "job_id": body.job_id}
