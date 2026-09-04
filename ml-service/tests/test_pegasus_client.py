from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.inference.pegasus.client import (
    TwelveLabsError,
    _wait_for_task,
    structured_payload,
)


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

    def test_payload_is_string_not_dict_or_list(self):
        """Raise error when decoded payload is a string, not dict or list."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": '"just a string"',
                "finish_reason": "stop",
                "usage": {},
            },
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        assert "must be dict or list" in str(exc.value)
        assert "str" in str(exc.value)

    def test_payload_is_int_not_dict_or_list(self):
        """Raise error when decoded payload is an int, not dict or list."""
        task = {
            "status": "ready",
            "result": {
                "generation_id": "g123",
                "data": "42",
                "finish_reason": "stop",
                "usage": {},
            },
        }
        with pytest.raises(TwelveLabsError) as exc:
            structured_payload(task)
        assert "must be dict or list" in str(exc.value)
        assert "int" in str(exc.value)


class TestWaitForTask:
    """Test the polling loop for task completion."""

    def _make_fake_client(self, responses: list[dict]) -> MagicMock:
        """Create a fake client that returns scripted task dicts."""
        def make_mock_with_dict(data):
            mock = MagicMock()
            mock.model_dump = lambda: data
            return mock

        client = MagicMock()
        # responses is a list of dicts to return on successive retrieve() calls
        client.analyze_async.tasks.retrieve.side_effect = [
            make_mock_with_dict(resp) for resp in responses
        ]
        return client

    def test_task_returns_ready_after_polling(self, monkeypatch):
        """Poll through processing states until ready."""
        sleep_calls = []
        monkeypatch.setattr(
            "app.inference.pegasus.client.time.sleep",
            lambda duration: sleep_calls.append(duration),
        )

        responses = [
            {"task_id": "t1", "status": "processing"},
            {"task_id": "t1", "status": "processing"},
            {"task_id": "t1", "status": "ready"},
        ]
        client = self._make_fake_client(responses)
        result = _wait_for_task(client, "t1", timeout=30.0)
        assert result["status"] == "ready"
        assert client.analyze_async.tasks.retrieve.call_count == 3
        assert len(sleep_calls) == 2  # Sleep between each processing response

    def test_task_failed_with_error_message(self):
        """Task failure includes API error message."""
        responses = [
            {
                "task_id": "t1",
                "status": "failed",
                "error": {"message": "API rate limit exceeded"},
            }
        ]
        client = self._make_fake_client(responses)
        with pytest.raises(TwelveLabsError) as exc:
            _wait_for_task(client, "t1", timeout=30.0)
        error_msg = str(exc.value)
        assert "failed" in error_msg
        assert "API rate limit exceeded" in error_msg

    def test_task_timeout_includes_last_status(self, monkeypatch):
        """Timeout error names the last-seen status."""
        sleep_calls = []
        monkeypatch.setattr(
            "app.inference.pegasus.client.time.sleep",
            lambda duration: sleep_calls.append(duration),
        )

        # Mock time.time to advance on each call so timeout triggers
        time_counter = [0.0]

        def mock_time():
            current = time_counter[0]
            time_counter[0] += 0.06  # Advance by 60ms per call
            return current

        monkeypatch.setattr("app.inference.pegasus.client.time.time", mock_time)

        responses = [
            {"task_id": "t1", "status": "processing"},
            {"task_id": "t1", "status": "pending"},
        ]
        client = self._make_fake_client(responses)
        with pytest.raises(TwelveLabsError) as exc:
            _wait_for_task(client, "t1", timeout=0.1)
        error_msg = str(exc.value)
        assert "did not complete" in error_msg
        assert "pending" in error_msg

    def test_ready_on_first_call_no_sleep(self, monkeypatch):
        """Ready status on first retrieve returns immediately without sleeping."""
        sleep_calls = []
        monkeypatch.setattr(
            "app.inference.pegasus.client.time.sleep",
            lambda duration: sleep_calls.append(duration),
        )

        responses = [{"task_id": "t1", "status": "ready"}]
        client = self._make_fake_client(responses)
        result = _wait_for_task(client, "t1", timeout=30.0)
        assert result["status"] == "ready"
        assert sleep_calls == []  # No sleep calls recorded

    def test_polling_sleeps_between_attempts(self, monkeypatch):
        """Sleep with correct interval occurs between poll attempts."""
        from app.inference.pegasus.client import POLL_INTERVAL

        sleep_calls = []
        monkeypatch.setattr(
            "app.inference.pegasus.client.time.sleep",
            lambda duration: sleep_calls.append(duration),
        )

        responses = [
            {"task_id": "t1", "status": "processing"},
            {"task_id": "t1", "status": "ready"},
        ]
        client = self._make_fake_client(responses)
        _wait_for_task(client, "t1", timeout=30.0)
        assert sleep_calls == [POLL_INTERVAL]
