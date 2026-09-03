import json
import urllib.request

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Annotation,
    AnnotationStatus,
    Inference,
    Job,
    JobStatus,
    Project,
    User,
    Video,
    VideoStatus,
    utcnow,
)
from app.queue import enqueue_job


def pipeline_version(pipeline: str) -> int | None:
    url = get_settings().ml_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/inference/{pipeline}", timeout=2) as resp:
            return int(json.loads(resp.read())["version"])
    except Exception:
        return None


def get_project_for_user(db: Session, project_id, user: User) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_video_for_user(db: Session, video_id, user: User) -> Video:
    video = db.scalar(
        select(Video)
        .join(Project, Video.project_id == Project.id)
        .where(Video.id == video_id, Project.user_id == user.id)
    )
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return video


def latest_job(db: Session, video_id) -> Job | None:
    return db.scalar(
        select(Job).where(Job.video_id == video_id).order_by(Job.created_at.desc()).limit(1)
    )


def neighbor_ids(db: Session, video: Video) -> tuple:
    prev_id = db.scalar(
        select(Video.id)
        .where(Video.project_id == video.project_id, Video.created_at < video.created_at)
        .order_by(Video.created_at.desc())
        .limit(1)
    )
    next_id = db.scalar(
        select(Video.id)
        .where(Video.project_id == video.project_id, Video.created_at > video.created_at)
        .order_by(Video.created_at.asc())
        .limit(1)
    )
    return prev_id, next_id


def get_inference(db: Session, video_id, pipeline: str, model_version: int | None = None) -> Inference | None:
    q = select(Inference).where(Inference.video_id == video_id, Inference.pipeline == pipeline)
    if model_version is not None:
        q = q.where(Inference.model_version == model_version)
    return db.scalar(q)


def upsert_working_annotation(
    db: Session,
    video: Video,
    payload: dict,
    *,
    s3_key: str | None = None,
    status: AnnotationStatus = AnnotationStatus.GENERATED,
) -> Annotation:
    annotation = db.query(Annotation).filter(Annotation.video_id == video.id).one_or_none()
    if annotation is None:
        annotation = Annotation(
            video_id=video.id,
            s3_key=s3_key,
            data=payload,
            version=1,
            status=status,
        )
        db.add(annotation)
        return annotation
    annotation.data = payload
    if s3_key is not None:
        annotation.s3_key = s3_key
    annotation.status = status
    return annotation


def upsert_inference(
    db: Session,
    video: Video,
    pipeline: str,
    payload: dict,
    s3_key: str | None,
    model_version: int = 1,
) -> Inference:
    inf = get_inference(db, video.id, pipeline)
    if inf is None:
        inf = Inference(
            video_id=video.id,
            pipeline=pipeline,
            model_version=model_version,
            data=payload,
            s3_key=s3_key,
        )
        db.add(inf)
        return inf
    inf.data = payload
    inf.s3_key = s3_key
    inf.model_version = model_version
    return inf


def apply_cached_inference(db: Session, video: Video, inf: Inference) -> Job:
    payload = inf.data if isinstance(inf.data, dict) else {}
    upsert_working_annotation(
        db, video, payload, s3_key=inf.s3_key, status=AnnotationStatus.GENERATED
    )
    duration = payload.get("duration")
    if duration:
        video.duration = float(duration)
    video.status = VideoStatus.COMPLETED
    job = db.scalar(
        select(Job)
        .where(
            Job.video_id == video.id,
            Job.pipeline == inf.pipeline,
            Job.status == JobStatus.COMPLETED,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if job is None:
        now = utcnow()
        job = Job(
            video_id=video.id,
            pipeline=inf.pipeline,
            status=JobStatus.COMPLETED,
            started_at=now,
        )
        db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(video)
    return job


def create_and_enqueue_job(
    db: Session, video: Video, *, requeue_if_queued: bool = False, pipeline: str = "overlap"
) -> Job:
    job = latest_job(db, video.id)
    if job is not None and job.status in {JobStatus.QUEUED, JobStatus.PROCESSING}:
        if job.status == JobStatus.QUEUED and requeue_if_queued:
            enqueue_job(str(job.id), str(video.id), video.s3_key, pipeline, str(video.project_id))
        return job

    ver = pipeline_version(pipeline)
    cached = get_inference(db, video.id, pipeline, ver) if ver is not None else None
    if cached is not None:
        return apply_cached_inference(db, video, cached)

    job = Job(video_id=video.id, status=JobStatus.QUEUED, pipeline=pipeline)
    video.status = VideoStatus.QUEUED
    project = db.get(Project, video.project_id)
    if project is not None:
        project.updated_at = utcnow()
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(video)
    enqueue_job(str(job.id), str(video.id), video.s3_key, pipeline, str(video.project_id))
    return job
