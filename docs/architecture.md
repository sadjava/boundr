# Boundr — Architecture Brief

## Goal

Build a lightweight web application for automatic annotation of short human-action videos (5–30 sec).

User flow:

1. Login
2. Create/select project
3. Upload video
4. ML automatically generates action annotation
5. User reviews/edits timeline and labels
6. Export JSON/CSV
7. Navigate to next video/task

One video = one annotation task.

---

## Architecture

```text
Browser / UI
    |
    | REST
    v
Backend (FastAPI)
    |
    +---- PostgreSQL
    |      users, projects, tasks, videos, jobs,
    |      annotations, inferences, fine_tunes
    |
    +---- Redis Streams
    |      ml-jobs      → ml-service
    |      ml-finetune  → finetune-service
    |
    +---- S3 / MinIO
           videos, annotation artifacts, fine-tune checkpoints

Redis Stream ml-jobs
    |
    v
ML Service
    |
    +-- queue consumer
    +-- video download from S3
    +-- preprocessing / ffmpeg
    +-- ML inference
    +-- postprocessing
    +-- save result
    +-- notify Backend
    |
    +-- Marlin llama.cpp server (local GPU)

Redis Stream ml-finetune
    |
    v
Fine-tune Service (mock)
    |
    +-- queue consumer
    +-- fetch dataset (EDITED annotations) via internal API
    +-- download videos from S3
    +-- write stub checkpoint + manifest to S3
    +-- notify Backend
```

Docker Compose services:

```text
frontend
backend
ml-service
finetune-service
marlin-server
postgres
redis
minio
```

No separate worker containers beyond the two consumers. `ml-service` and
`finetune-service` each contain an HTTP health endpoint and a Redis consumer.
`finetune-service` handles mock training jobs to exercise the data path.
The [`finetuning/`](../finetuning/README.md) toolkit trains Marlin
PEFT adapters from local datasets in its own environment. It is outside the
Compose job flow; those adapters are not automatically uploaded, registered,
or served by the application.

---

## Storage

### PostgreSQL

Stores metadata/state only:

* `users`
* `projects`
* `tasks`
* `videos`
* `jobs`
* `annotations`
* `inferences`
* `fine_tunes`

Annotation can be stored as `JSONB`.

### S3 / MinIO

Stores files:

```text
projects/{project_id}/videos/{video_id}/original.mp4
projects/{project_id}/videos/{video_id}/annotation.json
users/{user_id}/models/{fine_tune_id}/manifest.json
users/{user_id}/models/{fine_tune_id}/checkpoint.json
```

Video must NOT pass through Backend.

Upload:

```text
UI -> Backend -> presigned S3 URL
UI -> S3 directly
```

ML downloads the original video directly from S3.

---

## Job Processing

Backend is the source of truth for job state.

Typical states:

```text
QUEUED
PROCESSING
COMPLETED
FAILED
```

Flow:

```text
Backend
  -> create job in PostgreSQL
  -> XADD job to Redis Stream

ML service
  -> XREADGROUP from Redis
  -> mark job PROCESSING via Backend internal API
  -> download video from S3
  -> preprocess with ffmpeg
  -> run models
  -> postprocess annotation
  -> save annotation
  -> notify Backend
  -> XACK Redis message
```

Redis is only the queue/transport, not the source of truth.

Use Redis Streams rather than a simple LIST to avoid losing jobs after ML-service restart.

Only lightweight job metadata goes into Redis:

```json
{
  "job_id": "...",
  "video_id": "...",
  "s3_key": "..."
}
```

Never put video bytes into Redis.

---

## Preprocessing

Preprocessing belongs inside `ml-service`.

Pipeline:

```text
S3 original video
    -> ffprobe
    -> ffmpeg normalization
    -> frame extraction / model-specific preprocessing
    -> inference
```

Keep temporary intermediate files in local `/tmp`; do not store them permanently in S3 unless needed.

Backend should not know model-specific preprocessing details.

---

## Backend API

### Auth

```text
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/me
```

### Projects

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

### Videos

```text
GET    /api/projects/{project_id}/videos
POST   /api/projects/{project_id}/videos
GET    /api/videos/{video_id}
DELETE /api/videos/{video_id}
```

`POST /projects/{id}/videos` creates the video record and returns a presigned upload URL.

### Processing

```text
POST /api/videos/{video_id}/process
POST /api/jobs/purge
GET  /api/jobs/{job_id}
GET  /api/inference
```

`GET /api/inference` requires a JWT and returns the static pipeline list plus the
caller's `COMPLETED` fine-tunes that are not `hidden` (ids like `marlin_ft_*`).

`POST /api/jobs/purge` marks every `QUEUED`/`PROCESSING` job as failed, restores the
video to `UPLOADED` or `COMPLETED` (if an annotation already exists), and trims the
Redis stream so those messages are not consumed. A consumer that is already inside
`infer()` is not killed; its later callback is ignored so it cannot overwrite a new run.

### Fine-tunes

```text
POST /api/projects/{project_id}/fine-tunes
GET  /api/projects/{project_id}/fine-tunes
GET  /api/fine-tunes
GET  /api/fine-tunes/{fine_tune_id}
PATCH /api/fine-tunes/{id}          # { "hidden": true|false }
DELETE /api/fine-tunes/{id}         # row + S3 prefix
POST /api/fine-tunes/{id}/cancel    # QUEUED|PROCESSING → FAILED (owner only)
```

