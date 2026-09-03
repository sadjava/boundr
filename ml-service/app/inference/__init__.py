from __future__ import annotations

from app.inference.base import Inference, JobContext, VideoMeta, mock_segments
from app.inference.dense import DenseInference
from app.inference.overlap import OverlapInference
from app.inference.sequential import SequentialInference

PIPELINES: dict[str, type[Inference]] = {
    "overlap": OverlapInference,
    "stub": OverlapInference,
    "": OverlapInference,
    "sequential": SequentialInference,
    "dense": DenseInference,
}


def get_pipeline(name: str) -> Inference:
    cls = PIPELINES.get(name)
    if cls is None:
        raise ValueError(f"Unknown pipeline: {name}")
    return cls()


__all__ = [
    "Inference",
    "JobContext",
    "VideoMeta",
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
    assert OverlapInference.version == 2
    assert SequentialInference.version == 2
    assert DenseInference.version == 2
    print("ok")
