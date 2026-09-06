from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.segment import AnnotationSegment
from app.labels import clean_labels


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    action_types: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    action_types: list[str] | None = None
    objects: list[str] | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    action_types: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_project(cls, project) -> ProjectOut:
        return cls(
            id=project.id,
            user_id=project.user_id,
            name=project.name,
            description=project.description,
            action_types=clean_labels(project.action_types),
            objects=clean_labels(project.objects),
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    video_count: int = 0
    annotated_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_task(cls, task, video_count: int = 0, annotated_count: int = 0) -> TaskOut:
        return cls(
            id=task.id,
            project_id=task.project_id,
            name=task.name,
            video_count=video_count,
            annotated_count=annotated_count,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class FineTuneCreate(BaseModel):
    task_ids: list[uuid.UUID] = Field(min_length=1)
    name: str | None = Field(default=None, max_length=32)


class FineTuneUpdate(BaseModel):
    hidden: bool


class FineTuneOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    display_name: str
    status: str
    hidden: bool = False
    error_msg: str | None
    s3_prefix: str
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    project_name: str | None = None
    task_names: list[str] = Field(default_factory=list)
    manifest: dict | None = None
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_fine_tune(
        cls,
        row,
        *,
        project_name: str | None = None,
        task_names: list[str] | None = None,
    ) -> FineTuneOut:
        raw_ids = row.task_ids or []
        return cls(
            id=row.id,
            user_id=row.user_id,
            project_id=row.project_id,
            name=row.name,
            display_name=row.display_name,
            status=row.status.value if hasattr(row.status, "value") else str(row.status),
            hidden=bool(getattr(row, "hidden", False)),
            error_msg=row.error_msg,
            s3_prefix=row.s3_prefix,
            task_ids=[uuid.UUID(str(t)) for t in raw_ids],
            project_name=project_name,
            task_names=list(task_names or []),
            manifest=row.manifest,
            created_at=row.created_at,
            started_at=row.started_at,
            updated_at=row.updated_at,
        )


class InternalFineTuneCompleteIn(BaseModel):
    s3_prefix: str
    manifest: dict = Field(default_factory=dict)


class VideoCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_type: str = "video/mp4"


class AnnotationData(BaseModel):
    video_id: str
    duration: float
    fps: float | None = None
    segments: list[AnnotationSegment] = Field(default_factory=list)


class AnnotationOut(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    s3_key: str | None
    data: AnnotationData
    version: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnotationPut(BaseModel):
    data: AnnotationData


class JobOut(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    pipeline: str = "marlin"
    status: str
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    error_msg: str | None

    model_config = {"from_attributes": True}


class VideoOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    name: str
    s3_key: str
    status: str
    duration: float | None
    created_at: datetime
    updated_at: datetime
    upload_url: str | None = None
    playback_url: str | None = None
    latest_job: JobOut | None = None
    prev_video_id: uuid.UUID | None = None
    next_video_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class ProcessIn(BaseModel):
    pipeline: str = "marlin"


class ProcessTaskOut(BaseModel):
    queued: int


class PurgeOut(BaseModel):
    cancelled: int


INFERENCE_TYPES = [
    {
        "id": "marlin",
        "name": "Marlin 2B",
        "description": "GPU video captioning through llama.cpp",
    },
    {
        "id": "marlin_gpt",
        "name": "Marlin 2B + GPT",
        "description": "Marlin captions mapped to actions by GPT-4o-mini",
    },
    {
        "id": "overlap",
        "name": "Overlap",
        "description": "Concurrent actions that overlap in time",
    },
    {
        "id": "sequential",
        "name": "Sequential",
        "description": "Non-overlapping actions, one after another",
    },
    {
        "id": "dense",
        "name": "Dense",
        "description": "Shorter windows with more overlap",
    },
    {
        "id": "pegasus_analyze",
        "name": "Pegasus (analyze)",
        "description": "TwelveLabs Pegasus, free-form actions via a JSON schema",
    },
    {
        "id": "pegasus_segment",
        "name": "Pegasus (segment)",
        "description": "TwelveLabs Pegasus, time-based segmentation of actions",
    },
]


class InternalStatusIn(BaseModel):
    status: str = "PROCESSING"


class InternalCompleteIn(BaseModel):
    annotation: AnnotationData
    s3_key: str
    duration: float | None = None
    model_version: int = 1


class InternalFailIn(BaseModel):
    error_msg: str
