from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.inference.pegasus.client import (
    MAX_UPLOAD_BYTES,
    TwelveLabsError,
    _wait_for_task,
    analyze,
    structured_payload,
)


class FakeResponse:
    """SDK models expose model_dump(); plain dicts slip through _as_dict as-is."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self) -> dict:
        return self._data


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
        assert "did not become ready" in error_msg
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


class TestAnalyze:
    """Test analyze() orchestration with a fake SDK client: no network, no key."""

    def _ready_client(self) -> MagicMock:
        """Client where upload, asset wait and task wait all succeed first try."""
        client = MagicMock()
        client.assets.create.return_value = FakeResponse(
            {"id": "asset1", "status": "ready"}
        )
        client.assets.retrieve.return_value = FakeResponse(
            {"id": "asset1", "status": "ready"}
        )
        client.assets.delete.return_value = None
        client.analyze_async.tasks.create.return_value = FakeResponse({"id": "task1"})
        client.analyze_async.tasks.retrieve.return_value = FakeResponse(
            {
                "status": "ready",
                "result": {
                    "data": '{"actions": [{"action_type": "pour", "start": 1.0, "end": 2.0}]}',
                    "finish_reason": "stop",
                },
            }
        )
        return client

    def _install(
        self,
        monkeypatch,
        client: MagicMock,
        tmp_path,
        size: int = 100,
    ) -> str:
        video_path = str(tmp_path / "fake.mp4")
        with open(video_path, "wb") as fh:
            fh.write(b"x")
        monkeypatch.setattr(
            "app.inference.pegasus.client.os.path.getsize", lambda p: size
        )
        monkeypatch.setattr(
            "app.inference.pegasus.client.time.sleep", lambda d: None
        )
        # analyze() imports the SDK lazily inside the function body; patch the
        # import site so the real SDK is never touched.
        monkeypatch.setattr("twelvelabs.TwelveLabs", lambda api_key: client)
        return video_path

    def test_empty_api_key_raises_before_any_client(self, monkeypatch, tmp_path):
        def boom(api_key):
            raise AssertionError("client constructed without a key")

        monkeypatch.setattr("twelvelabs.TwelveLabs", boom)
        path = self._install(monkeypatch, self._ready_client(), tmp_path)
        with pytest.raises(TwelveLabsError, match="TWELVELABS_API_KEY is not set"):
            analyze(
                path, prompt="p", response_format={}, analysis_mode="general",
                timeout=60.0, api_key="",
            )

    def test_oversized_file_raises_before_any_upload(self, monkeypatch, tmp_path):
        def boom(api_key):
            raise AssertionError("client constructed")

        monkeypatch.setattr("twelvelabs.TwelveLabs", boom)
        path = self._install(
            monkeypatch, self._ready_client(), tmp_path, size=MAX_UPLOAD_BYTES + 1
        )
        with pytest.raises(TwelveLabsError, match="upload limit"):
            analyze(
                path, prompt="p", response_format={}, analysis_mode="general",
                timeout=60.0, api_key="k",
            )

    def test_task_create_receives_asset_id_and_params(self, monkeypatch, tmp_path):
        client = self._ready_client()
        path = self._install(monkeypatch, client, tmp_path)
        analyze(
            path, prompt="p", response_format={"type": "x"}, analysis_mode="general",
            timeout=60.0, api_key="k",
        )
        kwargs = client.analyze_async.tasks.create.call_args.kwargs
        assert kwargs["video"] == {"type": "asset_id", "asset_id": "asset1"}
        assert kwargs["model_name"] == "pegasus1.5"
        assert kwargs["analysis_mode"] == "general"
        assert kwargs["response_format"] == {"type": "x"}
        assert kwargs["prompt"] == "p"

    def test_asset_is_waited_on_before_task_creation(self, monkeypatch, tmp_path):
        client = self._ready_client()
        client.assets.retrieve.side_effect = [
            FakeResponse({"id": "asset1", "status": "processing"}),
            FakeResponse({"id": "asset1", "status": "ready"}),
        ]
        path = self._install(monkeypatch, client, tmp_path)
        analyze(
            path, prompt="p", response_format={}, analysis_mode="general",
            timeout=60.0, api_key="k",
        )
        assert client.assets.retrieve.call_count == 2
        calls = client.mock_calls
        last_retrieve = max(
            i for i, c in enumerate(calls) if c[0] == "assets.retrieve"
        )
        first_create = min(
            i for i, c in enumerate(calls) if c[0] == "analyze_async.tasks.create"
        )
        assert last_retrieve < first_create

    def test_asset_deleted_on_success(self, monkeypatch, tmp_path):
        client = self._ready_client()
        path = self._install(monkeypatch, client, tmp_path)
        analyze(
            path, prompt="p", response_format={}, analysis_mode="general",
            timeout=60.0, api_key="k",
        )
        client.assets.delete.assert_called_once_with(asset_id="asset1")

    def test_asset_deleted_when_analysis_task_fails(self, monkeypatch, tmp_path):
        client = self._ready_client()
        client.analyze_async.tasks.retrieve.return_value = FakeResponse(
            {"task_id": "task1", "status": "failed", "error": {"message": "boom"}}
        )
        path = self._install(monkeypatch, client, tmp_path)
        with pytest.raises(TwelveLabsError, match="analyze task task1 failed"):
            analyze(
                path, prompt="p", response_format={}, analysis_mode="general",
                timeout=60.0, api_key="k",
            )
        client.assets.delete.assert_called_once_with(asset_id="asset1")

    def test_asset_deleted_when_asset_processing_fails(self, monkeypatch, tmp_path):
        client = self._ready_client()
        client.assets.retrieve.return_value = FakeResponse(
            {"id": "asset1", "status": "failed", "error": {"message": "corrupt file"}}
        )
        path = self._install(monkeypatch, client, tmp_path)
        with pytest.raises(TwelveLabsError, match="asset asset1 failed"):
            analyze(
                path, prompt="p", response_format={}, analysis_mode="general",
                timeout=60.0, api_key="k",
            )
        client.assets.delete.assert_called_once_with(asset_id="asset1")

    def test_finish_reason_length_raises(self, monkeypatch, tmp_path):
        client = self._ready_client()
        client.analyze_async.tasks.retrieve.return_value = FakeResponse(
            {
                "status": "ready",
                "result": {
                    "data": '{"actions": []}',
                    "finish_reason": "length",
                },
            }
        )
        path = self._install(monkeypatch, client, tmp_path)
        with pytest.raises(TwelveLabsError, match="truncated"):
            analyze(
                path, prompt="p", response_format={}, analysis_mode="general",
                timeout=60.0, api_key="k",
            )
        client.assets.delete.assert_called_once_with(asset_id="asset1")
