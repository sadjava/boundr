from __future__ import annotations

import csv
import io
import json
import uuid

from app.segment import AnnotationSegment

CSV_HEADER = ["video_id", "segment_id", "action", "object", "start", "end", "keyframe"]


def _segments(items: list) -> list[dict]:
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", str(uuid.uuid4()))
        row["action"] = row.get("action_type") or row.get("action") or ""
        out.append(AnnotationSegment.model_validate(row).model_dump())
    return out


def parse_annotation_payload(
    raw: dict,
    video_id: str,
    duration: float | None = None,
) -> dict:
    """Accept Boundr {segments} or VLM {actions} JSON."""
    if "segments" in raw:
        items = raw["segments"]
    elif isinstance(raw.get("actions"), list):
        items = raw["actions"]
    else:
        raise ValueError("annotation must have segments or actions")
    if not isinstance(items, list):
        raise ValueError("annotation must have segments or actions")
    return {
        "video_id": video_id,
        "duration": float(raw.get("duration") or duration or 0),
        "fps": raw.get("fps"),
        "segments": _segments(items),
    }


def parse_annotation_bytes(blob: bytes, video_id: str, duration: float | None = None) -> dict:
    raw = json.loads(blob.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("annotation JSON must be an object")
    return parse_annotation_payload(raw, video_id, duration)


def annotation_to_csv(data: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for seg in data.get("segments") or []:
        writer.writerow(
            [
                data.get("video_id") or "",
                seg.get("id") or "",
                seg.get("action") or "",
                seg.get("object") or "",
                seg.get("start"),
                seg.get("end"),
                seg.get("keyframe"),
            ]
        )
    return buf.getvalue()


def parse_annotation_csv(blob: bytes, video_id: str, duration: float | None = None) -> dict:
    text = blob.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("empty CSV")
    fields = {f.strip().lower() for f in reader.fieldnames if f}
    needed = {"segment_id", "action", "start", "end"}
    if not needed.issubset(fields):
        raise ValueError("CSV must have segment_id, action, start, end columns")
    items = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        items.append(
            {
                "id": (row.get("segment_id") or "").strip() or str(uuid.uuid4()),
                "action": (row.get("action") or "").strip(),
                "object": (row.get("object") or "").strip() or None,
                "start": row.get("start"),
                "end": row.get("end"),
                "keyframe": row.get("keyframe") or None,
            }
        )
    return {
        "video_id": video_id,
        "duration": float(duration or 0),
        "fps": None,
        "segments": _segments(items),
    }


def _seg_key(seg: dict) -> tuple:
    obj = seg.get("object")
    if obj in ("", None):
        obj = None
    return (
        (seg.get("action") or "").strip().lower(),
        (obj or "").strip().lower() if obj else None,
        round(float(seg.get("start") or 0), 3),
        round(float(seg.get("end") or 0), 3),
        round(float(seg.get("keyframe") or 0), 3),
    )


def segments_match(a: dict, b: dict) -> bool:
    sa = sorted(_seg_key(s) for s in (a.get("segments") or []))
    sb = sorted(_seg_key(s) for s in (b.get("segments") or []))
    return sa == sb


def parse_annotation_file(
    blob: bytes,
    suffix: str,
    video_id: str,
    duration: float | None = None,
) -> dict:
    ext = suffix.lower()
    if ext == ".json":
        return parse_annotation_bytes(blob, video_id, duration)
    if ext == ".csv":
        return parse_annotation_csv(blob, video_id, duration)
    raise ValueError(f"unsupported annotation format: {suffix}")


def resolve_annotation_blobs(
    files: dict[str, bytes],
    video_id: str,
    duration: float | None = None,
) -> dict:
    """files maps '.json'/'.csv' -> bytes. One format: use it. Both: must match."""
    if not files:
        raise ValueError("no annotation files")
    parsed = {
        ext: parse_annotation_file(blob, ext, video_id, duration) for ext, blob in files.items()
    }
    if len(parsed) == 1:
        return next(iter(parsed.values()))
    json_data = parsed.get(".json")
    csv_data = parsed.get(".csv")
    if json_data is not None and csv_data is not None:
        if not segments_match(json_data, csv_data):
            raise ValueError("json and csv annotations differ")
        return json_data
    return next(iter(parsed.values()))


if __name__ == "__main__":
    boundr = parse_annotation_payload(
        {"video_id": "old", "duration": 4, "segments": [{"id": "1", "start": 0, "end": 1, "action": "pour"}]},
        "vid",
    )
    assert boundr["video_id"] == "vid"
    assert boundr["segments"][0]["action"] == "pour"
    vlm = parse_annotation_payload(
        {"actions": [{"action_type": "cut", "object": "onion", "start": 1, "end": 2}]},
        "vid",
        duration=3,
    )
    assert vlm["duration"] == 3
    assert vlm["segments"][0]["action"] == "cut"
    assert vlm["segments"][0]["object"] == "onion"

    csv_text = annotation_to_csv(boundr)
    from_csv = parse_annotation_csv(csv_text.encode(), "vid", duration=4)
    assert segments_match(boundr, from_csv)
    assert resolve_annotation_blobs({".json": json.dumps(boundr).encode()}, "vid")["segments"]
    assert resolve_annotation_blobs(
        {".json": json.dumps(boundr).encode(), ".csv": csv_text.encode()},
        "vid",
    )["segments"][0]["action"] == "pour"
    bad_csv = annotation_to_csv(
        {"video_id": "vid", "segments": [{"id": "1", "start": 0, "end": 2, "action": "other", "object": None, "keyframe": 1}]}
    )
    try:
        resolve_annotation_blobs(
            {".json": json.dumps(boundr).encode(), ".csv": bad_csv.encode()},
            "vid",
        )
        raise AssertionError("expected mismatch")
    except ValueError as e:
        assert "differ" in str(e)
    print("ok")
