from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_internal_token
from app.labels import clean_labels
from app.models import (
    FineTune,
    FineTuneStatus,
    Job,
    JobStatus,
    Project,
    Video,
    VideoStatus,
    utcnow,
)
from app.schemas import (
    FineTuneOut,
    InternalCompleteIn,
    InternalFailIn,
    InternalFineTuneCompleteIn,
    InternalStatusIn,
    JobOut,
)
from app.services import fine_tune_dataset, upsert_inference, upsert_working_annotation

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
    if job.status not in {JobStatus.QUEUED, JobStatus.PROCESSING}:
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
    if job.status not in {JobStatus.QUEUED, JobStatus.PROCESSING}:
        return job
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
    if job.status not in {JobStatus.QUEUED, JobStatus.PROCESSING}:
        return job
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


fine_tunes_internal = APIRouter(
    prefix="/api/internal/fine-tunes",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


def _fine_tune_or_404(db: Session, fine_tune_id: str) -> FineTune:
    row = db.get(FineTune, fine_tune_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fine-tune not found")
    return row


@fine_tunes_internal.get("/{fine_tune_id}/dataset")
def get_fine_tune_dataset(fine_tune_id: str, db: Session = Depends(get_db)) -> dict:
    return fine_tune_dataset(db, _fine_tune_or_404(db, fine_tune_id))


@fine_tunes_internal.post("/{fine_tune_id}/status", response_model=FineTuneOut)
def set_fine_tune_status(
    fine_tune_id: str, body: InternalStatusIn, db: Session = Depends(get_db)
) -> FineTuneOut:
    row = _fine_tune_or_404(db, fine_tune_id)
    if body.status != FineTuneStatus.PROCESSING.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported status")
    if row.status not in {FineTuneStatus.QUEUED, FineTuneStatus.PROCESSING}:
        return FineTuneOut.from_fine_tune(row)
    row.status = FineTuneStatus.PROCESSING
    row.started_at = row.started_at or utcnow()
    row.error_msg = None
    db.commit()
    db.refresh(row)
    return FineTuneOut.from_fine_tune(row)


@fine_tunes_internal.post("/{fine_tune_id}/complete", response_model=FineTuneOut)
def complete_fine_tune(
    fine_tune_id: str, body: InternalFineTuneCompleteIn, db: Session = Depends(get_db)
) -> FineTuneOut:
    row = _fine_tune_or_404(db, fine_tune_id)
    if row.status not in {FineTuneStatus.QUEUED, FineTuneStatus.PROCESSING}:
        return FineTuneOut.from_fine_tune(row)
    row.status = FineTuneStatus.COMPLETED
    row.error_msg = None
    row.s3_prefix = body.s3_prefix or row.s3_prefix
    row.manifest = body.manifest
    db.commit()
    db.refresh(row)
    return FineTuneOut.from_fine_tune(row)


@fine_tunes_internal.post("/{fine_tune_id}/fail", response_model=FineTuneOut)
def fail_fine_tune(
    fine_tune_id: str, body: InternalFailIn, db: Session = Depends(get_db)
) -> FineTuneOut:
    row = _fine_tune_or_404(db, fine_tune_id)
    if row.status not in {FineTuneStatus.QUEUED, FineTuneStatus.PROCESSING}:
        return FineTuneOut.from_fine_tune(row)
    row.status = FineTuneStatus.FAILED
    row.error_msg = body.error_msg
    db.commit()
    db.refresh(row)
    return FineTuneOut.from_fine_tune(row)
