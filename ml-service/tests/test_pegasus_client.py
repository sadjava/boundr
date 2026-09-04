from __future__ import annotations

import pytest

from app.inference.pegasus.client import TwelveLabsError, structured_payload


class TestStructuredPayload:
    """Test payload extraction from SDK response format."""

    def test_valid_payload_with_dict(self):
        """Extract valid JSON dict from result.data."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": '{"actions": [{"id": "1"}]}',
                "finish_reason": "stop",
                "usage": {},
            },
        }
        payload = structured_payload(task)
        assert payload == {"actions": [{"id": "1"}]}

    def test_valid_payload_with_list(self):
        """Extract valid JSON list from result.data."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": '[{"id": "1"}, {"id": "2"}]',
                "finish_reason": "stop",
                "usage": {},
            },
        }
        payload = structured_payload(task)
        assert payload == [{"id": "1"}, {"id": "2"}]

    def test_missing_result_field(self):
        """Raise error when result field is missing."""
        task = {"status": "ready"}
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        assert "no 'result' field" in str(exc.value)

    def test_missing_data_field(self):
        """Raise error when data field is missing from result."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "finish_reason": "stop",
                "usage": {},
            },
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        assert "no 'data' field" in str(exc.value)

    def test_invalid_json_in_data(self):
        """Raise error when data is not valid JSON, with truncated excerpt."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": "not valid json {broken[",
                "finish_reason": "stop",
                "usage": {},
            },
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        error_msg = str(exc.value)
        assert "not valid JSON" in error_msg
        assert "not valid json {broken[" in error_msg

    def test_long_invalid_json_excerpt_truncated(self):
        """Truncate long invalid JSON strings in error excerpt."""
        long_bad_json = "x" * 300 + "{broken["
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": long_bad_json,
                "finish_reason": "stop",
                "usage": {},
            },
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        error_msg = str(exc.value)
        assert "excerpt:" in error_msg
        # Should be truncated to 200 chars
        assert len(error_msg) < len(long_bad_json)

    def test_data_not_string(self):
        """Raise error when data is not a string."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": {"already": "dict"},
                "finish_reason": "stop",
                "usage": {},
            },
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        assert "is not a string" in str(exc.value)

    def test_result_not_dict(self):
        """Raise error when result field is not a dict."""
        task = {
            "status": "ready",
            "result": "not a dict",
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        assert "is not a dict" in str(exc.value)
