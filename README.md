# Boundr

Web application for automatic annotation of short human-action videos.

Upload a 5–30 second clip, and Boundr splits it into individual actions, assigns
temporal boundaries, an action type, an object and a keyframe to each step, and hands
you an editable timeline. You review the draft, fix what the model got wrong, and
export to JSON or CSV.

The point is not to remove the annotator from the loop. It is to change their job from
*producing* an annotation to *checking* one — which is where the time savings come from.

**Status:** the end-to-end product loop works — auth, projects, upload, queue, editor,
export. The inference step currently runs a stub that returns correctly shaped
segments; real models are being selected in a separate research repository and plug in
behind a single interface. See [Project overview](docs/project-overview.md) for an
honest account of what is and is not done.

---

## Quick start

```bash
cp .env.example .env
docker compose up -d
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| Adminer (database) | http://localhost:8080 |
| Redis Commander (queue) | http://localhost:8081 |

Register a user in the UI, create a project, define the action and object vocabularies
for it, upload a clip, and press **Run model**.

Database migrations run automatically on backend startup. To run them by hand:

```bash
docker compose exec backend alembic upgrade head
```

---

## Architecture at a glance

```text
Browser (React + TypeScript + Vite)
    │ REST
    ▼
Backend (FastAPI)
    ├── PostgreSQL   — users, projects, videos, jobs, annotations, inferences
    ├── Redis Stream — ML job queue
    └── S3 / MinIO   — source videos and annotation artifacts
                          ▲
Redis Stream ──► ML Service (consumer + HTTP API)
                  download from S3 → ffmpeg → inference → post-processing
                  → store result → callback to Backend
```

Five rules the design rests on:

1. **Backend owns business state.** Redis only delivers jobs.
2. **Video bytes never pass through Backend or Redis.** Upload goes browser → S3 via a
   presigned URL; the ML service pulls the file from S3 directly.
3. **Redis Streams, not a list.** A consumer group with `XACK` means a job survives an
   ML-service restart.
4. **All model-specific logic stays inside `ml-service`.** The backend knows nothing
   about fps, window size or checkpoint names.
5. **One video = one annotation task.** Simple for the user, simple in the schema.

We deliberately skipped Kafka/RabbitMQ/Celery and a separate worker service: for this
scale that is over-engineering, and Redis Streams already gives the delivery guarantee
we need.

Details: [docs/architecture.md](docs/architecture.md).

---

## Repository layout

```text
backend/      FastAPI service — API, auth, persistence, export
frontend/     React + TypeScript UI — timeline, annotation editor
ml-service/   Redis consumer + inference pipelines
infra/        MinIO CORS configuration
docs/         Project, product and engineering documentation
```

Inference pipelines live in `ml-service/app/inference/<name>/infer.py`. Adding one
means implementing a single `infer()` method on the `Inference` base class — no backend
or frontend changes required.

---

## Annotation contract

```json
{
  "start_ms": 2000,
  "end_ms": 5100,
  "action": "move",
  "object": "part",
  "keyframe_ms": 3800,
  "confidence": 0.87,
  "model_version": "pipeline-0.3"
}
```

Validated on the way in: field types, `start_ms < end_ms`,
`start_ms ≤ keyframe_ms ≤ end_ms`, `confidence ∈ [0,1]`, and containment within the
clip duration. Every result is tagged `OK` / `SCHEMA_ERROR` / `INVALID_JSON`, and the
raw model response is always kept — even one that failed to parse.

The contract was frozen *before* any model was chosen. That is why swapping the
pipeline touches neither the backend nor the frontend.

---

## Documentation

| Document | What is in it |
|---|---|
| [Project overview](docs/project-overview.md) | Problem, approach, what is built, results, limitations, roadmap |
| [Architecture](docs/architecture.md) | Services, storage, job lifecycle, API surface |
| [Diagrams](docs/diagrams.md) | Architecture, job states, ML pipeline, entity relationships |
| [Database schema](docs/database.md) | Every table, column, constraint, index, enum and migration |
| [Object storage](docs/storage.md) | S3/MinIO key layout, presigned URL flows, CORS, deletion |
| [Design spec](docs/design_spec.md) | Colour system, typography, components, accessibility |
| [Product docs](docs/product/) | User, hypothesis, MVP scope, success criteria, risks |
| [Data examples](docs/data-examples/) | Export formats and format guarantees |

The project overview and the product documents are in Russian; everything else is in
English. Each document is maintained in one language only.


---

## API surface

```text
POST   /api/auth/register            POST   /api/videos/{id}/process
POST   /api/auth/login               GET    /api/jobs/{id}
GET    /api/auth/me
                                     GET    /api/videos/{id}/annotation
GET    /api/projects                 PUT    /api/videos/{id}/annotation
POST   /api/projects                 GET    /api/videos/{id}/export?format=json|csv
GET    /api/projects/{id}
PATCH  /api/projects/{id}            POST   /api/internal/jobs/{id}/status
DELETE /api/projects/{id}            POST   /api/internal/jobs/{id}/complete
                                     POST   /api/internal/jobs/{id}/fail
GET    /api/projects/{id}/videos
POST   /api/projects/{id}/videos     GET    /health
```

`POST /projects/{id}/videos` creates the video record and returns a presigned upload
URL. Internal endpoints are for ML-service callbacks and require the shared
`INTERNAL_API_TOKEN`.

---

## Configuration

Copy `.env.example` to `.env`. The defaults work out of the box for local development;
change `JWT_SECRET` and `INTERNAL_API_TOKEN` before exposing anything.

The `pegasus_analyze` and `pegasus_segment` pipelines require a TwelveLabs API key.
Register at https://playground.twelvelabs.io, copy the key (format: `tlk_...`) from
Dashboard → API Key, and set it in `.env` as `TWELVELABS_API_KEY`. Without the key,
Pegasus jobs will fail with an explicit message, but other pipelines work normally.

---

## License and scope

Built for the "Automatic video action annotation" hackathon case. Out of scope by the
case terms: robot control, ROS and simulators, 3D trajectories, force and contact
estimation, training a large model from scratch, integrations with internal systems,
production load, user roles and billing.
