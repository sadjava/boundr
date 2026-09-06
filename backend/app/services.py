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
    FineTune,
    FineTuneStatus,
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
from app.s3 import fine_tune_s3_prefix, video_s3_key
from app.queue import enqueue_finetune, enqueue_job, flush_queue
from app.finetune import default_display_name, default_fine_tune_name, validate_fine_tune_name
from app.schemas import INFERENCE_TYPES


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
    # Marlin family (base + fine-tunes) skips cache: catalogs and checkpoints vary.
    skip_cache = pipeline in {"marlin", "marlin_gpt"} or pipeline.startswith("marlin_ft_")
    ver = pipeline_version(pipeline) if not skip_cache else None
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


def _annotation_has_segments(data) -> bool:
    if not isinstance(data, dict):
        return False
    segments = data.get("segments")
    return isinstance(segments, list) and len(segments) > 0


def annotated_videos_for_tasks(
    db: Session, project_id, task_ids: list
) -> list[tuple[Video, Annotation]]:
    """Videos in these tasks with any annotation that has non-empty segments."""
    if not task_ids:
        return []
    rows = db.execute(
        select(Video, Annotation)
        .join(Annotation, Annotation.video_id == Video.id)
        .where(
            Video.project_id == project_id,
            Video.task_id.in_(task_ids),
        )
        .order_by(Video.created_at.asc())
    ).all()
    return [(video, ann) for video, ann in rows if _annotation_has_segments(ann.data)]


def annotated_counts_by_task(db: Session, project_id) -> dict:
    rows = db.execute(
        select(Video.task_id, Annotation.data)
        .join(Annotation, Annotation.video_id == Video.id)
        .where(Video.project_id == project_id)
    ).all()
    counts: dict = {}
    for task_id, data in rows:
        if _annotation_has_segments(data):
            counts[task_id] = counts.get(task_id, 0) + 1
    return counts


def known_pipeline_ids(db: Session, user: User) -> set[str]:
    known = {item["id"] for item in INFERENCE_TYPES}
    ft_names = db.scalars(
        select(FineTune.name).where(
            FineTune.user_id == user.id,
            FineTune.status == FineTuneStatus.COMPLETED,
        )
    ).all()
    known.update(ft_names)
    return known


def list_inference_for_user(db: Session, user: User) -> list[dict]:
    items = list(INFERENCE_TYPES)
    rows = db.scalars(
        select(FineTune)
        .where(FineTune.user_id == user.id, FineTune.status == FineTuneStatus.COMPLETED)
        .order_by(FineTune.created_at.desc())
    ).all()
    for row in rows:
        items.append(
            {
                "id": row.name,
                "name": row.display_name,
                "description": f"Fine-tuned Marlin checkpoint ({row.name})",
            }
        )
    return items


def get_fine_tune_for_user(db: Session, fine_tune_id, user: User) -> FineTune:
    row = db.scalar(
        select(FineTune).where(FineTune.id == fine_tune_id, FineTune.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fine-tune not found")
    return row


def create_and_enqueue_fine_tune(
    db: Session,
    project: Project,
    user: User,
    task_ids: list,
    name: str | None = None,
) -> FineTune:
    tasks = list(
        db.scalars(
            select(Task).where(Task.project_id == project.id, Task.id.in_(task_ids))
        ).all()
    )
    if len(tasks) != len(set(task_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more tasks are not in this project",
        )
    annotated = annotated_videos_for_tasks(db, project.id, task_ids)
    if not annotated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No annotations with segments in the selected tasks",
        )
    try:
        ft_name = (
            validate_fine_tune_name(name)
            if name
            else default_fine_tune_name(project.name)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    existing = db.scalar(
        select(FineTune).where(FineTune.user_id == user.id, FineTune.name == ft_name)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fine-tune name already exists: {ft_name}",
        )

    row = FineTune(
        user_id=user.id,
        project_id=project.id,
        name=ft_name,
        display_name=default_display_name(project.name, ft_name),
        status=FineTuneStatus.QUEUED,
        s3_prefix="",
        task_ids=[str(t) for t in task_ids],
    )
    db.add(row)
    db.flush()
    row.s3_prefix = fine_tune_s3_prefix(str(user.id), str(row.id))
    db.commit()
    db.refresh(row)
    enqueue_finetune(str(row.id))
    return row


def cancel_fine_tune(db: Session, fine_tune: FineTune) -> FineTune:
    if fine_tune.status not in {FineTuneStatus.QUEUED, FineTuneStatus.PROCESSING}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel fine-tune in status {fine_tune.status.value}",
        )
    fine_tune.status = FineTuneStatus.FAILED
    fine_tune.error_msg = "Cancelled by user"
    db.commit()
    db.refresh(fine_tune)
    return fine_tune


def fine_tune_dataset(db: Session, fine_tune: FineTune) -> dict:
    task_ids = [t for t in (fine_tune.task_ids or [])]
    project_id = fine_tune.project_id
    videos_out: list[dict] = []
    if project_id is not None and task_ids:
        for video, ann in annotated_videos_for_tasks(db, project_id, task_ids):
            data = ann.data if isinstance(ann.data, dict) else {}
            videos_out.append(
                {
                    "video_id": str(video.id),
                    "s3_key": video.s3_key,
                    "duration": video.duration,
                    "segments": data.get("segments") or [],
                }
            )
    return {
        "id": str(fine_tune.id),
        "name": fine_tune.name,
        "project_id": str(project_id) if project_id else "",
        "s3_prefix": fine_tune.s3_prefix,
        "task_ids": [str(t) for t in task_ids],
        "videos": videos_out,
    }
