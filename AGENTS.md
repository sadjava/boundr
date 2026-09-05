# AGENTS.md

Working notes for coding agents in this repository. Read this before changing anything.
`CLAUDE.md` is a symlink to this file — edit `AGENTS.md`, never the symlink.

Boundr is a web application for automatic annotation of short human-action videos: a clip
goes in, a draft annotation comes out, the user corrects it on a timeline and exports
JSON or CSV. Product context is in [docs/project-overview.md](docs/project-overview.md);
this file is about how to work in the codebase.

---

## Commands

Everything runs through Docker Compose. There is no local dev setup outside it.

```bash
cp .env.example .env
docker compose up -d                       # full stack
docker compose up -d --build ml-service    # apply any source change to one service
docker compose logs -f ml-service          # follow a service
```

**`restart` does not apply code edits.** No service bind-mounts its source: `backend`,
`ml-service` and `frontend` all have a bare `build:`, so the code is copied into the
image at build time. `docker compose restart` brings the container back up from the
*old* image and your change silently does not run. Always rebuild:

```bash
docker compose up -d --build <service>
```

After rebuilding, confirm the change actually landed before drawing conclusions from
the behaviour — the failure mode here is invisible:

```bash
docker compose exec ml-service grep -c "<a string from your edit>" <path/inside/app>
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| Adminer | http://localhost:8080 |
| Redis Commander | http://localhost:8081 |

Migrations run automatically on backend startup (`alembic upgrade head` in the
container `CMD`). To create one:

```bash
docker compose exec backend alembic revision -m "short description"
docker compose exec backend alembic upgrade head
```

Write migrations by hand. Do not use `--autogenerate` here: the models use native
PostgreSQL enums, and autogenerate produces migrations that fail on enum changes.

Frontend:

```bash
cd frontend && npm run build     # tsc -b && vite build — the type check that matters
```

---

## Testing

There is no pytest suite in this repository. The convention is a
`if __name__ == "__main__":` block at the bottom of a module, asserting its own
invariants. Run them directly:

```bash
docker compose exec backend python -m app.segment       # annotation coercion rules
docker compose exec backend python -m app.labels        # vocabulary normalisation
docker compose exec ml-service python -m app.inference  # every registered pipeline
```

Each prints `ok` on success. Follow this pattern for new pure-logic modules: no network,
no database, fast enough to run on every edit. `app.inference` also builds a one-second
video with ffmpeg and runs a pipeline end to end — use it as the template for anything
that touches media.

If you add such a block, add the command to the list above.

New tests are written with pytest and live in `ml-service/tests/`. They run inside
the container from `/app`, so the `app` package is importable without a
`conftest.py`:

```bash
docker compose exec ml-service python -m pytest tests/ -q
```

The two conventions coexist deliberately: existing `__main__` self-tests stay where
they are, new tests go to `tests/`. Note that the listed
`docker compose exec ml-service python -m app.inference` does **not** run —
`app/inference/` is a package without a `__main__.py`, so the block at the bottom of
its `__init__.py` is unreachable and its assertions are not covered anywhere.

Annotation quality is measured by a standalone script outside Docker. It compares
predicted annotations with reference ones and checks them against the case
thresholds — see [eval/README.md](eval/README.md). Its own suite is pytest:

```bash
cd eval && python -m pytest tests/ -q
```

`eval/assets/` holds synthetic annotations used to exercise the script end to end;
`eval/data/` is for real data and is not tracked.

---

## Architecture invariants

Do not violate these without saying so explicitly. They are what the design rests on and
several of them are load-bearing in non-obvious ways.

1. **The backend owns business state.** Redis only transports jobs; it is never the
   source of truth. Never read state back out of Redis to decide anything.
2. **Video bytes never pass through the backend or Redis.** Upload is browser → S3 via a
   presigned URL; the ML service pulls the object from S3 itself. Never proxy a file
   through FastAPI, and never put media in a Redis message.
3. **Model specifics stay inside `ml-service`.** The backend must not learn about fps,
   window sizes, checkpoints or frame counts. It knows a pipeline name and a version
   integer, nothing more.
4. **The annotation contract is frozen.** `{id, start, end, action, object, keyframe}` in
   seconds on the product boundary. Changing it means changing the ML service, the
   backend schema, the frontend and the export at once — do not do it casually.
5. **One video = one annotation task.** Do not introduce many-to-one relationships
   between videos and annotations.
6. **No new infrastructure.** No Kafka, RabbitMQ, Celery or extra worker services. Redis
   Streams with a consumer group is deliberate and sufficient.

---

## Code map

```text
backend/app/
  main.py          FastAPI app, router registration
  models.py        SQLAlchemy models — the schema source of truth
  schemas.py       Pydantic request/response models
  segment.py       AnnotationSegment: validates and repairs annotation data
  labels.py        Vocabulary normalisation
  services.py      Shared logic: ownership checks, upserts, job creation
  queue.py         Redis Stream producer
  s3.py            Key construction, presigned URLs, bucket lifecycle
  security.py      bcrypt hashing, JWT issue/verify
  routers/         auth, projects, videos, jobs, annotations, internal
  alembic/         Migrations

