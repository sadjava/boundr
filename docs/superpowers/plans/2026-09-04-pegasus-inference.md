# Pegasus Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить синтетические заглушки реальным инференсом TwelveLabs Pegasus в двух режимах — `pegasus_analyze` (JSON-схема) и `pegasus_segment` (сегментные определения).

**Architecture:** Один пакет `ml-service/app/inference/pegasus/` содержит общий клиент поверх официального SDK, общий маппинг ответа в контракт аннотаций и два класса `Inference` — по одному на режим. Консьюмер и бэкенд не меняются, кроме регистрации двух новых имён пайплайнов. Вся модельная специфика остаётся внутри `ml-service`.

**Tech Stack:** Python 3, FastAPI, официальный SDK `twelvelabs` (1.2.9), ffmpeg/ffprobe, Redis Streams, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-09-04-pegasus-inference-design.md](../specs/2026-09-04-pegasus-inference-design.md)

## Global Constraints

- Ветка работы — `feat/pegasus-inference`. Коммитить только по одобрению пользователя; единственный автор коммита — пользователь, никаких упоминаний ИИ-ассистента.
- Сообщения коммитов — Conventional Commits, тип и краткое описание в нижнем регистре без точки.
- Все новые Python-модули начинаются со строки `from __future__ import annotations`.
- Современные аннотации типов (`str | None`, `list[dict]`), строки до ~100 символов. Линтера нет — подражать окружающему стилю, не переформатировать чужие файлы.
- Комментарии редкие и объясняют «почему», а не «что».
- Тесты — блок `if __name__ == "__main__":` внизу модуля, печатающий `ok`. Pytest в репозитории нет.
- Контракт аннотации заморожен: `{id, start, end, action, object, keyframe}`, время в **секундах**.
- Инвариант: `start <= keyframe <= end`. Бэкенд молча чинит нарушения, поэтому ошибка здесь не всплывёт как исключение.
- `ctx.action_types` и `ctx.objects` равные `None` означают **открытый словарь — это основной случай**, а не ошибка.
- Не переопределять `Inference.run()`.
- Ошибки не глотать: пустой результат — исключение, а не пустой список сегментов.
- Модель имени: `model_name = "pegasus1.5"`, `temperature = 0.2`.
- Лимит прямой загрузки файла в TwelveLabs — 200 МБ.
- Хот-релоада нет: после правки Python-кода нужен `docker compose restart ml-service`.

---

### Task 1: Маппинг ответа в контракт аннотаций

Чистая логика без сети и без SDK. Делается первой, потому что от неё зависят оба режима, а протестировать её можно без ключа.

**Files:**
- Create: `ml-service/app/inference/pegasus/__init__.py`
- Create: `ml-service/app/inference/pegasus/mapping.py`

**Interfaces:**
- Consumes: `make_segment`, `JobContext` из `app.inference.base`.
- Produces:
  - `vocabulary_prompt(ctx: JobContext) -> str`
  - `to_segments(raw: list[dict], duration: float) -> list[dict]`
  - `parse_analyze_payload(payload: dict) -> list[dict]`
  - `parse_segment_payload(payload: dict | list) -> list[dict]`
  - Оба парсера возвращают «сырые» записи вида `{"action": ..., "object": ..., "start": ..., "end": ...}`, которые затем передаются в `to_segments`.

- [ ] **Step 1: Создать пустой `__init__.py` пакета**

Пока пустой — экспорты классов появятся в Task 3.

```bash
mkdir -p "ml-service/app/inference/pegasus"
touch "ml-service/app/inference/pegasus/__init__.py"
```

- [ ] **Step 2: Написать падающий self-test**

Создать `ml-service/app/inference/pegasus/mapping.py` **только** с этим блоком (без реализации), чтобы убедиться, что тест действительно падает:

