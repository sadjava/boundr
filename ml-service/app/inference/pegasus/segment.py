from __future__ import annotations

import copy

from app.config import get_settings
from app.inference.base import Inference, JobContext, VideoMeta
from app.inference.pegasus.client import analyze as call_analyze
from app.inference.pegasus.mapping import (
    parse_segment_payload,
    to_segments,
    vocabulary_prompt,
)

SEGMENT_DEFINITIONS = {
    "type": "segment_definitions",
    "segment_time_format": "seconds",
    "segment_definitions": [
        {
            "id": "human_action",
            "description": (
                "Each continuous interval where a person performs a distinct "
                "manipulation action."
            ),
            "fields": [
                {
                    "name": "action_type",
                    "type": "string",
                    "description": "Verb / action label for this interval, e.g. pour, push.",
                },
                {
                    "name": "object",
                    "type": "string",
                    "description": (
                        "Primary object involved in the action, e.g. cup, bottle. "
                        "Leave empty if no object is identifiable."
                    ),
                },
            ],
        }
    ],
}


def _segment_definitions(ctx: JobContext) -> dict:
    """SEGMENT_DEFINITIONS with the vocabulary folded into the segment description.
    SME mode rejects the prompt parameter, so the description carries the prompting."""
    definitions = copy.deepcopy(SEGMENT_DEFINITIONS)
    base = (
        "Each continuous interval where a person performs a distinct "
        "manipulation action. "
    )
    definitions["segment_definitions"][0]["description"] = base + vocabulary_prompt(ctx)
    return definitions


class PegasusSegmentInference(Inference):
    name = "pegasus_segment"
    version = 1
    TIMEOUT = 600.0

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        payload = call_analyze(
            ctx.video_path,
            response_format=_segment_definitions(ctx),
            analysis_mode="time_based_metadata",
            timeout=self.TIMEOUT,
            api_key=get_settings().twelvelabs_api_key,
        )
        return to_segments(parse_segment_payload(payload), meta.duration)
