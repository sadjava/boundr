import json
import urllib.request

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.annotation_io import parse_annotation_payload
from app.models import (
    Annotation,
    AnnotationStatus,
    Inference,
    Job,
    JobStatus,
    Project,
    Task,
    User,
    Video,
    VideoStatus,
    utcnow,
)
from app.s3 import video_s3_key
from app.queue import enqueue_job, flush_queue


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


def get_task_for_user(db: Session, task_id, user: User) -> Task:
    task = db.scalar(
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.id == task_id, Project.user_id == user.id)
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def first_or_create_task(db: Session, project: Project, name: str = "Default") -> Task:
    task = db.scalar(
        select(Task).where(Task.project_id == project.id).order_by(Task.created_at.asc()).limit(1)
    )
    if task is not None:
        return task
    task = Task(project_id=project.id, name=name)
    db.add(task)
    db.flush()
    return task


def create_video_row(db: Session, project: Project, task: Task, name: str) -> Video:
    video = Video(
        project_id=project.id,
        task_id=task.id,
        name=name,
        s3_key="",
        status=VideoStatus.UPLOADING,
    )
    db.add(video)
    db.flush()
    video.s3_key = video_s3_key(str(project.id), str(video.id))
    project.updated_at = utcnow()
    task.updated_at = utcnow()
    return video


def apply_user_annotation(db: Session, video: Video, raw: dict) -> Annotation:
    payload = parse_annotation_payload(raw, str(video.id), video.duration)
    annotation = db.query(Annotation).filter(Annotation.video_id == video.id).one_or_none()
    if annotation is None:
        annotation = Annotation(
            video_id=video.id,
            data=payload,
            version=1,
            status=AnnotationStatus.EDITED,
        )
        db.add(annotation)
    else:
        annotation.data = payload
        annotation.version += 1
        annotation.status = AnnotationStatus.EDITED
    duration = payload.get("duration")
    if duration:
        video.duration = float(duration)
    return annotation


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
        .where(Video.task_id == video.task_id, Video.created_at < video.created_at)
        .order_by(Video.created_at.desc())
        .limit(1)
    )
    next_id = db.scalar(
        select(Video.id)
        .where(Video.task_id == video.task_id, Video.created_at > video.created_at)
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
        if job.pipeline == pipeline:
            if job.status == JobStatus.QUEUED and requeue_if_queued:
                enqueue_job(str(job.id), str(video.id), video.s3_key, job.pipeline, str(video.project_id))
            return job
        job.status = JobStatus.FAILED
        job.error_msg = f"Superseded by {pipeline}"

    # Marlin's parsed labels depend on mutable project catalogs,
    # which are not part of the cache key.
    ver = pipeline_version(pipeline) if pipeline not in {"marlin", "marlin_gpt"} else None
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


def cancel_active_jobs(db: Session) -> int:
    jobs = db.scalars(
        select(Job).where(Job.status.in_({JobStatus.QUEUED, JobStatus.PROCESSING}))
    ).all()
    for job in jobs:
        job.status = JobStatus.FAILED
        job.error_msg = "Cancelled: queue cleared"
        video = db.get(Video, job.video_id)
        if video is not None and video.status in {VideoStatus.QUEUED, VideoStatus.PROCESSING}:
            video.status = (
                VideoStatus.COMPLETED if video.annotation is not None else VideoStatus.UPLOADED
            )
    flush_queue()
    db.commit()
    return len(jobs)
