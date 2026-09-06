# Marlin through llama.cpp

Marlin is Boundr's default experimental local inference pipeline. It captions a
video with `NemoStation/Marlin-2B` through a pinned llama.cpp CUDA server, then
converts the timed English captions into Boundr action/object segments.

## Start

```bash
cp .env.example .env
docker compose up -d --build
```

The setup requires an NVIDIA GPU supported by CUDA 12.8 and NVIDIA Container Toolkit.
The build uses llama.cpp's default GPU targets. Optionally set `CUDA_ARCH` in `.env`
to compile for a specific architecture; no architecture is forced by default.

On first start, llama.cpp downloads about 5.5 GiB of GGUF files. Compose creates
`./models/marlin/` automatically and subsequent container recreations reuse it.
`MARLIN_MODELS_DIR` and `MARLIN_PORT` are configurable in `.env`.

The llama.cpp API is available at `http://127.0.0.1:8085`; Boundr uses the same
server through the Compose network. This development endpoint has no API key and
allows browser requests, so keep it on loopback. Remove its `ports` entry or add
authentication before deploying on a shared or untrusted host.

## Current pipeline

```text
video
  -> validate duration
  -> sample at 2 FPS to a temporary lossless clip
  -> Marlin caption through llama.cpp
  -> parse timed human-object manipulations (spaCy, or GPT-4o-mini)
  -> Boundr timeline segments
```

[`infer.py`](../ml-service/app/inference/marlin/infer.py) owns sampling and model
inference. It:

- accepts finite, positive durations up to 120 seconds;
- selects endpoint-preserving source frames, capped at 240 frames;
- encodes a temporary 2 FPS FFV1 clip with ffmpeg;
- sends the clip to llama.cpp with greedy decoding and a 2,048-token output cap;
- rescales returned timestamps for any small sampled-duration difference.

The temporary lossless clip is read and Base64-encoded in memory. High-resolution
inputs can therefore use substantial worker RAM even though llama.cpp resizes model
frames later.

[`postprocess.py`](../ml-service/app/inference/marlin/postprocess.py) is a separate,
replaceable callable with this shape:

```python
(text, model_duration, job_context) -> segments
```

The default `marlin` implementation is deterministic and local. A tolerant regular
expression reads Marlin's timestamp envelopes; the pinned spaCy English dependency
model finds human predicates, verb particles, and manipulated noun phrases. It handles
common active/passive, coordination, pronoun, and complement forms without another
LLM call.

`marlin_gpt` is a second pipeline in the same package. It uses the same captioning
step, then asks GPT-4o-mini through OpenRouter to emit Boundr `{start, end, action,
object}` segments. It needs `OPENROUTER_API_KEY`. Catalog labels, when set, are
matched by normalized spelling; unmatched items are dropped.

With empty project catalogs, extracted verb lemmas and object phrases remain
open-vocabulary. With configured catalogs, only matching action/object labels are
kept. Marlin results bypass the existing inference cache because those project catalogs
can change without changing the cache key.

Several small policy sets remain intentional: human actor words, non-manipulation
verbs, and compatibility synonyms for project catalogs. Dependency syntax cannot prove
physical contact, so open-vocabulary filtering is best effort. The parser also cannot
repair an object or action that Marlin did not describe correctly.

## llama.cpp configuration

The server currently runs with:

```text
--video-fps 2
--image-max-tokens 192
--ctx-size 32768
--video-timestamp-interval 1000
--no-cache-prompt
```

There is no `--parallel` / `-np` override. In a measured maximum-length run on an
RTX 4090, a 120-second, 240-frame clip used 22,742 prompt tokens and 412 completion
tokens. The 32,768-token context leaves room for the request's 2,048-token maximum
completion; the server process used about 5,486 MiB of GPU memory.

llama.cpp can log `non-consecutive token position` warnings for these requests because
the Qwen video format repeats multimodal position values. Fresh one-shot requests still
complete normally.

The image pins llama.cpp commit
`c5a5535e6ebc2e74ab0e3f1b249d7d989aba26a2`. The small patch in
[`qwen-video-format.patch`](../infra/marlin-server/qwen-video-format.patch) emits the
video timestamp/token layout expected by Qwen-family video models and suppresses a
timestamp after the final known frame. No prompt or output-content patch is applied.

The model files are pinned to Hugging Face revision
`7adc757f40191098ac3c5f286847a20088d1f6ac`:

| File | SHA-256 |
|---|---|
| `marlin-2b-text.gguf` | `f3aaf619b346f43e7ecd79734a5af297d0aa4374a138f1bfad9a9c2880a1a4ed` |
| `marlin-2b.gguf` | `ed14d6f1573cf75234e2d7d64fab30f1441bafbd0f965b2ad402ca116b79d844` |

## Limits

- Videos longer than 120 seconds are rejected instead of sampled more sparsely.
- The 2 FPS input timeline limits useful boundary precision to roughly 0.5 seconds.
- Caption correctness is model-dependent; deterministic parsing only maps what Marlin
  says into the annotation contract.
- The default Compose stack waits for `marlin-server` health because Marlin is the
  selected default pipeline.

## Verification

```bash
docker compose config --quiet
docker compose up -d --build
docker compose exec ml-service python -m pytest tests -q
docker compose exec ml-service python -m app.inference.marlin.infer
docker compose exec ml-service python -m app.inference.marlin.postprocess
docker compose exec ml-service python -m app.inference.marlin.gpt_postprocess
curl -f http://127.0.0.1:8085/health
```
