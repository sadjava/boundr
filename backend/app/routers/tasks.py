from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.annotation_io import annotation_to_csv, resolve_annotation_blobs
from app.archive import list_pairs
from app.database import get_db
from app.models import Annotation, Task, User, Video, VideoStatus, utcnow
from app.routers.videos import _to_video_out
from app.s3 import annotation_s3_key, delete_object, get_bytes, put_bytes
from app.schemas import (
    AnnotationData,
    INFERENCE_TYPES,
    ProcessIn,
    ProcessTaskOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    VideoCreate,
    VideoOut,
)
from app.security import get_current_user
from app.services import (
    apply_user_annotation,
    create_and_enqueue_job,
    create_video_row,
    get_project_for_user,
    get_task_for_user,
)

router = APIRouter(tags=["tasks"])

_VIDEO_CT = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".m4v": "video/mp4",
}


def _task_out(db: Session, task: Task) -> TaskOut:
    n = db.scalar(select(func.count()).select_from(Video).where(Video.task_id == task.id)) or 0
    return TaskOut.from_task(task, n)


def _counts(db: Session, project_id) -> dict:
    rows = db.execute(
        select(Video.task_id, func.count()).where(Video.project_id == project_id).group_by(Video.task_id)
    ).all()
    return {tid: n for tid, n in rows}


def _safe_stem(name: str, used: set[str]) -> str:
    stem = Path(name).stem or "video"
    base = stem
    i = 1
    while base.lower() in used:
        i += 1
        base = f"{stem}-{i}"
    used.add(base.lower())
    return base


def _zip_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip() or "export"


def _parse_formats(raw: str | None) -> set[str]:
    parts = [p.strip().lower() for p in (raw or "json").split(",") if p.strip()]
    allowed = {"json", "csv"}
    formats = {p for p in parts if p in allowed}
    if not formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="formats must include json and/or csv",
        )
    return formats


def _write_video_export(
    zf: zipfile.ZipFile,
    db: Session,
    video: Video,
    prefix: str,
    used: set[str],
    include_videos: bool,
    formats: set[str],
) -> None:
    stem = _safe_stem(video.name, used)
    annotation = db.query(Annotation).filter(Annotation.video_id == video.id).one_or_none()
    if annotation is not None:
        data = AnnotationData.model_validate(annotation.data).model_dump()
    else:
        data = AnnotationData(
            video_id=str(video.id),
            duration=float(video.duration or 0),
            segments=[],
        ).model_dump()
    if "json" in formats:
        zf.writestr(f"{prefix}annotations/{stem}.json", json.dumps(data, indent=2))
    if "csv" in formats:
        zf.writestr(f"{prefix}annotations/{stem}.csv", annotation_to_csv(data))
    if not include_videos:
        return
    try:
        raw = get_bytes(video.s3_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"could not read {video.name} from storage",
        ) from exc
    ext = Path(video.name).suffix.lower() or ".mp4"
    if ext not in _VIDEO_CT:
        ext = ".mp4"
    zf.writestr(f"{prefix}videos/{stem}{ext}", raw)


def _purge_video(video: Video) -> None:
    delete_object(video.s3_key)
    delete_object(annotation_s3_key(str(video.project_id), str(video.id)))


def _import_zip(db: Session, task: Task, blob: bytes, with_annotations: bool) -> int:
    # ponytail: whole zip in RAM; spill to a temp file if archives grow past a few hundred MB
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="not a zip archive") from exc
    try:
        pairs = list_pairs(zf, with_annotations)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    prepared: list[tuple[str, bytes, dict | None]] = []
    for display, video_member, ann_members in pairs:
        raw_video = zf.read(video_member)
        payload = None
        if ann_members is not None:
            try:
                blobs = {ext: zf.read(member) for ext, member in ann_members.items()}
                payload = resolve_annotation_blobs(blobs, "pending")
            except (ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{Path(display).stem}: {exc}",
                ) from exc
        prepared.append((display, raw_video, payload))

    project = task.project
    for display, raw_video, payload in prepared:
        video = create_video_row(db, project, task, display)
        put_bytes(
            video.s3_key,
            raw_video,
            _VIDEO_CT.get(Path(display).suffix.lower(), "video/mp4"),
        )
        video.status = VideoStatus.UPLOADED
        if payload is not None:
            apply_user_annotation(db, video, payload)
            video.status = VideoStatus.COMPLETED
    task.updated_at = utcnow()
    project.updated_at = utcnow()
    return len(prepared)


@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TaskOut]:
    project = get_project_for_user(db, project_id, user)
    tasks = list(
        db.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.created_at.asc()))
    )
    counts = _counts(db, project.id)
    return [TaskOut.from_task(t, counts.get(t.id, 0)) for t in tasks]


