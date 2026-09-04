from __future__ import annotations

import math

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


def parse_analyze_payload(payload: dict | list) -> list[dict]:
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


def parse_segment_payload(payload: dict) -> list[dict]:
    """Parse a time_based_metadata payload: an object keyed by segment definition id,
    each key mapping to an array of {start_time, end_time, metadata} objects."""
    if not isinstance(payload, dict) or not all(
        isinstance(v, list) for v in payload.values()
    ):
        raise ValueError(f"unexpected segment payload, expected dict of lists: {payload!r:.200}")

    raw: list[dict] = []
    for entries in payload.values():
        for seg in entries:
            if not isinstance(seg, dict):
                continue
            metadata = seg.get("metadata")
            if not isinstance(metadata, dict):
                continue
            raw.append(
                {
                    "action": metadata.get("action_type"),
                    "object": metadata.get("object"),
                    "start": seg.get("start_time"),
                    "end": seg.get("end_time"),
                }
            )
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
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        # Only clamp to duration if it is known (> 0). When ffprobe cannot read
        # the duration from the container, it falls back to 0, and clamping to 0
        # would discard all segments, raising here. With unknown duration there
        # is no upper bound to clamp against.
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
