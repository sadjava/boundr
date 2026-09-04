from __future__ import annotations

from app.inference.base import Inference, JobContext, VideoMeta, mock_segments


class OverlapInference(Inference):
    name = "overlap"
    version = 2
    WINDOWS = [(0.00, 0.42), (0.18, 0.55), (0.40, 0.78), (0.62, 1.00)]

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        # action_types, objects = ctx.action_types, ctx.objects  # None = open vocab
        # extract_frames(ctx.video_path, dest_dir, fps=1) → jpeg paths
        windows = self.WINDOWS[:3] if meta.duration < 8 else self.WINDOWS
        return mock_segments(windows, meta.duration, ctx)
