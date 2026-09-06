from __future__ import annotations

from app.inference.base import (
    Inference,
    JobContext,
    VideoMeta,
    extract_frames,
    mock_segments,
)
from app.inference.dense import DenseInference
from app.inference.marlin import MarlinGptInference, MarlinInference
from app.inference.overlap import OverlapInference
from app.inference.pegasus import PegasusAnalyzeInference, PegasusSegmentInference
from app.inference.sequential import SequentialInference

PIPELINES: dict[str, type[Inference]] = {
    "marlin": MarlinInference,
    "marlin_gpt": MarlinGptInference,
    "overlap": OverlapInference,
    "stub": OverlapInference,
    "": OverlapInference,
    "sequential": SequentialInference,
    "dense": DenseInference,
    "pegasus_analyze": PegasusAnalyzeInference,
    "pegasus_segment": PegasusSegmentInference,
}


def get_pipeline(name: str) -> Inference:
    # Fine-tuned checkpoints reuse MarlinInference; llama.cpp still serves stock marlin-2b
    # until real GGUF loading is wired.
    if name.startswith("marlin_ft_"):
        return MarlinInference()
    cls = PIPELINES.get(name)
    if cls is None:
        raise ValueError(f"Unknown pipeline: {name}")
    return cls()


__all__ = [
    "Inference",
    "JobContext",
    "VideoMeta",
    "extract_frames",
    "get_pipeline",
    "PIPELINES",
]


if __name__ == "__main__":
    ctx = JobContext(job_id="j", video_id="x", s3_key="")
    seq = SequentialInference().infer(VideoMeta(10.0, 30.0), ctx)
    assert not any(
        a["start"] < b["end"] and b["start"] < a["end"]
        for i, a in enumerate(seq)
        for b in seq[i + 1 :]
    )
    segs = OverlapInference().infer(VideoMeta(10.0, 30.0), ctx)
    overlap = any(
        a["start"] < b["end"] and b["start"] < a["end"]
        for i, a in enumerate(segs)
        for b in segs[i + 1 :]
    )
    assert overlap, "overlap mock should emit overlapping actions"
    labeled = mock_segments(
        OverlapInference.WINDOWS,
        10.0,
        JobContext(job_id="j", video_id="x", s3_key="", action_types=["alpha"], objects=["thing"]),
    )
    assert all(s["action"] == "alpha" for s in labeled)
    assert all(s["object"] == "thing" for s in labeled)
    open_vocab = OverlapInference().infer(VideoMeta(10.0, 30.0), ctx)
    assert all(s["object"] for s in open_vocab)
    assert ctx.action_types is None and ctx.objects is None
    import os
    import subprocess
    import tempfile

    root = tempfile.mkdtemp(prefix="boundr-infer-")
    vid = os.path.join(root, "t.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x32:d=1", "-pix_fmt", "yuv420p", vid],
        check=True,
        capture_output=True,
    )
    frames = extract_frames(vid, os.path.join(root, "frames"), fps=1)
    assert frames and all(os.path.isfile(p) for p in frames)
    ran = JobContext(job_id="j", video_id="x", s3_key="")
    out = OverlapInference().run(vid, ran)
    assert ran.video_path == vid
    assert out["segments"]
    assert OverlapInference.version == 2
    assert SequentialInference.version == 2
    assert DenseInference.version == 2
    assert MarlinInference.version == 7
    assert MarlinGptInference.version == 2
    assert isinstance(get_pipeline("marlin_ft_abc123"), MarlinInference)
    print("ok")