```python
from __future__ import annotations


if __name__ == "__main__":
    ctx_open = JobContext(job_id="j", video_id="v", s3_key="")
    prompt_open = vocabulary_prompt(ctx_open)
    assert "pour" in prompt_open, "open vocab prompt should show example labels"

    ctx_closed = JobContext(
        job_id="j", video_id="v", s3_key="", action_types=["alpha"], objects=["thing"]
    )
    prompt_closed = vocabulary_prompt(ctx_closed)
    assert "alpha" in prompt_closed and "thing" in prompt_closed

    analyze_payload = {
        "actions": [
            {"action_type": "pour", "object": "cup", "start": 1.0, "end": 2.5},
            {"action_type": "push", "start": 3.0, "end": 4.0},
        ]
    }
    raw = parse_analyze_payload(analyze_payload)
    assert raw == [
        {"action": "pour", "object": "cup", "start": 1.0, "end": 2.5},
        {"action": "push", "object": None, "start": 3.0, "end": 4.0},
    ]

    segment_payload = {
        "id": "human_action",
        "segments": [
            {"action_type": "grab", "object": "bottle", "start": 0.5, "end": 1.5},
        ],
    }
    assert parse_segment_payload(segment_payload) == [
        {"action": "grab", "object": "bottle", "start": 0.5, "end": 1.5}
    ]
    assert parse_segment_payload([segment_payload, segment_payload]) == [
        {"action": "grab", "object": "bottle", "start": 0.5, "end": 1.5}
    ] * 2

    try:
        parse_segment_payload({"nonsense": 1})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown segment payload shape must raise")

    segs = to_segments(raw, duration=10.0)
    assert len(segs) == 2
    assert [s["action"] for s in segs] == ["pour", "push"]
    assert segs[0]["object"] == "cup"
    assert segs[1]["object"] == "", "missing object becomes empty string"
    assert all(s["start"] <= s["keyframe"] <= s["end"] for s in segs)
    assert all(isinstance(s["id"], str) and s["id"] for s in segs)

    ordered = to_segments(
        [
            {"action": "b", "object": "", "start": 5.0, "end": 6.0},
            {"action": "a", "object": "", "start": 1.0, "end": 2.0},
        ],
        duration=10.0,
    )
    assert [s["action"] for s in ordered] == ["a", "b"], "segments must be sorted by start"

    clipped = to_segments([{"action": "a", "object": "", "start": -1.0, "end": 99.0}], 10.0)
    assert clipped[0]["start"] == 0.0 and clipped[0]["end"] == 10.0

    dropped = to_segments(
        [
            {"action": "good", "object": "", "start": 1.0, "end": 2.0},
            {"action": "reversed", "object": "", "start": 5.0, "end": 4.0},
            {"action": "zero", "object": "", "start": 3.0, "end": 3.0},
            {"action": "", "object": "x", "start": 6.0, "end": 7.0},
            {"action": "bad_number", "object": "", "start": "x", "end": 8.0},
        ],
        duration=10.0,
    )
    assert [s["action"] for s in dropped] == ["good"]

    try:
        to_segments([], duration=10.0)
    except ValueError:
        pass
    else:
        raise AssertionError("empty result must raise, not return []")

    print("ok")
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `docker compose exec ml-service python -m app.inference.pegasus.mapping`
Expected: FAIL — `NameError: name 'JobContext' is not defined`

Если контейнер не запущен: `docker compose up -d ml-service`.

- [ ] **Step 4: Написать реализацию**

Вставить **над** блоком `if __name__ == "__main__":` в том же файле:

```python
from app.inference.base import JobContext, make_segment

OPEN_ACTION_HINT = (
    "Use concise lowercase verb labels for actions, for example pour, push, pick_up."
)
OPEN_OBJECT_HINT = (
    "Use concise lowercase nouns for objects. "
    "Leave the object empty if no object is involved."
)


def vocabulary_prompt(ctx: JobContext) -> str:
    """Build the vocabulary part of the prompt. None = open vocabulary (primary case)."""
    parts = []
    if ctx.action_types:
        parts.append("Use only these action labels: " + ", ".join(ctx.action_types) + ".")
    else:
        parts.append(OPEN_ACTION_HINT)
    if ctx.objects:
        parts.append("Use only these object labels: " + ", ".join(ctx.objects) + ".")
    else:
        parts.append(OPEN_OBJECT_HINT)
    return " ".join(parts)


