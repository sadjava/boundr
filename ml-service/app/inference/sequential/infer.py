from __future__ import annotations

from app.inference.base import Inference, JobContext, VideoMeta, mock_segments


class SequentialInference(Inference):
    name = "sequential"
    version = 2
    WINDOWS = [(0.00, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.00)]

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        windows = self.WINDOWS[:3] if meta.duration < 8 else self.WINDOWS
        return mock_segments(windows, meta.duration, ctx)
