from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class LoadError(Exception):
    """Файл не удалось прочитать как разметку."""


@dataclass(frozen=True)
class Segment:
    id: str
    start: float
    end: float
    action: str
    object: str
    keyframe: float | None


def _as_float(value: object, field: str, path: Path) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise LoadError(f"{path}: поле {field!r} не число: {value!r}") from None


def _as_label(value: object) -> str:
    # Пустой объект в контракте продукта — это "", "none" или null.
    if value is None:
        return ""
    return str(value).strip()


def load_annotation(path: Path) -> list[Segment]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(f"{path}: {exc}") from exc

    if isinstance(raw, dict):
        raw = raw.get("segments", [])
    if not isinstance(raw, list):
        raise LoadError(f"{path}: ожидался список сегментов")

    segments: list[Segment] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise LoadError(f"{path}: сегмент #{index} не объект")
        keyframe = item.get("keyframe")
        segments.append(Segment(
            id=str(item.get("id", index)),
            start=_as_float(item.get("start"), "start", path),
            end=_as_float(item.get("end"), "end", path),
            action=_as_label(item.get("action")),
            object=_as_label(item.get("object")),
            keyframe=None if keyframe is None else _as_float(keyframe, "keyframe", path),
        ))
    return segments


def partition_valid(segments: list[Segment]) -> tuple[list[Segment], list[Segment]]:
    valid = [s for s in segments if s.start <= s.end]
    invalid = [s for s in segments if s.start > s.end]
    return valid, invalid