def parse_analyze_payload(payload: dict) -> list[dict]:
    actions = payload.get("actions") if isinstance(payload, dict) else None
    if not isinstance(actions, list):
        keys = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise ValueError(f"unexpected analyze payload, no 'actions' list: {keys}")
    return [
        {
            "action": item.get("action_type"),
            "object": item.get("object"),
            "start": item.get("start"),
            "end": item.get("end"),
        }
        for item in actions
        if isinstance(item, dict)
    ]


def parse_segment_payload(payload: dict | list) -> list[dict]:
    groups = payload if isinstance(payload, list) else [payload]
    seen_segments_key = False
    raw: list[dict] = []
    for group in groups:
        if not isinstance(group, dict) or "segments" not in group:
            continue
        seen_segments_key = True
        for seg in group.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            raw.append(
                {
                    "action": seg.get("action_type"),
                    "object": seg.get("object"),
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                }
            )
    if not seen_segments_key:
        raise ValueError(f"unexpected segment payload, no 'segments' key: {payload!r:.200}")
    return raw


def to_segments(raw: list[dict], duration: float) -> list[dict]:
    """Coerce raw model output into the frozen annotation contract."""
    out: list[dict] = []
    for item in raw:
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if duration > 0:
            start = min(start, duration)
            end = min(end, duration)
        start = max(start, 0.0)
        if end <= start:
            continue
        action = str(item.get("action") or "").strip()
        if not action:
            continue
        obj = str(item.get("object") or "").strip()
        out.append(make_segment(start, end, action, obj))
    out.sort(key=lambda s: s["start"])
    if not out:
        # A silently empty annotation looks like a pipeline that found nothing.
        raise ValueError("Pegasus returned no usable segments")
    return out
```

- [ ] **Step 5: Убедиться, что тест проходит**

Run: `docker compose exec ml-service python -m app.inference.pegasus.mapping`
Expected: PASS — печатает `ok`

- [ ] **Step 6: Коммит**

```bash
git add ml-service/app/inference/pegasus/__init__.py ml-service/app/inference/pegasus/mapping.py
git commit -m "feat(ml-service): map Pegasus output to the annotation contract"
```

---

### Task 2: SDK, конфигурация и клиент

**Files:**
- Modify: `ml-service/requirements.txt`
- Modify: `ml-service/app/config.py`
- Modify: `docker-compose.yml` (блок `environment` сервиса `ml-service`, около строки 150)
- Modify: `.env.example`
- Create: `ml-service/app/inference/pegasus/client.py`

**Interfaces:**
- Consumes: `get_settings()` из `app.config`; пакет `twelvelabs`.
- Produces:
  - `class TwelveLabsError(RuntimeError)`
  - `MAX_UPLOAD_BYTES: int`
  - `analyze(video_path: str, *, prompt: str, response_format: dict, analysis_mode: str, timeout: float, api_key: str) -> dict | list` — возвращает структурированную полезную нагрузку, уже извлечённую из ответа задачи. Режим analyze получает `dict`, режим segment — `dict` или `list`.
  - `structured_payload(result: dict) -> dict | list`

- [ ] **Step 1: Добавить зависимость**

Дописать в конец `ml-service/requirements.txt`:

```text
twelvelabs>=1.2.9,<2
```

Версию пиним, потому что 1.x несовместим с 0.4.x.

- [ ] **Step 2: Добавить настройку**

В `ml-service/app/config.py`, в классе `Settings`, после строки `database_url: ...` добавить:

```python
    twelvelabs_api_key: str = ""
```

- [ ] **Step 3: Пробросить переменную**

В `.env.example` дописать в конец:

```text

TWELVELABS_API_KEY=
```

В `docker-compose.yml` в блоке `environment` сервиса `ml-service`, после строки `PIPELINE: stub`, добавить:

```yaml
      TWELVELABS_API_KEY: ${TWELVELABS_API_KEY:-}
