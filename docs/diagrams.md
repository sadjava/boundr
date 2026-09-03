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

## 3. ML pipeline: hybrid configuration

```mermaid
flowchart LR
    V["video 5–30 s"] --> FF["ffmpeg<br/>normalise, fps 16"]
    FF --> EMB["embeddings<br/>sliding window"]
    EMB --> CACHE[("feature cache<br/>.npz")]
    EMB --> SEG["TW-FINCH<br/>clustering with<br/>temporal weighting"]
    SEG --> POST["post-processing<br/>merge short segments"]
    POST --> LBL["multimodal LLM<br/>action and object names"]
    LBL --> KF["keyframe selection"]
    KF --> OUT["contract JSON"]

    style LBL stroke-dasharray: 5 5
```

The dashed block is the one blocked by external API access (Gemini geo-blocking, balance
requirements). Everything else is implemented and has been run. For an alternative to that
block with no external APIs, see 3b.

**Division of labour between tracks (in the hybrid):** segmentation supplies accurate
temporal boundaries — it sees transitions in motion and invents nothing. The LLM attaches
names to finished intervals, which segmentation cannot do by construction
(`action="segment"`, `object="cluster_N"`).

---

## 3b. Alternative: one model instead of a pipeline

```mermaid
flowchart LR
    V["video 5–30 s"] --> FF["ffmpeg<br/>2 FPS, ≤448×448"]
    FF --> M["Marlin-2B<br/>dense captioning<br/>+ temporal grounding"]
    M --> PARSE["parse events[]<br/>start / end / description"]
    PARSE --> MAP["map description<br/>→ action + object"]
    MAP --> KF["keyframe selection"]
    KF --> OUT["contract JSON"]

    style M stroke:#DCC3AA
```

The open video-VLM Marlin-2B (Apache 2.0) emits events with second-precise timestamps in
a single pass, potentially replacing the whole "embeddings → clustering → LLM labelling"
chain. A trial run has been performed; quality on our task is unmeasured.

The fork is settled by one run against ground truth: if Marlin's boundaries land within
2 s, this scheme wins; if not, the hybrid from §3 stays, with Marlin supplying names only.
Both variants write the same JSON, so the product does not depend on the choice.

---

## 4. What works today and what is a stub

```mermaid
flowchart LR
    subgraph GREEN["✅ Real loop"]
        A["Upload<br/>presigned S3"] --> B["Queue<br/>Redis Streams"]
        B --> C["States<br/>and callbacks"]
        E["Contract<br/>validation"] --> F["Editor<br/>timeline"]
        F --> G["Export<br/>JSON / CSV"]
    end
    subgraph YELLOW["🟡 Stub"]
        D["Inference<br/>mock_segments"]
    end
    C --> D --> E
```

The stub returns segments with a correct structure and the right duration — it reads real
video metadata through `ffprobe` and extracts a frame through `ffmpeg`, so the whole
file-handling path is exercised — but the content is synthetic.

Replacing the stub with a real model means implementing one `infer()` method on the
abstract `Inference` class. Neither the backend nor the frontend changes.

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
