from __future__ import annotations

from app.inference.base import Inference, JobContext, VideoMeta, mock_segments


class DenseInference(Inference):
    name = "dense"
    version = 2
    WINDOWS = [
        (0.00, 0.28),
        (0.12, 0.38),
        (0.30, 0.55),
        (0.48, 0.72),
        (0.65, 0.88),
        (0.80, 1.00),
    ]

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        return mock_segments(self.WINDOWS, meta.duration, ctx)