```

- [ ] **Step 4: Пересобрать образ и проверить, что SDK установился**

Run:
```bash
docker compose up -d --build ml-service
```

Затем:
```bash
docker compose exec ml-service python -c "import twelvelabs; print(twelvelabs.__version__)"
```
Expected: печатает версию 1.2.x

- [ ] **Step 5: Выяснить настоящие сигнатуры SDK**

Это шаг разведки, а не догадка. Спека прямо отмечает, что примеров с `segment_definitions` в справочнике SDK нет.

Run:
```bash
docker compose exec ml-service python -c "
from twelvelabs import TwelveLabs
import inspect
c = TwelveLabs(api_key='x')
print('assets.create:', inspect.signature(c.assets.create))
print('tasks.create:', inspect.signature(c.analyze_async.tasks.create))
print('tasks methods:', [m for m in dir(c.analyze_async.tasks) if not m.startswith('_')])
"
```

Записать фактические имена параметров. Реализация в следующем шаге написана под ожидаемые имена (`method`/`file` у `assets.create`; `video`, `model_name`, `prompt`, `analysis_mode`, `response_format`, `temperature` у `tasks.create`; метод ожидания вида `wait_for_done`). **Если фактические имена отличаются — поправить код шага 6 под них и отметить расхождение в описании коммита.**

- [ ] **Step 6: Написать клиент**

Создать `ml-service/app/inference/pegasus/client.py`:

```python
from __future__ import annotations

import os

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MODEL_NAME = "pegasus1.5"
TEMPERATURE = 0.2
POLL_INTERVAL = 3.0

# Keys the SDK may carry the structured payload under; checked in order.
PAYLOAD_KEYS = ("data", "result", "content", "output")


class TwelveLabsError(RuntimeError):
    pass


def _as_dict(obj: object) -> dict:
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            return fn()
    if isinstance(obj, dict):
        return obj
    raise TwelveLabsError(f"cannot convert SDK response of type {type(obj).__name__}")


def structured_payload(result: dict) -> dict | list:
    for key in PAYLOAD_KEYS:
        value = result.get(key)
        if isinstance(value, (dict, list)):
            return value
    raise TwelveLabsError(f"no structured payload in task result, keys: {sorted(result)}")


def analyze(
    video_path: str,
    *,
    prompt: str,
    response_format: dict,
    analysis_mode: str,
    timeout: float,
    api_key: str,
) -> dict | list:
    if not api_key:
        raise TwelveLabsError("TWELVELABS_API_KEY is not set")

    size = os.path.getsize(video_path)
    if size > MAX_UPLOAD_BYTES:
        raise TwelveLabsError(
            f"video is {size} bytes, TwelveLabs direct upload limit is {MAX_UPLOAD_BYTES}"
        )

    # Imported lazily so a broken or missing SDK does not take the consumer down at startup.
    from twelvelabs import TwelveLabs

    client = TwelveLabs(api_key=api_key)
    with open(video_path, "rb") as fh:
        asset = _as_dict(client.assets.create(method="direct", file=fh))
    asset_id = asset.get("id") or asset.get("asset_id")
    if not asset_id:
        raise TwelveLabsError(f"asset upload returned no id, keys: {sorted(asset)}")

    task = _as_dict(
        client.analyze_async.tasks.create(
            video={"type": "asset", "asset_id": asset_id},
            model_name=MODEL_NAME,
            temperature=TEMPERATURE,
            prompt=prompt,
            analysis_mode=analysis_mode,
            response_format=response_format,
        )
    )
    task_id = task.get("id") or task.get("task_id")
    if not task_id:
        raise TwelveLabsError(f"analyze task returned no id, keys: {sorted(task)}")

    result = _as_dict(
        client.analyze_async.tasks.wait_for_done(
            task_id=task_id, sleep_interval=POLL_INTERVAL, timeout=timeout
        )
    )

    status = str(result.get("status") or "").lower()
    if status and status not in ("ready", "done", "completed"):
        raise TwelveLabsError(f"analyze task {task_id} finished with status {status}")
    if str(result.get("finish_reason") or "").lower() == "length":
        raise TwelveLabsError(
            f"analyze task {task_id} was truncated (finish_reason=length); segments are incomplete"
        )
    return structured_payload(result)
