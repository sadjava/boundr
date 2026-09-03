import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Annotation, AnnotationStatus, User
from app.schemas import AnnotationData, AnnotationOut, AnnotationPut
from app.security import get_current_user
from app.services import get_video_for_user

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
    annotation = db.query(Annotation).filter(Annotation.video_id == video.id).one_or_none()
    payload = body.data.model_dump()
    payload["video_id"] = str(video.id)
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
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["video_id", "segment_id", "action", "object", "start", "end", "keyframe"])
        for seg in data.segments:
            writer.writerow(
                [
                    data.video_id,
                    seg.id,
                    seg.action,
                    seg.object or "",
                    seg.start,
                    seg.end,
                    seg.keyframe,
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{video.name}.annotation.csv"'},
        )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be json or csv")
