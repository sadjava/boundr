from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import annotations, auth, fine_tunes, internal, jobs, projects, tasks, videos
from app.s3 import ensure_bucket

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_bucket()
    yield


app = FastAPI(title="Boundr", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(videos.router)
app.include_router(tasks.router)
app.include_router(fine_tunes.router)
app.include_router(jobs.router)
app.include_router(annotations.router)
app.include_router(internal.router)
app.include_router(internal.projects_internal)
app.include_router(internal.fine_tunes_internal)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