```

- [ ] **Step 7: Проверить, что модуль импортируется и ключ проверяется**

Run:
```bash
docker compose restart ml-service && docker compose exec ml-service python -c "
from app.inference.pegasus.client import analyze, TwelveLabsError, structured_payload
try:
    analyze('/etc/hostname', prompt='p', response_format={}, analysis_mode='general', timeout=1.0, api_key='')
except TwelveLabsError as e:
    assert 'TWELVELABS_API_KEY is not set' in str(e), e
    print('ok')
"
```
Expected: печатает `ok`

- [ ] **Step 8: Коммит**

```bash
git add ml-service/requirements.txt ml-service/app/config.py \
        ml-service/app/inference/pegasus/client.py docker-compose.yml .env.example
git commit -m "feat(ml-service): add TwelveLabs SDK client for Pegasus"
```

---

### Task 3: Два пайплайна и их регистрация

**Files:**
- Create: `ml-service/app/inference/pegasus/analyze.py`
- Create: `ml-service/app/inference/pegasus/segment.py`
- Modify: `ml-service/app/inference/pegasus/__init__.py`
- Modify: `ml-service/app/inference/__init__.py`

**Interfaces:**
- Consumes: `Inference`, `JobContext`, `VideoMeta` из `app.inference.base`; `analyze`, `TwelveLabsError` из `app.inference.pegasus.client`; `vocabulary_prompt`, `to_segments`, `parse_analyze_payload`, `parse_segment_payload` из `app.inference.pegasus.mapping`; `get_settings` из `app.config`.
- Produces: `PegasusAnalyzeInference` (`name = "pegasus_analyze"`), `PegasusSegmentInference` (`name = "pegasus_segment"`), обе с `version = 1` и `TIMEOUT = 600.0`.

- [ ] **Step 1: Написать режим analyze**

Создать `ml-service/app/inference/pegasus/analyze.py`:

```python
from __future__ import annotations

from app.config import get_settings
from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.pegasus.client import analyze as call_analyze
from app.inference.pegasus.mapping import (
    parse_analyze_payload,
    to_segments,
    vocabulary_prompt,
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "description": "Detected human actions in the video, ordered by start time.",
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "description": (
                            "Verb / action label for this interval "
                            "(e.g. pour, push, pick_up)."
                        ),
                    },
                    "object": {
                        "type": "string",
                        "description": (
                            "Primary object involved in the action, if identifiable "
                            "(e.g. cup, bottle). Leave empty if no object is identifiable."
                        ),
                    },
                    "start": {
                        "type": "number",
                        "description": (
                            "Start time of the action in seconds from the beginning "
                            "of the video."
                        ),
                    },
                    "end": {
                        "type": "number",
                        "description": (
                            "End time of the action in seconds from the beginning of "
                            "the video. Must be >= start."
                        ),
                    },
                },
                "required": ["action_type", "start", "end"],
            },
        }
    },
    "required": ["actions"],
}


class PegasusAnalyzeInference(Inference):
    name = "pegasus_analyze"
    version = 1
    # Upper bound on the whole upload + analysis round trip. Kept here rather than in
    # config: it is a property of this pipeline, not of the deployment.
    TIMEOUT = 600.0

    def build_prompt(self, ctx: JobContext) -> str:
        return (
            "Detect every distinct human action in this video. "
            "For each action return its start and end time in seconds. "
            + vocabulary_prompt(ctx)
        )

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        payload = call_analyze(
            ctx.video_path,
            prompt=self.build_prompt(ctx),
            response_format={"type": "json_schema", "json_schema": JSON_SCHEMA},
            analysis_mode="general",
            timeout=self.TIMEOUT,
            api_key=get_settings().twelvelabs_api_key,
        )
        return to_segments(parse_analyze_payload(payload), meta.duration)
```

- [ ] **Step 2: Написать режим segment**

Создать `ml-service/app/inference/pegasus/segment.py`:

```python
from __future__ import annotations

