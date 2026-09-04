from __future__ import annotations

import pytest

from app.inference.base import JobContext
from app.inference.pegasus.mapping import (
    parse_analyze_payload,
    parse_segment_payload,
    to_segments,
    vocabulary_prompt,
)


def ctx(**kwargs) -> JobContext:
    return JobContext(job_id="j", video_id="v", s3_key="", **kwargs)


def test_open_vocabulary_prompt_shows_examples():
    text = vocabulary_prompt(ctx())
    assert "pour" in text


def test_closed_vocabulary_prompt_lists_labels():
    text = vocabulary_prompt(ctx(action_types=["alpha"], objects=["thing"]))
    assert "alpha" in text
    assert "thing" in text


def test_parse_analyze_payload_normalises_records():
    payload = {
        "actions": [
            {"action_type": "pour", "object": "cup", "start": 1.0, "end": 2.5},
            {"action_type": "push", "start": 3.0, "end": 4.0},
        ]
    }
    assert parse_analyze_payload(payload) == [
        {"action": "pour", "object": "cup", "start": 1.0, "end": 2.5},
        {"action": "push", "object": None, "start": 3.0, "end": 4.0},
    ]


def test_parse_analyze_payload_rejects_unknown_shape():
    with pytest.raises(ValueError):
        parse_analyze_payload({"nonsense": 1})


def test_parse_segment_payload_accepts_definition_keyed_shape():
    payload = {
        "human_action": [
            {
                "start_time": 0.5,
                "end_time": 1.5,
                "metadata": {"action_type": "grab", "object": "bottle"},
            }
        ]
    }
    assert parse_segment_payload(payload) == [
        {"action": "grab", "object": "bottle", "start": 0.5, "end": 1.5}
    ]


def test_parse_segment_payload_accepts_multiple_definition_keys():
    entry = {
        "start_time": 0.5,
        "end_time": 1.5,
        "metadata": {"action_type": "grab", "object": "bottle"},
    }
    payload = {"human_action": [entry], "other_definition": [entry]}
    assert len(parse_segment_payload(payload)) == 2


def test_parse_segment_payload_skips_entry_with_missing_metadata():
    payload = {
        "human_action": [
            {"start_time": 0.5, "end_time": 1.5},
            {
                "start_time": 2.0,
                "end_time": 3.0,
                "metadata": {"action_type": "push", "object": "cart"},
            },
        ]
    }
    assert parse_segment_payload(payload) == [
        {"action": "push", "object": "cart", "start": 2.0, "end": 3.0}
    ]


def test_parse_segment_payload_skips_entry_with_non_dict_metadata():
    payload = {
        "human_action": [
            {"start_time": 0.5, "end_time": 1.5, "metadata": "not a dict"},
        ]
    }
    assert parse_segment_payload(payload) == []


def test_parse_segment_payload_rejects_unknown_shape():
    with pytest.raises(ValueError):
        parse_segment_payload({"nonsense": 1})


def test_parse_segment_payload_rejects_list():
    with pytest.raises(ValueError):
        parse_segment_payload([{"human_action": []}])


def test_to_segments_produces_contract_fields():
    raw = [{"action": "pour", "object": "cup", "start": 1.0, "end": 2.5}]
    seg = to_segments(raw, duration=10.0)[0]
    assert set(seg) == {"id", "start", "end", "action", "object", "keyframe"}
    assert seg["start"] <= seg["keyframe"] <= seg["end"]
    assert isinstance(seg["id"], str) and seg["id"]


def test_to_segments_blanks_missing_object():
    raw = [{"action": "push", "object": None, "start": 3.0, "end": 4.0}]
    assert to_segments(raw, duration=10.0)[0]["object"] == ""


def test_to_segments_sorts_by_start():
    raw = [
        {"action": "b", "object": "", "start": 5.0, "end": 6.0},
        {"action": "a", "object": "", "start": 1.0, "end": 2.0},
    ]
    assert [s["action"] for s in to_segments(raw, duration=10.0)] == ["a", "b"]


def test_to_segments_clips_to_duration():
    raw = [{"action": "a", "object": "", "start": -1.0, "end": 99.0}]
    seg = to_segments(raw, duration=10.0)[0]
    assert seg["start"] == 0.0
    assert seg["end"] == 10.0


def test_to_segments_skips_clamping_when_duration_unknown():
    raw = [
        {"action": "a", "object": "", "start": 1.0, "end": 99.0},
        {"action": "b", "object": "", "start": -5.0, "end": 50.0},
    ]
    segs = to_segments(raw, duration=0.0)
    # b's negative start is still clamped to 0.0 (outside the duration guard),
    # so it sorts first. a's end=99.0 stays unclamped (inside the guard).
    assert segs[0]["action"] == "b"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 50.0
    assert segs[1]["action"] == "a"
    assert segs[1]["start"] == 1.0
    assert segs[1]["end"] == 99.0


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "reversed", "object": "", "start": 5.0, "end": 4.0},
        {"action": "zero", "object": "", "start": 3.0, "end": 3.0},
        {"action": "", "object": "x", "start": 6.0, "end": 7.0},
        {"action": "bad_number", "object": "", "start": "x", "end": 8.0},
        {"action": "nan_start", "object": "", "start": float("nan"), "end": 5.0},
        {"action": "nan_end", "object": "", "start": 1.0, "end": float("nan")},
        {"action": "inf_end", "object": "", "start": 1.0, "end": float("inf")},
    ],
)
def test_to_segments_drops_unusable_records(bad):
    good = {"action": "good", "object": "", "start": 1.0, "end": 2.0}
    assert [s["action"] for s in to_segments([good, bad], duration=10.0)] == ["good"]


def test_to_segments_raises_on_empty_result():
    # A silently empty annotation looks like a pipeline that found nothing.
    with pytest.raises(ValueError):
        to_segments([], duration=10.0)
