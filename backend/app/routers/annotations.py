import json

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.annotation_io import annotation_to_csv
from app.database import get_db
from app.models import Annotation, User
from app.schemas import AnnotationData, AnnotationOut, AnnotationPut
from app.security import get_current_user
from app.services import apply_user_annotation, get_video_for_user

router = APIRouter(tags=["annotations"])


@router.get("/api/videos/{video_id}/annotation", response_model=AnnotationOut)
def get_annotation(
    video_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Annotation:
    video = get_video_for_user(db, video_id, user)
    annotation = db.query(Annotation).filter(Annotation.video_id == video.id).one_or_none()
    if annotation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    return annotation


@router.put("/api/videos/{video_id}/annotation", response_model=AnnotationOut)
def put_annotation(
    video_id: str,
    body: AnnotationPut,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Annotation:
    video = get_video_for_user(db, video_id, user)
    annotation = apply_user_annotation(db, video, body.data.model_dump())
    db.commit()
    db.refresh(annotation)
    return annotation


@router.post("/api/videos/{video_id}/annotation/upload", response_model=AnnotationOut)
def upload_annotation(
    video_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Annotation:
    video = get_video_for_user(db, video_id, user)
    blob = file.file.read()
    try:
        raw = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="annotation JSON must be an object")
    try:
        annotation = apply_user_annotation(db, video, raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(annotation)
    return annotation


@router.get("/api/videos/{video_id}/export")
def export_annotation(
    video_id: str,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    video = get_video_for_user(db, video_id, user)
    annotation = db.query(Annotation).filter(Annotation.video_id == video.id).one_or_none()
    if annotation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    data = AnnotationData.model_validate(annotation.data)

    fmt = format.lower()
    if fmt == "json":
        body = json.dumps(data.model_dump(), indent=2)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{video.name}.annotation.json"'
            },
        )
    if fmt == "csv":
        return Response(
            content=annotation_to_csv(data.model_dump()),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{video.name}.annotation.csv"'},
        )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be json or csv")
