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
                "One atomic manipulation action performed by a person: a single "
                "verb applied to a single object. Start a new segment whenever the "
                "verb changes, the manipulated object changes, the acting hand "
                "changes, or the person grasps or releases something. Atomic actions "
                "are short, typically between 0.3 and 3 seconds; an interval longer "
                "than about 5 seconds almost certainly contains several actions and "
                "must be split. Never return a high-level task or activity as one "
                "segment: instead of a single 'make coffee' interval, return "
                "'grasp cup', 'pour water', 'stir', 'place cup' as separate "
                "segments. Segments may be adjacent or briefly overlap. Prefer more, "
                "shorter segments over fewer, longer ones. "
            ),
            "fields": [
                {
                    "name": "action_type",
                    "type": "string",
                    "description": (
                        "A single lowercase verb for this interval, e.g. pour, push, "
                        "grasp, lift, release. Exactly one verb: never a phrase with "
                        "'and', never a task name such as 'cooking' or 'assembly'."
                    ),
                },
                {
                    "name": "object",
                    "type": "string",
                    "description": (
                        "The single object directly manipulated during this interval, "
                        "e.g. cup, bottle. One object only; if the person manipulates "
                        "another object, that is a separate segment. Leave empty if no "
                        "object is identifiable."
                    ),
                },
            ],
        }
    ],
}


def _segment_definitions(ctx: JobContext) -> dict:
    """SEGMENT_DEFINITIONS with the vocabulary appended to the segment description.
    SME mode rejects the prompt parameter, so the description carries the prompting."""
    definitions = copy.deepcopy(SEGMENT_DEFINITIONS)
    definitions["segment_definitions"][0]["description"] += vocabulary_prompt(ctx)
    return definitions


class PegasusSegmentInference(Inference):
    name = "pegasus_segment"
    version = 2
    # Product SLA: one video must finish within two minutes.
    TIMEOUT = 120.0

    def infer(self, meta: VideoMeta, ctx: JobContext) -> list[dict]:
        payload = call_analyze(
            ctx.video_path,
            response_format=_segment_definitions(ctx),
            analysis_mode="time_based_metadata",
            timeout=self.TIMEOUT,
            api_key=get_settings().twelvelabs_api_key,
        )
        return to_segments(parse_segment_payload(payload), meta.duration)
