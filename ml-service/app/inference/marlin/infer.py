from __future__ import annotations

import base64
import json
import math
import os
import subprocess
import tempfile
import urllib.request
from fractions import Fraction

from app.config import get_settings
from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.marlin.gpt_postprocess import parse_with_gpt
from app.inference.marlin.postprocess import Postprocessor, parse_manipulations

PROMPT = (
    "Provide a spatial description of this clip followed by time-ranged events.\n"
    "For each event, give the time range as <start - end> and a short description."
)
MAX_VIDEO_DURATION = 120.0


def _validate_duration(duration: float) -> None:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Marlin requires a finite positive video duration")
    if duration > MAX_VIDEO_DURATION:
        raise ValueError(f"Marlin supports videos up to {MAX_VIDEO_DURATION:g} seconds")


def _sample_video(video_path: str, output_path: str) -> float:
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=nb_frames,nb_read_frames,avg_frame_rate,r_frame_rate",
                "-of", "json", video_path,
            ]
        )
    )["streams"][0]
    n_frames = int(next(
        value
        for value in (probe.get("nb_read_frames"), probe.get("nb_frames"))
        if value not in (None, "N/A")
    ))
    fps = Fraction(next(
        value
        for value in (probe.get("avg_frame_rate"), probe.get("r_frame_rate"))
        if value not in (None, "0/0")
    ))
    n_sampled = min(max(int(Fraction(n_frames) * 2 / fps), 4), 240, n_frames)
    if n_sampled < 2:
        raise ValueError("video must contain at least two frames")
    last = n_frames - 1
    steps = n_sampled - 1
    # Constant-size form of Python's round-to-even endpoint linspace.
    nearest = f"floor(n*{steps}/{last}+0.5)"
    lower = f"floor({nearest}*{last}/{steps})"
    remainder = f"mod({nearest}*{last}\\,{steps})"
    rounded = (
        f"{lower}+gt(2*{remainder}\\,{steps})"
        f"+eq(2*{remainder}\\,{steps})*mod({lower}\\,2)"
    )
    select = f"eq(n\\,{rounded})"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", video_path, "-vf",
            f"select={select},setpts=N/(2*TB),format=bgr0", "-an", "-c:v", "ffv1",
            "-level", "3", "-g", "1", "-r", "2", output_path,
        ],
        check=True,
    )
    return n_sampled / 2


def _caption(video_path: str) -> tuple[str, float]:
    with tempfile.TemporaryDirectory() as directory:
        sampled = os.path.join(directory, "video.mkv")
        model_duration = _sample_video(video_path, sampled)
        with open(sampled, "rb") as file:
            video = base64.b64encode(file.read()).decode()
    request = urllib.request.Request(
        get_settings().marlin_url,
        json.dumps(
            {
                "model": "marlin-2b",
                "messages": [{"role": "user", "content": [
                    {"type": "input_video", "input_video": {"data": video}},
                    {"type": "text", "text": PROMPT},
                ]}],
                "temperature": 0,
                "max_tokens": 2048,
                "cache_prompt": False,
            }
        ).encode(),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3600) as response:
        payload = json.load(response)
    message = payload["choices"][0]["message"]
    content = message.get("content") or message.get("reasoning_content") or ""
    return content.removeprefix("<think>\n"), model_duration


def _source_timeline(segments: list[dict], duration: float, model_duration: float) -> list[dict]:
    scale = duration / model_duration
    for segment in segments:
        for key in ("start", "end", "keyframe"):
            segment[key] = round(min(max(segment[key] * scale, 0.0), duration), 3)
    return segments


class MarlinInference(Inference):
    name = "marlin"
    version = 7

    def __init__(self, postprocessor: Postprocessor = parse_manipulations):
        self.postprocessor = postprocessor

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        _validate_duration(meta.duration)
        raw, model_duration = _caption(ctx.video_path)
        segments = self.postprocessor(raw, model_duration, ctx)
        return _source_timeline(segments, meta.duration, model_duration)


class MarlinGptInference(MarlinInference):
    name = "marlin_gpt"
    version = 2

    def __init__(self, postprocessor: Postprocessor = parse_with_gpt):
        super().__init__(postprocessor)


if __name__ == "__main__":
    _validate_duration(120.0)
    try:
        _validate_duration(120.001)
    except ValueError:
        pass
    else:
        raise AssertionError("videos longer than 120 seconds must be rejected")
    scaled = _source_timeline(
        [{"start": 30.0, "end": 60.0, "keyframe": 45.0}], 600.0, 120.0
    )
    assert scaled == [{"start": 150.0, "end": 300.0, "keyframe": 225.0}]
    print("ok")
