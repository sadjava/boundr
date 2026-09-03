from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

MOCK_ACTIONS = ["pour", "push", "put", "pick_up"]
MOCK_OBJECTS = ["cup", "bottle", "person", "cabinet", "counter"]


@dataclass
class JobContext:
    job_id: str
    video_id: str
    s3_key: str
    project_id: str = ""
    action_types: list[str] | None = None
    objects: list[str] | None = None


@dataclass
class VideoMeta:
    duration: float
    fps: float


def ffprobe_meta(video_path: str) -> VideoMeta:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    duration = float(payload.get("format", {}).get("duration") or 0)
    fps = 30.0
    for stream in payload.get("streams", []):
        if stream.get("codec_type") == "video":
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
            if rate and rate != "0/0":
                num, _, den = rate.partition("/")
                try:
                    fps = float(num) / float(den or 1)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            break
    return VideoMeta(duration=duration, fps=fps)


def smoke_extract_frame(video_path: str) -> None:
    fd, out = tempfile.mkstemp(suffix=".jpg", prefix="vtas-frame-")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "0",
                "-i",
                video_path,
                "-frames:v",
                "1",
                out,
            ],
            capture_output=True,
            check=True,
        )
    finally:
        if os.path.exists(out):
            os.remove(out)


def pick_action(ctx: JobContext, i: int) -> str:
    pool = [a for a in (ctx.action_types or []) if a] or MOCK_ACTIONS
    return pool[i % len(pool)]


def pick_object(ctx: JobContext) -> str:
    pool = [o for o in (ctx.objects or []) if o] or MOCK_OBJECTS
    return random.choice(pool)


def make_segment(start: float, end: float, action: str, obj: str) -> dict:
    start = round(start, 3)
    end = round(end, 3)
    return {
        "id": str(uuid.uuid4()),
        "start": start,
        "end": end,
        "action": action,
        "object": obj,
        "keyframe": round(start + (end - start) * 0.4, 3),
    }


def mock_segments(windows: list[tuple[float, float]], duration: float, ctx: JobContext) -> list[dict]:
    if duration <= 0:
        duration = 5.0
    return [
        make_segment(sf * duration, ef * duration, pick_action(ctx, i), pick_object(ctx))
        for i, (sf, ef) in enumerate(windows)
    ]


class Inference(ABC):
    name: str
    version: int = 1

    def run(self, video_path: str, ctx: JobContext) -> dict:
        meta = ffprobe_meta(video_path)
        smoke_extract_frame(video_path)
        return {
            "video_id": ctx.video_id,
            "duration": meta.duration,
            "fps": meta.fps,
            "segments": self.infer(meta, ctx),
        }

    @abstractmethod
    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        """Replace this in each inference type folder."""