from app.config import get_settings
from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.pegasus.client import analyze as call_analyze
from app.inference.pegasus.mapping import (
    parse_segment_payload,
    to_segments,
    vocabulary_prompt,
)

SEGMENT_DEFINITIONS = {
    "type": "segment_definitions",
    "segment_time_format": "seconds",
    "segment_definitions": [
        {
            "id": "human_action",
            "description": (
                "Each continuous interval where a person performs a distinct "
                "manipulation action."
            ),
            "fields": [
                {
                    "name": "action_type",
                    "type": "string",
                    "description": "Verb / action label for this interval, e.g. pour, push.",
                },
                {
                    "name": "object",
                    "type": "string",
                    "description": (
                        "Primary object involved in the action, e.g. cup, bottle. "
                        "Leave empty if no object is identifiable."
                    ),
                },
            ],
        }
    ],
}


class PegasusSegmentInference(Inference):
    name = "pegasus_segment"
    version = 1
    TIMEOUT = 600.0

    def build_prompt(self, ctx: JobContext) -> str:
        return (
            "Segment this video into intervals of distinct human manipulation actions. "
            + vocabulary_prompt(ctx)
        )

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        payload = call_analyze(
            ctx.video_path,
            prompt=self.build_prompt(ctx),
            response_format=SEGMENT_DEFINITIONS,
            analysis_mode="time_based_metadata",
            timeout=self.TIMEOUT,
            api_key=get_settings().twelvelabs_api_key,
        )
        return to_segments(parse_segment_payload(payload), meta.duration)
```

Интервалы отдаёт сам API в полях сегмента, поэтому `start`/`end` не дублируются в `fields`.

- [ ] **Step 3: Экспортировать классы из пакета**

Заменить содержимое `ml-service/app/inference/pegasus/__init__.py` на:

```python
from app.inference.pegasus.analyze import PegasusAnalyzeInference
from app.inference.pegasus.segment import PegasusSegmentInference

__all__ = ["PegasusAnalyzeInference", "PegasusSegmentInference"]
```

- [ ] **Step 4: Зарегистрировать пайплайны**

В `ml-service/app/inference/__init__.py` добавить импорт после строки `from app.inference.overlap import OverlapInference`:

```python
from app.inference.pegasus import PegasusAnalyzeInference, PegasusSegmentInference
```

И две записи в словарь `PIPELINES`, после `"dense": DenseInference,`:

```python
    "pegasus_analyze": PegasusAnalyzeInference,
    "pegasus_segment": PegasusSegmentInference,
```

- [ ] **Step 5: Расширить self-test**

Добавить в `ml-service/app/inference/__init__.py` внутрь блока `if __name__ == "__main__":`, непосредственно перед `print("ok")`:

```python
    assert get_pipeline("pegasus_analyze").name == "pegasus_analyze"
    assert get_pipeline("pegasus_segment").name == "pegasus_segment"
    assert PegasusAnalyzeInference.version == 1
    assert PegasusSegmentInference.version == 1
    assert PegasusAnalyzeInference.TIMEOUT == PegasusSegmentInference.TIMEOUT == 600.0
    pegasus_ctx = JobContext(
        job_id="j", video_id="x", s3_key="", action_types=["alpha"], objects=["thing"]
    )
    for cls in (PegasusAnalyzeInference, PegasusSegmentInference):
        text = cls().build_prompt(pegasus_ctx)
        assert "alpha" in text and "thing" in text, cls.name
