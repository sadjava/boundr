from __future__ import annotations

from app.inference import get_pipeline
from app.inference.base import JobContext, VideoMeta
from app.inference.pegasus import PegasusAnalyzeInference, PegasusSegmentInference
from app.inference.pegasus.segment import _segment_definitions


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
    text = PegasusAnalyzeInference().build_prompt(ctx)
    assert "alpha" in text
    assert "thing" in text
    definitions = _segment_definitions(ctx)
    description = definitions["segment_definitions"][0]["description"]
    assert "alpha" in description
    assert "thing" in description


def test_prompts_stay_open_without_a_vocabulary():
    ctx = JobContext(job_id="j", video_id="v", s3_key="")
    assert "pour" in PegasusAnalyzeInference().build_prompt(ctx)
    definitions = _segment_definitions(ctx)
    assert "pour" in definitions["segment_definitions"][0]["description"]


def test_analyze_pipeline_calls_with_correct_mode_and_format(monkeypatch):
    """Verify analyze pipeline uses general mode with json_schema response format."""
    call_args = {}

    def fake_analyze(video_path, **kwargs):
        call_args.update(kwargs)
        return {"actions": [{"action_type": "pour", "object": "cup", "start": 1.0, "end": 2.0}]}

    # Monkeypatch call_analyze in the analyze module
    import app.inference.pegasus.analyze
    monkeypatch.setattr(app.inference.pegasus.analyze, "call_analyze", fake_analyze)

    meta = VideoMeta(duration=10.0, fps=30.0)
    ctx = JobContext(job_id="j", video_id="v", s3_key="")
    pipeline = PegasusAnalyzeInference()
    segments = pipeline.infer(meta, ctx)

    # Verify the API was called with correct parameters
    assert call_args["analysis_mode"] == "general"
    assert call_args["response_format"]["type"] == "json_schema"
    assert call_args["timeout"] == 600.0
    assert "Detect" in call_args["prompt"]

    # Verify output segments satisfy the contract
    assert len(segments) == 1
    seg = segments[0]
    assert set(seg.keys()) == {"id", "start", "end", "action", "object", "keyframe"}
    assert seg["start"] <= seg["keyframe"] <= seg["end"]
    assert seg["action"] == "pour"
    assert seg["object"] == "cup"


def test_segment_pipeline_calls_with_correct_mode_and_format(monkeypatch):
    """Verify segment pipeline uses time_based_metadata mode with segment_definitions format."""
    call_args = {}

    def fake_analyze(video_path, **kwargs):
        call_args.update(kwargs)
        return {
            "human_action": [
                {
                    "start_time": 1.0,
                    "end_time": 2.0,
                    "metadata": {"action_type": "pour", "object": "cup"},
                }
            ]
        }

    # Monkeypatch call_analyze in the segment module
    import app.inference.pegasus.segment
    monkeypatch.setattr(app.inference.pegasus.segment, "call_analyze", fake_analyze)

    meta = VideoMeta(duration=10.0, fps=30.0)
    ctx = JobContext(job_id="j", video_id="v", s3_key="")
    pipeline = PegasusSegmentInference()
    segments = pipeline.infer(meta, ctx)

    # Verify the API was called with correct parameters
    assert call_args["analysis_mode"] == "time_based_metadata"
    assert call_args["response_format"]["type"] == "segment_definitions"
    assert call_args["timeout"] == 600.0
    # SME mode rejects the prompt parameter; the instructions live in the description
    assert "prompt" not in call_args
    description = call_args["response_format"]["segment_definitions"][0]["description"]
    assert "Each continuous interval" in description

    # Verify output segments satisfy the contract
    assert len(segments) == 1
    seg = segments[0]
    assert set(seg.keys()) == {"id", "start", "end", "action", "object", "keyframe"}
    assert seg["start"] <= seg["keyframe"] <= seg["end"]
    assert seg["action"] == "pour"
    assert seg["object"] == "cup"


def test_analyze_pipeline_includes_vocabulary_in_api_call(monkeypatch):
    """Verify analyze pipeline includes project vocabulary in the API prompt."""
    call_args = {}

    def fake_analyze(video_path, **kwargs):
        call_args.update(kwargs)
        return {"actions": [{"action_type": "stir", "object": "pot", "start": 0.5, "end": 1.5}]}

    import app.inference.pegasus.analyze
    monkeypatch.setattr(app.inference.pegasus.analyze, "call_analyze", fake_analyze)

    meta = VideoMeta(duration=5.0, fps=24.0)
    ctx = JobContext(
        job_id="j", video_id="v", s3_key="",
        action_types=["stir", "pour"], objects=["pot", "cup"]
    )
    pipeline = PegasusAnalyzeInference()
    segments = pipeline.infer(meta, ctx)

    # Verify vocabulary labels are in the prompt
    prompt = call_args["prompt"]
    assert "stir" in prompt
    assert "pour" in prompt
    assert "pot" in prompt
    assert "cup" in prompt
    assert len(segments) == 1


def test_segment_pipeline_includes_vocabulary_in_api_call(monkeypatch):
    """Verify segment pipeline folds the project vocabulary into the definitions."""
    call_args = {}

    def fake_analyze(video_path, **kwargs):
        call_args.update(kwargs)
        return {
            "human_action": [
                {
                    "start_time": 0.5,
                    "end_time": 1.5,
                    "metadata": {"action_type": "stir", "object": "pot"},
                }
            ]
        }

    import app.inference.pegasus.segment
    monkeypatch.setattr(app.inference.pegasus.segment, "call_analyze", fake_analyze)

    meta = VideoMeta(duration=5.0, fps=24.0)
    ctx = JobContext(
        job_id="j", video_id="v", s3_key="",
        action_types=["stir", "pour"], objects=["pot", "cup"]
    )
    pipeline = PegasusSegmentInference()
    segments = pipeline.infer(meta, ctx)

    # Verify vocabulary labels are in the segment description, not the prompt
    assert "prompt" not in call_args
    description = call_args["response_format"]["segment_definitions"][0]["description"]
    assert "stir" in description
    assert "pour" in description
    assert "pot" in description
    assert "cup" in description
    assert len(segments) == 1
