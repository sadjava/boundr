from __future__ import annotations

from app.config import get_settings
from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.pegasus.client import analyze as call_analyze
from app.inference.pegasus.mapping import (
    parse_analyze_payload,
    to_segments,
    vocabulary_prompt,
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "description": "Detected human actions in the video, ordered by start time.",
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "description": (
                            "Verb / action label for this interval "
                            "(e.g. pour, push, pick_up)."
                        ),
                    },
                    "object": {
                        "type": "string",
                        "description": (
                            "Primary object involved in the action, if identifiable "
                            "(e.g. cup, bottle). Leave empty if no object is identifiable."
                        ),
                    },
                    "start": {
                        "type": "number",
                        "description": (
                            "Start time of the action in seconds from the beginning "
                            "of the video."
                        ),
                    },
                    "end": {
                        "type": "number",
                        "description": (
                            "End time of the action in seconds from the beginning of "
                            "the video. Must be >= start."
                        ),
                    },
                },
                "required": ["action_type", "start", "end"],
            },
        }
    },
    "required": ["actions"],
}


class PegasusAnalyzeInference(Inference):
    name = "pegasus_analyze"
    version = 2
    # Product SLA: one video must finish within two minutes.
    TIMEOUT = 120.0

    def build_prompt(self, ctx: JobContext) -> str:
        return (
            "Detect every distinct human action in this video. "
            "For each action return its start and end time in seconds. "
            + vocabulary_prompt(ctx)
        )

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        payload = call_analyze(
            ctx.video_path,
            prompt=self.build_prompt(ctx),
            response_format={"type": "json_schema", "json_schema": JSON_SCHEMA},
            analysis_mode="general",
            timeout=self.TIMEOUT,
            api_key=get_settings().twelvelabs_api_key,
        )
        return to_segments(parse_analyze_payload(payload), meta.duration)