```

AGENTS.md просит проверять здесь вывод нового пайплайна, но вывод Pegasus требует сети,
ключа и расходует квоту. Поэтому здесь проверяется только регистрация и построение
промпта, а маппинг вывода полностью покрыт self-тестом из Task 1.

- [ ] **Step 6: Прогнать оба self-теста**

Run:
```bash
docker compose restart ml-service
docker compose exec ml-service python -m app.inference
docker compose exec ml-service python -m app.inference.pegasus.mapping
```
Expected: обе команды печатают `ok`

- [ ] **Step 7: Проверить, что ML-сервис отдаёт версии**

Run:
```bash
curl -s localhost:8001/inference/pegasus_analyze
curl -s localhost:8001/inference/pegasus_segment
```
Expected: JSON с `"version": 1` для обоих

- [ ] **Step 8: Коммит**

```bash
git add ml-service/app/inference/pegasus/ ml-service/app/inference/__init__.py
git commit -m "feat(ml-service): add pegasus_analyze and pegasus_segment pipelines"
```

---

### Task 4: Показать пайплайны в интерфейсе

**Files:**
- Modify: `backend/app/schemas.py:140-156` (список `INFERENCE_TYPES`)

**Interfaces:**
- Consumes: строковые имена пайплайнов из Task 3 — `pegasus_analyze`, `pegasus_segment`.
- Produces: две новые записи в `GET /api/inference`; фронтенд менять не нужно, селектор Model на `VideoPage` строится из этого ответа.

- [ ] **Step 1: Добавить записи**

В `backend/app/schemas.py` в список `INFERENCE_TYPES`, после словаря с `"id": "dense"`, добавить:

```python
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
```

`id` обязан совпадать с ключом в `PIPELINES`: `process_video` в
`backend/app/routers/videos.py:165` отклоняет неизвестные имена по этому списку.

- [ ] **Step 2: Проверить, что бэкенд отдаёт новые типы**

Run:
```bash
docker compose restart backend && sleep 5 && curl -s localhost:8000/api/inference
```
Expected: в JSON присутствуют `pegasus_analyze` и `pegasus_segment`

- [ ] **Step 3: Проверить сборку фронтенда**

Фронтенд не менялся, но проверка типов дёшева и ловит рассинхрон `types.ts` со схемами.

Run: `cd frontend && npm run build`
Expected: сборка проходит без ошибок

- [ ] **Step 4: Коммит**

```bash
git add backend/app/schemas.py
git commit -m "feat(backend): expose pegasus pipelines in the inference list"
```

---

### Task 5: Живая проверка на реальном ключе

Требует ключа TwelveLabs. Если ключа нет, задача откладывается — остальной код от неё не зависит, но **без неё нельзя утверждать, что пайплайны работают**: до этого момента проверены только регистрация и маппинг на зафиксированных данных.

**Files:**
- Modify: `ml-service/app/inference/pegasus/client.py` (только если реальный ответ не совпал с ожиданиями)
- Modify: `ml-service/app/inference/pegasus/mapping.py` (только если реальный ответ не совпал с ожиданиями)

**Interfaces:**
- Consumes: всё из задач 1–4.
- Produces: подтверждённые формы ответа; при расхождении — исправленные `structured_payload` и парсеры.

- [ ] **Step 1: Прописать ключ**

Добавить в `.env` строку `TWELVELABS_API_KEY=tlk_...` и применить:

```bash
docker compose up -d ml-service
```

Ключ берётся в Dashboard на <https://playground.twelvelabs.io> (раздел API Key).
`.env` в репозиторий не коммитится.

- [ ] **Step 2: Прогнать оба режима через интерфейс**

Открыть http://localhost:3000, загрузить короткий ролик, выбрать в селекторе Model
значение «Pegasus (analyze)», нажать Run model. Дождаться завершения (минуты).
Повторить для «Pegasus (segment)» на том же видео.

- [ ] **Step 3: Прочитать логи**

Run: `docker compose logs --tail=100 ml-service`

Ожидаемо: `Job ... completed` для обоих запусков.

Если задача упала — сообщение об ошибке содержит фактические ключи ответа
(`no structured payload in task result, keys: [...]` или
`unexpected segment payload, no 'segments' key: ...`). Поправить `PAYLOAD_KEYS`
в `client.py` или соответствующий парсер в `mapping.py` под реальную форму,
дописать в self-тест Task 1 случай с настоящей формой ответа и повторить прогон.

- [ ] **Step 4: Проверить результат на таймлайне**

Сегменты должны появиться на таймлайне видео, границы — в пределах длительности,
ключевой кадр — внутри сегмента. Оба режима должны быть видны как отдельные результаты:
`inferences` уникален по `(video_id, pipeline)`.

- [ ] **Step 5: Перепрогнать self-тесты**

Run:
```bash
docker compose exec ml-service python -m app.inference.pegasus.mapping
docker compose exec ml-service python -m app.inference
docker compose exec backend python -m app.segment
docker compose exec backend python -m app.labels
```
Expected: все четыре печатают `ok`

- [ ] **Step 6: Коммит (только если что-то правилось)**

```bash
git add ml-service/app/inference/pegasus/
git commit -m "fix(ml-service): match the real TwelveLabs response shape"
```

---

### Task 6: Документация

AGENTS.md требует обновлять документацию в том же изменении, которое делает её неверной.

**Files:**
- Modify: `CLAUDE.md` (он же AGENTS.md — разделы «Testing», «Adding an inference pipeline», «Gotchas»)
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/project-overview.md` (§4–5)

