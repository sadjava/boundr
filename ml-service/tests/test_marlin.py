from __future__ import annotations

import json
import subprocess

import pytest

from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.marlin.infer import MarlinInference, _sample_video
from app.inference.marlin.postprocess import parse_manipulations


def test_marlin_uses_base_runner_and_scales_timestamps(monkeypatch):
    monkeypatch.setattr(
        "app.inference.marlin.infer._caption",
        lambda _path: ("caption", 60.0),
    )
    ctx = JobContext(job_id="j", video_id="v", s3_key="", video_path="video.mp4")
    pipeline = MarlinInference(
        lambda _text, _duration, _ctx: [
            {"id": "s", "start": 10.0, "end": 20.0, "keyframe": 14.0}
        ]
    )

    assert MarlinInference.run is Inference.run
    assert pipeline.infer(VideoMeta(120.0, 30.0), ctx) == [
        {"id": "s", "start": 20.0, "end": 40.0, "keyframe": 28.0}
    ]


def test_marlin_rejects_videos_over_two_minutes():
    with pytest.raises(ValueError, match="up to 120 seconds"):
        MarlinInference().infer(
            VideoMeta(120.001, 30.0),
            JobContext(job_id="j", video_id="v", s3_key="", video_path="video.mp4"),
        )


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), float("inf")])
def test_marlin_rejects_invalid_duration(duration):
    with pytest.raises(ValueError, match="finite positive"):
        MarlinInference().infer(
            VideoMeta(duration, 30.0),
            JobContext(job_id="j", video_id="v", s3_key="", video_path="video.mp4"),
        )


def test_marlin_object_fallback_stays_inside_the_human_clause():
    segments = parse_manipulations(
        "<0 - 2> The person covers the pot and stirs, while the camera pans.",
        2.0,
        JobContext(job_id="j", video_id="v", s3_key=""),
    )

    assert [(segment["action"], segment["object"]) for segment in segments] == [
        ("cover", "pot"),
        ("stir", "pot"),
    ]


def test_marlin_sampler_keeps_two_frames_per_second(tmp_path):
    source = tmp_path / "source.mp4"
    sampled = tmp_path / "sampled.mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=red:s=32x32:r=30:d=3", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
    )

    assert _sample_video(str(source), str(sampled)) == 3.0
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,nb_read_frames", "-of", "json",
        str(sampled),
    ]))["streams"][0]
    assert probe == {"avg_frame_rate": "2/1", "nb_read_frames": "6"}
