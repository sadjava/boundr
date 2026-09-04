from __future__ import annotations

from app.inference import get_pipeline
from app.inference.base import JobContext
from app.inference.pegasus import PegasusAnalyzeInference, PegasusSegmentInference


def test_pipelines_are_registered():
    assert get_pipeline("pegasus_analyze").name == "pegasus_analyze"
    assert get_pipeline("pegasus_segment").name == "pegasus_segment"


def test_pipeline_versions_and_timeout():
    assert PegasusAnalyzeInference.version == 1
    assert PegasusSegmentInference.version == 1
    assert PegasusAnalyzeInference.TIMEOUT == 600.0
    assert PegasusSegmentInference.TIMEOUT == 600.0


def test_prompts_carry_the_project_vocabulary():
    ctx = JobContext(
        job_id="j", video_id="v", s3_key="", action_types=["alpha"], objects=["thing"]
    )
    for cls in (PegasusAnalyzeInference, PegasusSegmentInference):
        text = cls().build_prompt(ctx)
        assert "alpha" in text, cls.name
        assert "thing" in text, cls.name


def test_prompts_stay_open_without_a_vocabulary():
    ctx = JobContext(job_id="j", video_id="v", s3_key="")
    for cls in (PegasusAnalyzeInference, PegasusSegmentInference):
        assert "pour" in cls().build_prompt(ctx), cls.name