Creates a `fine_tunes` row (`QUEUED`), enqueues `{job_id}` on Redis stream `ml-finetune`,
and returns immediately. Videos from the selected tasks that have an annotation with
non-empty `segments` are used (GENERATED or EDITED). Default pipeline id is
`marlin_ft_{project}_{YYYYMMDD}_{hex}` (≤32 chars).

`GET /api/fine-tunes` lists every fine-tune for the caller (all statuses), with
`project_name` / `task_names` enrichment for the Models page. `hidden` keeps the row
but drops it from `GET /api/inference`. `DELETE` removes the row and best-effort
deletes the S3 prefix.

Cancel is cooperative: the consumer checks status after `PROCESSING` and skips if the
job was cancelled; a later `complete`/`fail` callback cannot overwrite a cancelled row.
To run again, start a new fine-tune from the project page.

### Annotation

```text
GET /api/videos/{video_id}/annotation
PUT /api/videos/{video_id}/annotation
```

### Export

```text
GET /api/videos/{video_id}/export?format=json
GET /api/videos/{video_id}/export?format=csv
```

### Internal ML callbacks

```text
POST /api/internal/jobs/{job_id}/status
POST /api/internal/jobs/{job_id}/complete
POST /api/internal/jobs/{job_id}/fail
GET  /api/internal/fine-tunes/{id}/dataset
POST /api/internal/fine-tunes/{id}/status
POST /api/internal/fine-tunes/{id}/complete
POST /api/internal/fine-tunes/{id}/fail
```

---

## ML Service API

Minimal:

```text
POST /jobs
GET  /health
```

`POST /jobs` does NOT run inference synchronously. It only adds a job to Redis and returns `202 Accepted`.

Actual processing happens in the Redis consumer inside the same `ml-service` container.

### Fine-tune service (mock)

```text
GET /health
```

Consumes `ml-finetune`, downloads each dataset video from S3, uploads a stub
`manifest.json` + `checkpoint.json` under `users/{user_id}/models/{id}/`, and
callbacks the backend. Selecting a completed `marlin_ft_*` pipeline runs stock
Marlin via llama.cpp. Offline PEFT training uses the `finetuning/` toolkit.

### Marlin pipeline

The default `marlin` pipeline samples up to 120 seconds at 2 FPS, sends a temporary
lossless clip to the local llama.cpp server, and converts its timed English captions
into the annotation contract with a local spaCy parser. `marlin_gpt` shares that
captioning step and maps captions through GPT-4o-mini on OpenRouter instead. The
model weights live in `./models/marlin/`, outside the containers and Git. Inputs
longer than 120 seconds fail before encoding or GPU inference. See
[marlin-llamacpp.md](marlin-llamacpp.md) for the pinned build and measured settings.

### Pegasus pipelines and external APIs

The `pegasus_analyze` and `pegasus_segment` pipelines upload videos directly to the
TwelveLabs API. The video file is downloaded from S3 locally first; a presigned URL
from MinIO (with the default `S3_PUBLIC_ENDPOINT=http://localhost:9000`) cannot be
resolved by external services. The SDK is imported lazily so a broken or missing
dependency does not crash the consumer at startup. Analyze requests cap
`max_tokens` at 4096 so a job can finish inside the two-minute product SLA
(`TIMEOUT=120` on both Pegasus pipelines). Dense SME output still hits that
cap (`finish_reason=length`); the client then salvages a valid JSON prefix
instead of failing the job.

Processing is sequential: the consumer reads Redis with `count=1`, so Pegasus jobs
occupy the worker for up to two minutes while the next video waits in `QUEUED`.

**S3 key collision:** `annotation.json` has no pipeline name in its S3 key, so
`pegasus_analyze` and `pegasus_segment` both write to the same object. When the
second pipeline to run completes, it overwrites the first in S3 AND overwrites the
working annotation in the database (destroying any user edits via `upsert_working_annotation`).
The `inferences` table does preserve separate rows for each `(video_id, pipeline)` pair,
so the raw model results are kept per pipeline — only the shared working annotation
is lost.

---

## ML Pipeline

Recommended conceptual pipeline:

```text
video
  -> coarse video understanding / action segmentation
  -> temporal boundary refinement
  -> action classification
  -> object detection/grounding
  -> keyframe selection
  -> confidence scoring
  -> final annotation JSON
```

Initial model stack can be kept pluggable; do not hard-code model logic into Backend.

---

## UI

Main screens:

```text
/login
/projects
/projects/{id}
/videos/{id}
```

Video page:

```text
Video player
Timeline with action segments
Annotation editor
Keyframe preview
Action/object fields
Previous / Next video
Export JSON / CSV
```

User edits automatically generated annotations rather than filling them from scratch.

---

## Core design principles

1. **Backend owns business state.**
2. **S3 owns video files.**
3. **Redis owns job delivery only.**
4. **ML service owns preprocessing + inference.**
5. **Video bytes never go through Backend or Redis.**
6. **One video = one task.**
7. Keep architecture simple; no Kafka/RabbitMQ/Celery/multiple worker services.
8. All model-specific logic stays isolated inside `ml-service`.
