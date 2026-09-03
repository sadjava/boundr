from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_internal_token
from app.labels import clean_labels
from app.models import Job, JobStatus, Project, Video, VideoStatus, utcnow
from app.schemas import InternalCompleteIn, InternalFailIn, InternalStatusIn, JobOut
from app.services import upsert_inference, upsert_working_annotation

router = APIRouter(
    prefix="/api/internal/jobs",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


def _job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/{job_id}/status", response_model=JobOut)
def set_status(job_id: str, body: InternalStatusIn, db: Session = Depends(get_db)) -> Job:
    job = _job_or_404(db, job_id)
    if body.status != JobStatus.PROCESSING.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported status")
    if job.status == JobStatus.COMPLETED:
        return job
    job.status = JobStatus.PROCESSING
    job.started_at = job.started_at or utcnow()
    job.error_msg = None
    video = db.get(Video, job.video_id)
    if video is not None:
        video.status = VideoStatus.PROCESSING
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/complete", response_model=JobOut)
def complete(job_id: str, body: InternalCompleteIn, db: Session = Depends(get_db)) -> Job:
    job = _job_or_404(db, job_id)
    video = db.get(Video, job.video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    payload = body.annotation.model_dump()
    payload["video_id"] = str(video.id)
    pipeline = job.pipeline or "overlap"
    upsert_inference(db, video, pipeline, payload, body.s3_key, body.model_version)
    upsert_working_annotation(db, video, payload, s3_key=body.s3_key)

    if body.duration is not None:
        video.duration = body.duration
    elif body.annotation.duration:
        video.duration = body.annotation.duration

    job.status = JobStatus.COMPLETED
    job.error_msg = None
    video.status = VideoStatus.COMPLETED
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/fail", response_model=JobOut)
def fail(job_id: str, body: InternalFailIn, db: Session = Depends(get_db)) -> Job:
    job = _job_or_404(db, job_id)
    job.status = JobStatus.FAILED
    job.error_msg = body.error_msg
    video = db.get(Video, job.video_id)
    if video is not None:
        video.status = VideoStatus.FAILED
    db.commit()
    db.refresh(job)
    return job


projects_internal = APIRouter(
    prefix="/api/internal/projects",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


@projects_internal.get("/{project_id}")
def get_internal_project(project_id: str, db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {
        "id": str(project.id),
        "action_types": clean_labels(project.action_types),
        "objects": clean_labels(project.objects),
    }
