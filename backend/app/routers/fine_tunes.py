from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FineTune, User
from app.schemas import FineTuneCreate, FineTuneOut
from app.security import get_current_user
from app.services import (
    cancel_fine_tune,
    create_and_enqueue_fine_tune,
    get_fine_tune_for_user,
    get_project_for_user,
)

router = APIRouter(tags=["fine-tunes"])


@router.post(
    "/api/projects/{project_id}/fine-tunes",
    response_model=FineTuneOut,
    status_code=status.HTTP_201_CREATED,
)
def create_fine_tune(
    project_id: str,
    body: FineTuneCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FineTuneOut:
    project = get_project_for_user(db, project_id, user)
    row = create_and_enqueue_fine_tune(db, project, user, body.task_ids, body.name)
    return FineTuneOut.from_fine_tune(row)


@router.get("/api/projects/{project_id}/fine-tunes", response_model=list[FineTuneOut])
def list_project_fine_tunes(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FineTuneOut]:
    project = get_project_for_user(db, project_id, user)
    rows = list(
        db.scalars(
            select(FineTune)
            .where(FineTune.user_id == user.id, FineTune.project_id == project.id)
            .order_by(FineTune.created_at.desc())
        )
    )
    return [FineTuneOut.from_fine_tune(r) for r in rows]


@router.get("/api/fine-tunes/{fine_tune_id}", response_model=FineTuneOut)
def get_fine_tune(
    fine_tune_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FineTuneOut:
    return FineTuneOut.from_fine_tune(get_fine_tune_for_user(db, fine_tune_id, user))


@router.post("/api/fine-tunes/{fine_tune_id}/cancel", response_model=FineTuneOut)
def cancel_fine_tune_endpoint(
    fine_tune_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FineTuneOut:
    row = get_fine_tune_for_user(db, fine_tune_id, user)
    return FineTuneOut.from_fine_tune(cancel_fine_tune(db, row))
