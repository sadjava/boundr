# Инференс TwelveLabs Pegasus: два режима (analyze и segment)

Дата: 2026-09-04

## 1. Задача

Добавить в Boundr реальный инференс на основе TwelveLabs Pegasus вместо синтетических
заглушек. Поддержать оба режима, доступные в Playground:

- `playground.twelvelabs.io/analyze` — структурированный ответ по произвольной JSON-схеме;
- `playground.twelvelabs.io/segment` — извлечение временных сегментов с полями.

Оба режима обслуживает один эндпоинт TwelveLabs, различаются они полем `response_format`
и режимом анализа.

## 2. Внешний API

Базовый URL: `https://api.twelvelabs.io/v1.3`. Аутентификация — заголовок `x-api-key`.
Индексы заводить не требуется.

| Шаг | Запрос |
|---|---|
| Загрузка файла | `POST /assets` (multipart, до 200 МБ) → `asset_id` |
| Постановка задачи | `POST /analyze/tasks` → `{"task_id", "status": "pending"}` |
| Получение результата | `GET /analyze/tasks/{task_id}`, пока `status != "ready"` |

Тело задачи:

```json
{
  "video": {"type": "asset", "asset_id": "..."},
  "model_name": "pegasus1.5",
  "temperature": 0.2,
  "prompt": "...",
  "analysis_mode": "general | time_based_metadata",
  "response_format": {...}
}
```

Синхронный вариант `POST /analyze` не подходит: он поддерживает только
`response_format.type = "json_schema"`, то есть режим segment через него недоступен.

### Получение ключа

1. Регистрация на <https://playground.twelvelabs.io>.
2. Dashboard → API Key, ключ вида `tlk_...`. Есть бесплатный тариф с квотой на минуты видео.
3. Ключ кладётся в `.env` как `TWELVELABS_API_KEY` и пробрасывается в контейнер `ml-service`.

## 3. Решения

### 3.1 Два пайплайна, один пакет

Регистрируются два пайплайна: `pegasus_analyze` и `pegasus_segment`. Таблица `inferences`
уникальна по `(video_id, pipeline)`, поэтому результаты двух режимов сосуществуют и их
можно сравнить на одном видео.

Код обоих режимов лежит в одном пакете `ml-service/app/inference/pegasus/`. Различаются
режимы ровно двумя вещами — телом `response_format` и разбором ответа; загрузка файла,
поллинг, таймаут, построение промпта и приведение к контракту у них общие.

**Это осознанное отклонение от конвенции.** Существующие пакеты (`overlap`, `dense`,
`sequential`) содержат по одному классу в `infer.py`, и AGENTS.md описывает добавление
пайплайна как «пакет на пайплайн». Здесь — пакет на модель с двумя классами. Отклонение
должно быть зафиксировано в AGENTS.md, чтобы не читаться как ошибка.

### 3.2 Загрузка файла, а не presigned-URL

MinIO слушает `localhost:9000`; такой адрес TwelveLabs не резолвит. Поэтому ml-service
загружает файл сам. Файл к моменту вызова уже лежит локально в `ctx.video_path` —
консьюмер скачивает его из S3 перед запуском пайплайна, лишней работы нет.

При размере файла свыше 200 МБ кидаем понятное исключение до обращения к API.

Инвариант «видео не проходит через бэкенд и Redis» не нарушается: файл идёт из
ml-service напрямую во внешний сервис.

### 3.3 Словарь проекта — через промпт, не через enum

`ctx.action_types` и `ctx.objects` могут быть `None` (открытый словарь — основной случай)
или списком допустимых меток.

Если словарь задан, допустимые метки перечисляются в промпте и в `description` полей
схемы. В `enum` схемы словарь не зашивается: при жёстком enum модель натягивает
неподходящую метку вместо честного ответа. Приведение к словарю выполняет нормализация
на стороне бэкенда (`backend/app/labels.py`), которая уже есть.

При `None` промпт просит краткие глагольные метки в нижнем регистре.

### 3.4 Долгие вызовы: последовательно, с таймаутом

Консьюмер читает Redis Stream с `count=1` и обрабатывает сообщения по одному. Вызов
Pegasus занимает минуты, поэтому видео обрабатываются последовательно; второе висит в
`QUEUED`, пока не закончится первое. Для коротких роликов кейса этого достаточно.

`consumer.py` не меняется. Параллелизм не добавляем: он потребовал бы обработки 429 и
упирался бы в квоту бесплатного тарифа.

Таймаут поллинга — константа класса пайплайна (`TIMEOUT = 600.0`), не настройка
окружения. По истечении — исключение, задача уходит в `FAILED` с внятным сообщением.

## 4. Структура

```text
ml-service/app/inference/pegasus/
  __init__.py   re-export PegasusAnalyzeInference, PegasusSegmentInference
  client.py     HTTP: загрузка asset, создание задачи, поллинг
  mapping.py    построение промпта из словаря; ответ API → сегменты контракта
  analyze.py    PegasusAnalyzeInference — режим json_schema
  segment.py    PegasusSegmentInference — режим segment_definitions
```