@router.post(
    "/api/projects/{project_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    project_id: str,
    body: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskOut:
    project = get_project_for_user(db, project_id, user)
    task = Task(project_id=project.id, name=body.name.strip())
    project.updated_at = utcnow()
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskOut.from_task(task, 0)


@router.post("/api/projects/{project_id}/import", response_model=TaskOut)
def import_project_archive(
    project_id: str,
    file: UploadFile = File(...),
    with_annotations: bool = Form(False),
    task_name: str | None = Form(None),
    task_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskOut:
    project = get_project_for_user(db, project_id, user)
    if task_id:
        task = get_task_for_user(db, task_id, user)
        if task.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task is not in this project")
    else:
        name = (task_name or "").strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task name is required")
        task = Task(project_id=project.id, name=name)
        db.add(task)
        db.flush()
    blob = file.file.read()
    _import_zip(db, task, blob, with_annotations)
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskOut:
    return _task_out(db, get_task_for_user(db, task_id, user))


@router.patch("/api/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskOut:
    task = get_task_for_user(db, task_id, user)
    if body.name is not None:
        task.name = body.name.strip()
        task.project.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    task = get_task_for_user(db, task_id, user)
    for video in list(task.videos):
        _purge_video(video)
    task.project.updated_at = utcnow()
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/tasks/{task_id}/videos", response_model=list[VideoOut])
def list_task_videos(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VideoOut]:
    task = get_task_for_user(db, task_id, user)
    videos = list(
        db.scalars(select(Video).where(Video.task_id == task.id).order_by(Video.created_at.asc()))
    )
    return [_to_video_out(db, v) for v in videos]


@router.post(
    "/api/tasks/{task_id}/videos",
    response_model=VideoOut,
    status_code=status.HTTP_201_CREATED,
)
def create_task_video(
    task_id: str,
    body: VideoCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoOut:
    task = get_task_for_user(db, task_id, user)
    video = create_video_row(db, task.project, task, body.name)
    db.commit()
    db.refresh(video)
    return _to_video_out(db, video, include_upload=True, content_type=body.content_type)


@router.post("/api/tasks/{task_id}/import", response_model=TaskOut)
def import_task_archive(
    task_id: str,
    file: UploadFile = File(...),
    with_annotations: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskOut:
    task = get_task_for_user(db, task_id, user)
    blob = file.file.read()
    _import_zip(db, task, blob, with_annotations)
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.get("/api/projects/{project_id}/export")
def export_project(
    project_id: str,
    include_videos: bool = False,
    formats: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    project = get_project_for_user(db, project_id, user)
    fmt_set = _parse_formats(formats)
    tasks = list(
        db.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.created_at.asc()))
    )
    # ponytail: zip built in RAM; stream to disk if a project has many large videos
    buf = io.BytesIO()
    wrote = 0
    used_tasks: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for task in tasks:
            videos = list(
                db.scalars(select(Video).where(Video.task_id == task.id).order_by(Video.created_at.asc()))
            )
            if not videos:
                continue
            prefix = f"{_safe_stem(task.name, used_tasks)}/"
            used: set[str] = set()
            for video in videos:
                _write_video_export(zf, db, video, prefix, used, include_videos, fmt_set)
                wrote += 1
    if not wrote:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project has no videos")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{_zip_name(project.name)}.zip"'},
    )


@router.get("/api/tasks/{task_id}/export")
def export_task(
    task_id: str,
    include_videos: bool = False,
    formats: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    task = get_task_for_user(db, task_id, user)
    fmt_set = _parse_formats(formats)
    videos = list(
        db.scalars(select(Video).where(Video.task_id == task.id).order_by(Video.created_at.asc()))
    )
    if not videos:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task has no videos")

    # ponytail: zip built in RAM; stream to disk if a task has many large videos
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for video in videos:
            _write_video_export(zf, db, video, "", used, include_videos, fmt_set)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{_zip_name(task.name)}.zip"'},
    )


@router.post("/api/tasks/{task_id}/process", response_model=ProcessTaskOut)
def process_task(
    task_id: str,
    body: ProcessIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProcessTaskOut:
    task = get_task_for_user(db, task_id, user)
    pipeline = (body.pipeline if body else "overlap") or "overlap"
    known = {item["id"] for item in INFERENCE_TYPES}
    if pipeline not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown inference type: {pipeline}",
        )
    videos = list(
        db.scalars(select(Video).where(Video.task_id == task.id).order_by(Video.created_at.asc()))
    )
    queued = 0
    for video in videos:
        if video.status == VideoStatus.UPLOADING:
            continue
        create_and_enqueue_job(db, video, requeue_if_queued=True, pipeline=pipeline)
        queued += 1
    if queued == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no videos ready to process")
    return ProcessTaskOut(queued=queued)
