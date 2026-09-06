from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, User, Video, VideoStatus
from app.s3 import (
    annotation_s3_key,
    delete_object,
    object_exists,
    presigned_get_url,
    presigned_put_url,
)
from app.schemas import JobOut, ProcessIn, VideoCreate, VideoOut
from app.security import get_current_user
from app.services import (
    create_and_enqueue_job,
    create_video_row,
    first_or_create_task,
    get_project_for_user,
    get_video_for_user,
    known_pipeline_ids,
    latest_job,
    list_inference_for_user,
    neighbor_ids,
)

router = APIRouter(tags=["videos"])


def _to_video_out(
    db: Session,
    video: Video,
    *,
    include_upload: bool = False,
    content_type: str = "video/mp4",
    include_neighbors: bool = False,
) -> VideoOut:
    job = latest_job(db, video.id)
    playback = None
    if video.status != VideoStatus.UPLOADING:
        playback = presigned_get_url(video.s3_key)
    prev_id = next_id = None
    if include_neighbors:
        prev_id, next_id = neighbor_ids(db, video)
    return VideoOut(
        id=video.id,
        project_id=video.project_id,
        task_id=video.task_id,
        name=video.name,
        s3_key=video.s3_key,
        status=video.status.value,
        duration=video.duration,
        created_at=video.created_at,
        updated_at=video.updated_at,
        upload_url=presigned_put_url(video.s3_key, content_type) if include_upload else None,
        playback_url=playback,
        latest_job=JobOut.model_validate(job) if job else None,
        prev_video_id=prev_id,
        next_video_id=next_id,
    )


@router.get("/api/projects/{project_id}/videos", response_model=list[VideoOut])
def list_videos(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VideoOut]:
    get_project_for_user(db, project_id, user)
    videos = list(
        db.scalars(
            select(Video)
            .where(Video.project_id == project_id)
            .order_by(Video.created_at.asc())
        )
    )
    return [_to_video_out(db, v) for v in videos]


@router.post(
    "/api/projects/{project_id}/videos",
    response_model=VideoOut,
    status_code=status.HTTP_201_CREATED,
)
def create_video(
    project_id: str,
    body: VideoCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoOut:
    project = get_project_for_user(db, project_id, user)
    task = first_or_create_task(db, project)
    video = create_video_row(db, project, task, body.name)
    db.commit()
    db.refresh(video)
    return _to_video_out(db, video, include_upload=True, content_type=body.content_type)


@router.get("/api/videos/{video_id}", response_model=VideoOut)
def get_video(
    video_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoOut:
    video = get_video_for_user(db, video_id, user)
    return _to_video_out(db, video, include_neighbors=True)


@router.delete("/api/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(
    video_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    video = get_video_for_user(db, video_id, user)
    delete_object(video.s3_key)
    delete_object(annotation_s3_key(str(video.project_id), str(video.id)))
    db.delete(video)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/videos/{video_id}/uploaded", response_model=VideoOut)
def mark_uploaded(
    video_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoOut:
    video = get_video_for_user(db, video_id, user)
    if not object_exists(video.s3_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video object not found in storage",
        )
    if video.status == VideoStatus.UPLOADING:
        video.status = VideoStatus.UPLOADED
        db.commit()
        db.refresh(video)
    return _to_video_out(db, video, include_neighbors=True)


@router.get("/api/inference")
def list_inference(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    return list_inference_for_user(db, user)


@router.post("/api/videos/{video_id}/process", response_model=JobOut)
def process_video(
    video_id: str,
    body: ProcessIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Job:
    video = get_video_for_user(db, video_id, user)
    if video.status == VideoStatus.UPLOADING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video has not finished uploading",
        )
    pipeline = (body.pipeline if body else "marlin") or "marlin"
    if pipeline not in known_pipeline_ids(db, user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown inference type: {pipeline}",
        )
    return create_and_enqueue_job(db, video, requeue_if_queued=True, pipeline=pipeline)
