from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.labels import clean_labels
from app.models import Project, User
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from app.s3 import delete_prefix
from app.security import get_current_user
from app.services import get_project_for_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ProjectOut]:
    rows = list(
        db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc()))
    )
    return [ProjectOut.from_project(p) for p in rows]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = Project(
        user_id=user.id,
        name=body.name,
        description=body.description,
        action_types=clean_labels(body.action_types),
        objects=clean_labels(body.objects),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.from_project(project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    return ProjectOut.from_project(get_project_for_user(db, project_id, user))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = get_project_for_user(db, project_id, user)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.action_types is not None:
        project.action_types = clean_labels(body.action_types)
    if body.objects is not None:
        project.objects = clean_labels(body.objects)
    db.commit()
    db.refresh(project)
    return ProjectOut.from_project(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    project = get_project_for_user(db, project_id, user)
    delete_prefix(f"projects/{project.id}/")
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
