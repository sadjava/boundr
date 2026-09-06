from __future__ import annotations

import json
from io import BytesIO

import pytest

from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.marlin.gpt_postprocess import parse_with_gpt, segments_from_json
from app.inference.marlin.infer import MarlinGptInference


def test_marlin_gpt_uses_base_runner_and_scales_timestamps(monkeypatch):
    monkeypatch.setattr(
        "app.inference.marlin.infer._caption",
        lambda _path: ("<0 - 10> A hand opens a door.", 60.0),
    )
    monkeypatch.setattr(
        "app.inference.marlin.gpt_postprocess._complete",
        lambda _prompt: json.dumps(
            {"segments": [{"start": 10.0, "end": 20.0, "action": "open", "object": "door"}]}
        ),
    )
    ctx = JobContext(job_id="j", video_id="v", s3_key="", video_path="video.mp4")

    assert MarlinGptInference.run is Inference.run
    assert MarlinGptInference.name == "marlin_gpt"
    out = MarlinGptInference().infer(VideoMeta(120.0, 30.0), ctx)
    assert [(s["start"], s["end"], s["action"], s["object"]) for s in out] == [
        (20.0, 40.0, "open", "door"),
    ]


def test_segments_from_json_accepts_fences_and_action_type():
    parsed = segments_from_json(
        """```json
        {"segments": [{"start": 2, "end": 4, "action_type": "open", "object": "door"}]}
        ```""",
        8,
        JobContext("j", "v", ""),
    )
    assert [(s["action"], s["object"], s["start"], s["end"]) for s in parsed] == [
        ("open", "door", 2.0, 4.0),
    ]


def test_segments_from_json_maps_catalog_labels():
    ctx = JobContext("j", "v", "", action_types=["pick_up"], objects=["card"])
    parsed = segments_from_json(
        '{"segments": [{"start": 0, "end": 1, "action": "Pick Up", "object": "Card"}]}',
        1,
        ctx,
    )
    assert [(s["action"], s["object"]) for s in parsed] == [("pick_up", "card")]


def test_segments_from_json_drops_labels_outside_catalog():
    ctx = JobContext("j", "v", "", action_types=["pick_up"], objects=["card"])
    assert segments_from_json(
        '{"segments": [{"start": 0, "end": 1, "action": "pull_out", "object": "card"}]}',
        1,
        ctx,
    ) == []


def test_parse_with_gpt_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        "app.inference.marlin.gpt_postprocess.get_settings",
        lambda: type("S", (), {"openrouter_api_key": "", "openrouter_base_url": ""})(),
    )
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        parse_with_gpt("<0 - 1> A hand opens a door.", 1, JobContext("j", "v", ""))


def test_parse_with_gpt_posts_json_object(monkeypatch):
    captured: dict = {}

    class Response:
        def __enter__(self):
            return BytesIO(json.dumps({
                "choices": [{"message": {"content": '{"segments":[{"start":0,"end":1,"action":"open","object":"door"}]}'}}],
            }).encode())

        def __exit__(self, *_exc):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data)
        captured["auth"] = request.headers.get("Authorization")
        return Response()

    monkeypatch.setattr(
        "app.inference.marlin.gpt_postprocess.get_settings",
        lambda: type(
            "S",
            (),
            {
                "openrouter_api_key": "sk-test",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
            },
        )(),
    )
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    parsed = parse_with_gpt("<0 - 1> A hand opens a door.", 1, JobContext("j", "v", ""))
    assert [(s["action"], s["object"]) for s in parsed] == [("open", "door")]
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["timeout"] == 120
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "openai/gpt-4o-mini"
    assert captured["body"]["response_format"] == {"type": "json_object"}