ml-service/app/
  consumer.py      Redis consumer loop: download → run → upload → callback
  inference/       Pipelines (see below)
  project.py       Reads project vocabularies straight from PostgreSQL
  backend_client.py  Status callbacks to the backend
  s3.py            Download/upload, key derivation

frontend/src/
  pages/           Login, Projects, ProjectCreate, ProjectDetail, VideoPage
  components/      Timeline, RangeSlider, Layout, StatusBadge, ConfirmDialog
  api.ts           Typed fetch wrapper, JWT handling, export download
  types.ts         Shared types — keep in sync with backend/app/schemas.py
```

---

## Adding an inference pipeline

**This is how model inference gets implemented in this project: a new package under
`ml-service/app/inference/`, mirroring the existing ones.** Do not add model code
anywhere else, and do not extend an existing pipeline in place when the behaviour is
genuinely different — add a package, so old results stay reproducible.

`overlap`, `dense` and `sequential` are stubs that return synthetic segments with a
correct structure. They exist to exercise the loop and are staying — they let you test
the queue without spending an API call. The real pipelines are the two MVP branches:
`pegasus_analyze` / `pegasus_segment` (implemented) and `marlin2b` (in preparation on a
separate branch). Expect more: the registry is the scaling point, so adding a model means
adding a package, never editing an existing one.

### Steps

1. Create `ml-service/app/inference/<name>/` with `__init__.py` and `infer.py`.

2. In `infer.py`, subclass `Inference` from `app.inference.base` and implement `infer`:

   ```python
   from __future__ import annotations

   from app.inference.base import Inference, JobContext, VideoMeta


   class MyInference(Inference):
       name = "my_pipeline"
       version = 1

       def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
           ...
   ```

3. Re-export the class from the package `__init__.py`:

   ```python
   from app.inference.my_pipeline.infer import MyInference

   __all__ = ["MyInference"]
   ```

4. Register it in `ml-service/app/inference/__init__.py` under `PIPELINES`, keyed by the
   string the API will accept.

5. Extend the self-test at the bottom of that same `__init__.py` with assertions about
   the new pipeline's output.

**Exception: `inference/pegasus/`.** The two TwelveLabs pipelines
(`pegasus_analyze`, `pegasus_segment`) share one package instead of having one each.
They differ in the `response_format` they send, the `analysis_mode` they request, how
they parse the reply, and the prompt text; the SDK client, the prompt builder and
the mapping to the annotation contract are shared. Splitting them would duplicate
that code or push it to a third place. This is deliberate — do not "fix" it by
splitting the package.

### The contract you must satisfy

- **Never override `run()`.** The base class calls `ffprobe`, fills in `video_path`, and
  wraps your segments into `{video_id, duration, fps, segments}`. Overriding it breaks
  the response shape the backend expects.
- **Return a list of segment dicts** shaped by `make_segment()`: `id` (uuid4 string),
  `start`, `end`, `keyframe` in **seconds** (not milliseconds — the research repository
  uses ms, the product does not), `action` and `object` as strings. Use `make_segment()`
  rather than building dicts by hand; it rounds consistently and places the keyframe.
- **`start ≤ keyframe ≤ end`.** The backend clamps violations silently, so a bug here
  will not raise — it will just produce quietly wrong annotations.
- **Respect the project vocabulary.** `ctx.action_types` and `ctx.objects` are either a
  list of allowed labels or `None`. **`None` means open vocabulary and is the primary
  case** — do not treat it as an error or substitute a default list without saying so.
- **`ctx.video_path` is a real local file** already downloaded from S3. Use
  `extract_frames(ctx.video_path, dest_dir, fps=...)` for frames; it shells out to ffmpeg
  and returns sorted jpeg paths. Clean up temporary directories yourself.
- **Bump `version` when output changes meaningfully.** The backend reads it from
  `GET /inference/{name}` on the ML service and stores it with the result.
- **Raise on failure.** The consumer catches exceptions, reports `FAILED` with the
  traceback and acks the message. Do not swallow errors and return empty segments — a
  silent empty annotation looks like a working pipeline that found nothing.

### Heavy models

`ml-service/requirements.txt` currently has no torch or transformers — the stubs do not
need them. A real pipeline will add heavy dependencies and a model download; expect the
image to grow and the first run to be slow. Keep model loading out of import time so the
consumer starts immediately and one broken pipeline does not take the service down.

Run any heavy training or bulk inference under `systemd-run` with explicit resource
limits, so an OOM does not take the SSH session with it.

---

## Conventions

**Python.** `from __future__ import annotations` at the top of new modules. Modern type
hints (`str | None`, `list[dict]`). Lines up to ~100 characters. No linter or formatter
is configured — match the surrounding style rather than reformatting files. Comments are
sparse and explain *why*, not *what*; do not add narration.

**TypeScript.** Strict mode, no `any`. Double quotes, semicolons, two-space indent.
Types in `types.ts` mirror `backend/app/schemas.py` — change both together.

**API.** Public routes are `/api/...` and require a JWT. ML callbacks are
`/api/internal/...` and require the shared `INTERNAL_API_TOKEN`. Ownership is checked via
`get_project_for_user` / `get_video_for_user`, which 404 rather than 403 on someone
else's data. Keep it that way: it does not leak the existence of other users' records.

**Migrations.** One migration per schema change, hand-written, with a working
`downgrade()`.

---

## Documentation upkeep

**After any change, update the documentation if the change makes it wrong.** Stale
documentation is worse than none: it is trusted and then it lies. In particular:

| If you change | Update |
|---|---|
| Models or migrations | [docs/database.md](docs/database.md) |
| S3 keys, presigning, CORS, deletion | [docs/storage.md](docs/storage.md) |
| Services, queue, job lifecycle, API | [docs/architecture.md](docs/architecture.md), [docs/diagrams.md](docs/diagrams.md) |
| Inference pipelines or the ML approach | [docs/project-overview.md](docs/project-overview.md) §4–5 |
| Export format | [docs/data-examples/](docs/data-examples/) |
| Metrics, matching rules, the judge | [eval/README.md](eval/README.md) |
| UI colours, components, states | [docs/design_spec.md](docs/design_spec.md) |
| Setup, ports, commands | [README.md](README.md) and this file |

Language split: engineering documents are in **English**; the project overview and the
product documents in `docs/product/` are in **Russian**. Each document is maintained in
one language only — do not create parallel translations, they drift.

If a change reveals that existing documentation was already wrong, fix it in the same
change and say so in the commit message.

---

## Commits

**Conventional Commits.** Every message starts with a type:

```text
<type>: <imperative summary in lower case, no trailing period>

