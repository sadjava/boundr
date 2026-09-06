"""Map Marlin captions onto Boundr segments with GPT-4o-mini via OpenRouter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import get_settings
from app.inference.base import JobContext, make_segment

MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
TIMEOUT = 120
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

PROMPT = """\
Convert timed English video captions into atomic human-object manipulations
in EPIC-Kitchens style.

The clip lasts {duration:g} seconds. Events look like "<start - end> description".

Return JSON only:
{{"segments": [{{"start": number, "end": number, "action": string, "object": string}}]}}

Rules:
- Keep only contact manipulations. Drop looking, walking, waiting, carrying,
  holding, reaching, adjusting, checking, and camera motion.
- One segment per time span. Do not overlap segments and do not emit two
  actions for the same interval.
- Merge consecutive events with the same action and object.
- start and end are seconds; keep 0 <= start < end <= {duration:g}.
  Prefer the caption's own range; do not invent extra micro-steps (lift, scrape,
  carry) inside one continuous pour or scoop.
- action is a short verb. Use a hyphen for particles (pick-up, put-down,
  pour-into, pour-onto, turn-on, turn-off, take-from). Not snake_case.
- object is the head noun of the thing being manipulated (pan, rice, tap, mug),
  not a scene phrase. Not "food in the pan", "tea into mug", "plate on the table".
  Put the destination into the verb (pour-into), not into the object string.
- Every segment needs both action and object. {vocab}

Captions:
{captions}
"""


def _norm(value: str) -> str:
    return "_".join(value.lower().replace("-", " ").replace("_", " ").split())


def _vocab(ctx: JobContext) -> str:
    parts = []
    if ctx.action_types:
        parts.append("Use only these action labels: " + ", ".join(ctx.action_types) + ".")
    else:
        parts.append(
            "Use concise lowercase verbs; hyphenate particles "
            "(pick-up, put-down, turn-off)."
        )
    if ctx.objects:
        parts.append("Use only these object labels: " + ", ".join(ctx.objects) + ".")
    else:
        parts.append("Use a concise noun phrase for the manipulated object.")
    return " ".join(parts)


def _strip_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


def _complete(prompt: str) -> str:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    base = (settings.openrouter_base_url or DEFAULT_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        json.dumps(
            {
                "model": MODEL,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode(),
        {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise ValueError(f"OpenRouter HTTP {exc.code}: {body}") from exc
    message = payload["choices"][0]["message"]
    content = message.get("content") or ""
    if not content.strip():
        raise ValueError("OpenRouter returned an empty completion")
    return content


def _items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("segments")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    raise ValueError("OpenRouter response did not contain a segments list")


def _pick(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _in_catalog(value: str, catalog: list[str] | None) -> str | None:
    if not catalog:
        return value
    wanted = _norm(value)
    for label in catalog:
        if _norm(label) == wanted:
            return label
    return None


def segments_from_json(text: str, duration: float, ctx: JobContext) -> list[dict]:
    try:
        payload = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise ValueError("OpenRouter response was not valid JSON") from exc
    out: list[dict] = []
    seen: set[tuple[str, str, float, float]] = set()
    for item in _items(payload):
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        start = max(0.0, min(start, duration))
        end = max(start, min(end, duration))
        if end <= start:
            continue
        action = _in_catalog(_pick(item, "action", "action_type"), ctx.action_types)
        obj = _in_catalog(_pick(item, "object"), ctx.objects)
        if not action or not obj:
            continue
        key = (action, obj, start, end)
        if key in seen:
            continue
        seen.add(key)
        out.append(make_segment(start, end, action, obj))
    return out


def parse_with_gpt(text: str, duration: float, ctx: JobContext) -> list[dict]:
    if not text.strip():
        raise ValueError("Marlin response was empty")
    prompt = PROMPT.format(duration=duration, vocab=_vocab(ctx), captions=text.strip())
    return segments_from_json(_complete(prompt), duration, ctx)


if __name__ == "__main__":
    ctx = JobContext("self-check", "video", "")
    parsed = segments_from_json(
        """```json
        {"segments": [
          {"start": 2, "end": 4, "action": "open", "object": "cabinet door"},
          {"start": 4, "end": 6, "action_type": "put_down", "object": "cup"}
        ]}
        ```""",
        8,
        ctx,
    )
    assert [
        (item["start"], item["end"], item["action"], item["object"])
        for item in parsed
    ] == [
        (2.0, 4.0, "open", "cabinet door"),
        (4.0, 6.0, "put_down", "cup"),
    ]
    cataloged = segments_from_json(
        '{"segments": [{"start": 0, "end": 1, "action": "pull_out", "object": "a card"}]}',
        1,
        JobContext("self-check", "video", "", action_types=["pick_up"], objects=["card"]),
    )
    assert cataloged == []
    matched = segments_from_json(
        '{"segments": [{"start": 0, "end": 1, "action": "Pick Up", "object": "Card"}]}',
        1,
        JobContext("self-check", "video", "", action_types=["pick_up"], objects=["card"]),
    )
    assert [(item["action"], item["object"]) for item in matched] == [("pick_up", "card")]
    try:
        segments_from_json("not json", 1, ctx)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid JSON must fail")
    print("ok")
