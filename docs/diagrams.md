# Diagrams


## 1. Service architecture

```mermaid
flowchart TB
    UI["Frontend<br/>React + TypeScript + Vite"]
    BE["Backend<br/>FastAPI"]
    PG[("PostgreSQL<br/>users · projects · videos<br/>jobs · annotations · inferences")]
    RD[["Redis Stream<br/>ML job queue"]]
    S3[("S3 / MinIO<br/>videos · artifacts")]
    ML["ML Service<br/>consumer + HTTP API"]

    UI -->|REST| BE
    UI -.->|"presigned URL<br/>video goes direct"| S3
    BE --> PG
    BE -->|XADD| RD
    BE -->|presigned URL| S3
    RD -->|XREADGROUP| ML
    ML -->|download| S3
    ML -->|"status callbacks<br/>/api/internal/jobs/*"| BE
```

What matters here:

- Video **never passes** through the backend or Redis — only through S3 via presigned URLs.
- Redis delivers jobs; the backend is the source of truth for state.
- A consumer group with `XACK`: a job is not lost when the ML service restarts.
- All model specifics stay inside `ml-service`.

A raster version of this diagram: [architecture.png](architecture.png).

---

## 2. Job lifecycle

```mermaid
stateDiagram-v2
    [*] --> UPLOADING: video record created
    UPLOADING --> UPLOADED: file uploaded to S3
    UPLOADED --> QUEUED: POST /videos/{id}/process
    QUEUED --> PROCESSING: ML picked the job off the stream
    PROCESSING --> COMPLETED: annotation stored
    PROCESSING --> FAILED: pipeline error
    FAILED --> QUEUED: retry
    COMPLETED --> QUEUED: re-run with another pipeline
    COMPLETED --> [*]
```

The annotation carries its own separate status: `GENERATED` (came from the model) →
`EDITED` (the user changed it). This distinguishes human-verified annotation from
unverified — material for dataset quality.

---

## 3. ML pipelines in the MVP

Two pipelines are being prepared for the MVP, in parallel and independently. Both take a
video and emit the same contract JSON, so the product does not depend on which one a
project uses — the pipeline is chosen by name per job.

```mermaid
flowchart LR
    V["video 5-30 s"] --> FF["ffmpeg / ffprobe<br/>duration, fps, frames"]

    FF --> M["Marlin-2B<br/>dense captioning<br/>+ temporal grounding"]
    FF --> P["TwelveLabs Pegasus<br/>hosted video LLM"]

    M --> PARSE["parse events[]<br/>start / end / description"]
    PARSE --> MAP["map description<br/>-> action + object"]

    P --> PP["parse json_schema<br/>or segment_definitions"]

    MAP --> KF["keyframe selection"]
    PP --> KF
    KF --> OUT["contract JSON"]

    style M stroke-dasharray: 5 5
```

**`marlin2b` (dashed — in preparation).** The open video-VLM
[`NemoStation/Marlin-2B`](https://huggingface.co/NemoStation/Marlin-2B) (Apache 2.0) runs
locally: no external API, no per-clip cost, no geo-blocking. It emits events with
second-precise timestamps in one pass. Sampling is 2 FPS, which bounds boundary precision
at roughly 0.5 s.

**`pegasus_analyze` / `pegasus_segment` (implemented).** A hosted TwelveLabs model, one
package with two modes: `general` with a `json_schema` response and a real `prompt`, and
`time_based_metadata` (SME) which segments the video itself and rejects the `prompt`
parameter — there the whole prompt lives in the segment definition description. In
practice the two trade off against each other: SME segments more finely, `general`
reasons over the whole clip and picks better verbs.

The two branches are deliberately not merged. They fail for unrelated reasons — a local
model against a hosted API — so keeping both is the cheapest insurance available.

### The extension point

Neither branch is privileged. A pipeline is a package under `ml-service/app/inference/`
implementing one `infer()` method, registered by name:

```mermaid
flowchart LR
    JOB["job<br/>pipeline: name"] --> REG{{"PIPELINES<br/>registry"}}
    REG --> O["overlap · dense<br/>sequential<br/>(stubs)"]
    REG --> PG["pegasus_analyze<br/>pegasus_segment"]
    REG --> MR["marlin2b"]
    REG --> NEXT["...<br/>next model"]

    O --> BASE["Inference.run()<br/>ffprobe, contract shape"]
    PG --> BASE
    MR --> BASE
    NEXT --> BASE
    BASE --> OUT["contract JSON"]

    style MR stroke-dasharray: 5 5
    style NEXT stroke-dasharray: 5 5
```

Adding a model touches neither the backend nor the frontend: they know a pipeline name
and a version integer, nothing more. This has already been exercised — Pegasus was added
without a single change outside `ml-service`.

**Dropped: the TW-FINCH hybrid.** Earlier plans routed embeddings through TW-FINCH
clustering with temporal weighting to get boundaries, then attached names with a separate
LLM call. That chain is not part of the MVP. Both surviving pipelines produce boundaries
and labels in one pass, which makes the segmentation-plus-labelling split redundant. The
research behind it is recorded in the project overview, §6.

---

## 4. What works today and what is a stub

```mermaid
flowchart LR
    subgraph GREEN["Real loop"]
        A["Upload<br/>presigned S3"] --> B["Queue<br/>Redis Streams"]
        B --> C["States<br/>and callbacks"]
        E["Contract<br/>validation"] --> F["Editor<br/>timeline"]
        F --> G["Export<br/>JSON / CSV"]
    end
    subgraph INF["Inference"]
        D1["pegasus_analyze<br/>pegasus_segment<br/>real model"]
        D2["marlin2b<br/>in preparation"]
        D3["overlap · dense · sequential<br/>synthetic segments"]
    end
    C --> INF --> E

    style D2 stroke-dasharray: 5 5
```

The Pegasus pipelines are real inference: the video is uploaded to TwelveLabs, analysed,
and the reply is mapped onto the contract. `marlin2b` is being prepared on a separate
branch. The three original pipelines remain as stubs — they return synthetic segments
with a correct structure and the right duration, reading real metadata through `ffprobe`,
so the whole file-handling path stays exercised without spending an API call. They are
useful for testing the loop and are not scheduled for removal.

---

## 5. Data model

```mermaid
erDiagram
    users ||--o{ projects : owns
    projects ||--o{ videos : contains
    videos ||--o{ jobs : "was processed by"
    videos ||--o{ inferences : "model outputs"
    videos ||--o| annotations : "working annotation"

    projects {
        jsonb action_types "action vocabulary"
        jsonb objects "object vocabulary"
    }
    jobs {
        string pipeline
        enum status "QUEUED PROCESSING COMPLETED FAILED"
    }
    inferences {
        string pipeline
        int model_version
        jsonb data "raw model output"
    }
    annotations {
        jsonb data "annotation"
        enum status "GENERATED EDITED"
        int version
    }
```

**The key decision:** `inferences` and `annotations` are separate. Raw model outputs are
stored apart from the working annotation, one row per `(video_id, pipeline)`. That lets
one clip be run through several *different* pipelines and compared without losing the
user's edits.

Note what this does **not** give you: two results from the *same* pipeline cannot
coexist. `upsert_inference()` looks the row up by `(video_id, pipeline)` alone and
overwrites it, recording the new `model_version` in place — so bumping a pipeline's
version and re-running destroys the previous result. Full schema, including the fix if
version-to-version comparison becomes necessary: [database.md](database.md).