### 4.1 client.py

```python
def analyze(video_path: str, *, prompt: str, response_format: dict,
            analysis_mode: str, timeout: float, api_key: str) -> dict
```

Выполняет три шага из §2 с интервалом поллинга 3 с. Кидает исключение при:
пустом `api_key` (текст «TWELVELABS_API_KEY is not set» — чтобы причина была видна
в UI, а не приходила как 401), файле свыше 200 МБ, статусе задачи `failed`, истечении
таймаута, `finish_reason == "length"` (ответ обрезан — сегменты неполные).

Транспорт — `httpx`, он уже в `ml-service/requirements.txt`. Новых зависимостей нет.

### 4.2 analyze.py

`name = "pegasus_analyze"`, `version = 1`, `analysis_mode = "general"`.

`response_format.json_schema` — схема из постановки задачи: объект с массивом `actions`,
элементы которого имеют `action_type` (string), `object` (string), `start` (number),
`end` (number); обязательны `action_type`, `start`, `end`.

Единственная правка схемы: в `description` поля `object` добавляется указание оставлять
поле пустым, если предмет не определяется, — иначе модель чаще выдумывает предмет.

### 4.3 segment.py

`name = "pegasus_segment"`, `version = 1`, `analysis_mode = "time_based_metadata"`.

```json
{"type": "segment_definitions",
 "segment_time_format": "seconds",
 "segment_definitions": [{
   "id": "human_action",
   "description": "Each continuous interval where a person performs a distinct manipulation action.",
   "fields": [
     {"name": "action_type", "type": "string", "description": "..."},
     {"name": "object",      "type": "string", "description": "..."}
   ]}]}
```

Границы интервала возвращает сам API в полях сегмента, поэтому в `fields` они
не дублируются.

### 4.4 mapping.py

Приведение к контракту `{id, start, end, action, object, keyframe}` в секундах через
`make_segment()` из `inference/base.py` — он же расставляет `keyframe` внутри интервала.

Правила очистки, общие для обоих режимов:

- отбрасываются записи с `end <= start` и с `end <= 0`;
- `end` подрезается по `meta.duration`, `start` — по нулю;
- отсутствующий `object` превращается в пустую строку;
- сегменты сортируются по `start`;
- если после очистки не осталось ни одного сегмента, кидается исключение. Тихая пустая
  аннотация выглядит как работающий пайплайн, который ничего не нашёл, — по правилу
  AGENTS.md «не отдавать молча пустой результат».

## 5. Остальные изменения

| Файл | Изменение |
|---|---|
| `ml-service/app/inference/__init__.py` | два ключа в `PIPELINES` + self-test |
| `ml-service/app/config.py` | `twelvelabs_api_key: str = ""` |
| `backend/app/schemas.py` | две записи в `INFERENCE_TYPES` (строка 140) |
| `.env.example` | `TWELVELABS_API_KEY=` |
| `docker-compose.yml` | проброс переменной в `ml-service` |

Фронтенд не меняется: селектор Model на `VideoPage` строится из `GET /api/inference`.

## 6. Тестирование

По конвенции репозитория — блок `if __name__ == "__main__":` в
`ml-service/app/inference/__init__.py`, без сети и без ключа. Проверяются функции
из `mapping.py` на зафиксированных ответах API (вариант `{"actions": [...]}` и сегментный):

- `start <= keyframe <= end` для каждого сегмента;
- значения в секундах;
- отсев записей с `end <= start`;
- подрезка `end` по длительности видео;
- пустой `object` не роняет маппинг;
- пустой результат приводит к исключению;
- словарь проекта попадает в текст промпта, при `None` промпт остаётся открытым.

Сетевой вызов `client.py` не тестируется: он требует ключа и расходует квоту.

Запуск: `docker compose exec ml-service python -m app.inference` (команда уже есть
в AGENTS.md).

## 7. Обновление документации

| Документ | Что добавить |
|---|---|
| `AGENTS.md` | отклонение из §3.1; переменная `TWELVELABS_API_KEY` |
| `README.md` | получение ключа TwelveLabs при настройке |
| `docs/architecture.md` | внешний вызов из ml-service; последовательная обработка |
| `docs/project-overview.md` §4–5 | описание пайплайнов Pegasus |

Отдельно отметить известный подвох: ключ `annotation.json` в S3 не содержит имени
пайплайна, поэтому оба режима пишут в один объект и второй запуск перезаписывает первый.
В БД поле `data` хранится отдельно на каждый пайплайн, так что сравнение режимов
не ломается.

## 8. Вне области задачи

Параллельная обработка, ретраи на 429, кэширование `asset_id` между запусками,
загрузка файлов свыше 200 МБ через multipart-эндпоинт.