**Interfaces:**
- Consumes: факты из задач 1–5.
- Produces: документацию, соответствующую коду.

- [ ] **Step 1: Обновить AGENTS.md**

В разделе «Testing» добавить в список команд:

```bash
docker compose exec ml-service python -m app.inference.pegasus.mapping  # Pegasus output mapping
```

В раздел «Adding an inference pipeline» добавить абзац об осознанном отклонении:

> **Exception: `inference/pegasus/`.** The two TwelveLabs pipelines
> (`pegasus_analyze`, `pegasus_segment`) share one package instead of having one each.
> They differ only in the `response_format` they send and how they parse the reply;
> the SDK client, the prompt builder and the mapping to the annotation contract are
> shared. Splitting them would duplicate that code or push it to a third place.
> This is deliberate — do not "fix" it by splitting the package.

В раздел «Gotchas» добавить:

> - **Pegasus jobs block the consumer for minutes.** The consumer reads with `count=1`,
>   so videos are processed one at a time; the next job sits in `QUEUED` meanwhile.
>   `TIMEOUT` is a class attribute on each pipeline, not a setting.
> - **`TWELVELABS_API_KEY` is required for the Pegasus pipelines.** Without it a job
>   fails with an explicit message rather than a 401 from the API.

- [ ] **Step 2: Обновить README.md**

В описание настройки, рядом с копированием `.env`, добавить: для пайплайнов Pegasus
нужен ключ TwelveLabs — регистрация на <https://playground.twelvelabs.io>, ключ вида
`tlk_...` из Dashboard → API Key, вписать в `.env` как `TWELVELABS_API_KEY`. Без ключа
остальные пайплайны работают, а задачи Pegasus падают с внятным сообщением.

- [ ] **Step 3: Обновить docs/architecture.md**

Добавить: ml-service обращается к внешнему API TwelveLabs напрямую (файл уже скачан
из S3 локально, presigned-URL MinIO извне не резолвится); обработка последовательная,
одно видео за раз; ключ `annotation.json` в S3 не содержит имени пайплайна, поэтому
два режима Pegasus пишут в один объект и второй запуск перезаписывает первый — в БД
поле `data` при этом хранится отдельно на каждый пайплайн, так что сравнение режимов
не ломается.

- [ ] **Step 4: Обновить docs/project-overview.md §4–5**

Описать по-русски два режима Pegasus: чем отличаются `json_schema` и
`segment_definitions`, что словарь проекта передаётся через промпт, а не через `enum`,
и что нормализацию меток делает `backend/app/labels.py`.

- [ ] **Step 5: Проверить, что команды из документации работают**

Run: `docker compose exec ml-service python -m app.inference.pegasus.mapping`
Expected: печатает `ok`

- [ ] **Step 6: Коммит**

```bash
git add CLAUDE.md README.md docs/architecture.md docs/project-overview.md
git commit -m "docs: document the Pegasus pipelines and the TwelveLabs key"
```

---

## Порядок и зависимости

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6.

Задачи 1 и 2 независимы друг от друга по коду и могут идти в любом порядке;
Task 3 требует обеих. Task 5 требует ключа и может быть отложена, но до её выполнения
работоспособность пайплайнов не подтверждена.
