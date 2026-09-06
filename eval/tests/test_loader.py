from __future__ import annotations

import json
from pathlib import Path

import pytest

from evallib.loader import LoadError, Segment, load_annotation, partition_valid


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "clip.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_export_shape(tmp_path: Path) -> None:
    path = _write(tmp_path, {
        "video_id": "v1",
        "duration": 10.0,
        "fps": 30.0,
        "segments": [
            {"id": "a", "start": 0.0, "end": 2.0, "action": "open",
             "object": "drawer", "keyframe": 1.0},
        ],
    })
    segments = load_annotation(path)
    assert segments == [Segment("a", 0.0, 2.0, "open", "drawer")]


def test_loads_bare_list(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        {"id": "a", "start": 1, "end": 2, "action": "take", "object": "knife"},
    ])
    segments = load_annotation(path)
    assert len(segments) == 1
    assert segments[0].start == 1.0


def test_missing_object_becomes_empty_string(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"id": "a", "start": 0, "end": 1, "action": "wash",
                              "object": None}])
    assert load_annotation(path)[0].object == ""


def test_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "clip.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoadError):
        load_annotation(path)


def test_non_numeric_bounds_raise(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"id": "a", "start": "x", "end": 1,
                              "action": "open", "object": "drawer"}])
    with pytest.raises(LoadError):
        load_annotation(path)


def test_partition_valid_splits_on_reversed_bounds() -> None:
    good = Segment("a", 0.0, 1.0, "open", "drawer")
    bad = Segment("b", 2.0, 1.0, "close", "drawer")
    assert partition_valid([good, bad]) == ([good], [bad])