<body: what changed and why, wrapped at ~72 characters>
```

| Type | Use for |
|---|---|
| `feat` | New user-visible capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Restructuring with no behaviour change |
| `perf` | Performance work |
| `test` | Self-check blocks and test fixtures |
| `build` | Dependencies, Dockerfiles, compose |
| `chore` | Tooling and housekeeping |

A scope is optional and useful when the change is confined:
`feat(ml-service): add marlin pipeline`, `fix(frontend): keep keyframe inside segment`.

Rules:

- **Commit only when the user asks.** Propose a message and let them approve it.
- **Small, logical commits.** Each one is a step of reasoning that must be readable later.
  Do not bundle unrelated changes.
- **Do not amend, squash or rebase** already-created commits without being asked.
- **The user is the sole author.** Never add a `Co-Authored-By` trailer, a "generated
  with" line, or any other mention of Claude, Anthropic or an AI assistant — not in
  commit messages, pull request descriptions or issues.
- Explain non-obvious behaviour in the body. If the change works around something
  surprising, the commit message is the right place to record it.

---

## Gotchas

Things that have already cost time here.

- **Re-running a pipeline destroys user edits.** `upsert_working_annotation` overwrites
  `annotations.data` and resets the status to `GENERATED`.
- **`inferences` is unique on `(video_id, pipeline)`** — not on `model_version`. Two
  results from the same pipeline cannot coexist; the newer one overwrites the older.
- **`annotation.json` has no pipeline in its S3 key,** so inference rows for different
  pipelines can point at the same object, containing whichever ran last.
- **The video object key is hardcoded to `original.mp4`** regardless of the uploaded
  container. MOV uploads are stored under an `.mp4` name.
- **Two S3 clients, on purpose.** `internal_s3()` for server-side calls,
  `public_s3()` for signing URLs the browser will use. Signing with the internal
  hostname produces URLs the browser cannot resolve.
- **`POST /jobs` on the ML service hardcodes `pipeline: "overlap"`.** The real path is
  the backend's own producer in `queue.py`, which passes the requested pipeline. That
  endpoint is a debugging convenience and lies about pipeline selection.
- **Enum changes need `ALTER TYPE`.** Adding a value to `VideoStatus`, `JobStatus` or
  `AnnotationStatus` in Python without a migration will fail at runtime, not at startup.
- **No hot reload, and `restart` is not enough.** Both Python services run without
  `--reload`, and neither mounts its source, so a restart re-runs the old image.
  Rebuild with `docker compose up -d --build <service>`. This has already cost time:
  a prompt change looked like it had no effect on the model output, when in fact the
  container was still running the previous prompt.
- **Pegasus jobs block the consumer for minutes.** The consumer reads with `count=1`,
  so videos are processed one at a time; the next job sits in `QUEUED` meanwhile.
  `TIMEOUT` is a class attribute on each pipeline, not a setting.
- **`TWELVELABS_API_KEY` is required for the Pegasus pipelines.** Without it a job
  fails with an explicit message rather than a 401 from the API.

---

## Out of scope

Set by the hackathon case. Do not add, even if it seems natural: robot control, ROS and
simulators, 3D trajectories, force and contact estimation, training a large model from
scratch, integrations with internal company systems, production load handling, user roles
and permissions, billing.
