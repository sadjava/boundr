from __future__ import annotations

import json
import os
import time

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MODEL_NAME = "pegasus1.5"
TEMPERATURE = 0.2
POLL_INTERVAL = 3.0


class TwelveLabsError(RuntimeError):
    pass


def _as_dict(obj: object) -> dict:
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            return fn()
    if isinstance(obj, dict):
        return obj
    raise TwelveLabsError(f"cannot convert SDK response of type {type(obj).__name__}")


def structured_payload(task_result: dict) -> dict | list:
    """Extract and decode the structured payload from AnalyzeTaskResult.data."""
    if "result" not in task_result:
        raise TwelveLabsError(
            f"task result has no 'result' field, keys: {sorted(task_result)}"
        )

    task_result_obj = task_result["result"]
    if not isinstance(task_result_obj, dict):
        raise TwelveLabsError(
            f"task result field is not a dict: {type(task_result_obj).__name__}"
        )

    data_str = task_result_obj.get("data")
    if data_str is None:
        raise TwelveLabsError(
            f"task result has no 'data' field, keys: {sorted(task_result_obj)}"
        )

    if not isinstance(data_str, str):
        raise TwelveLabsError(
            f"task result data is not a string: {type(data_str).__name__}"
        )

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError as e:
        excerpt = data_str[:200]
        raise TwelveLabsError(
            f"task result data is not valid JSON: {e}; excerpt: {excerpt}"
        )

    if not isinstance(payload, (dict, list)):
        raise TwelveLabsError(
            f"structured payload must be dict or list, got {type(payload).__name__}"
        )

    return payload


def _wait_for_task(client, task_id: str, timeout: float) -> dict:
    """Poll tasks.retrieve() until task reaches terminal state or timeout."""
    start = time.time()
    while True:
        task = _as_dict(client.analyze_async.tasks.retrieve(task_id=task_id))
        status = str(task.get("status") or "").lower()

        if status == "ready":
            return task
        if status == "failed":
            error = task.get("error", {})
            error_msg = (
                error.get("message", "unknown error")
                if isinstance(error, dict)
                else str(error)
            )
            raise TwelveLabsError(f"analyze task {task_id} failed: {error_msg}")

        # Check timeout
        elapsed = time.time() - start
        if elapsed > timeout:
            raise TwelveLabsError(
                f"analyze task {task_id} did not complete within {timeout} "
                f"seconds (status: {status})"
            )

        time.sleep(POLL_INTERVAL)


def analyze(
    video_path: str,
    *,
    prompt: str,
    response_format: dict,
    analysis_mode: str,
    timeout: float,
    api_key: str,
) -> dict | list:
    if not api_key:
        raise TwelveLabsError("TWELVELABS_API_KEY is not set")

    size = os.path.getsize(video_path)
    if size > MAX_UPLOAD_BYTES:
        raise TwelveLabsError(
            f"video is {size} bytes, TwelveLabs direct upload limit is {MAX_UPLOAD_BYTES}"
        )

    # Imported lazily so a broken or missing SDK does not take the consumer down at startup.
    from twelvelabs import TwelveLabs

    client = TwelveLabs(api_key=api_key)
    with open(video_path, "rb") as fh:
        asset = _as_dict(client.assets.create(method="direct", file=fh))
    asset_id = asset.get("id") or asset.get("asset_id")
    if not asset_id:
        raise TwelveLabsError(f"asset upload returned no id, keys: {sorted(asset)}")

    task = _as_dict(
        client.analyze_async.tasks.create(
            video={"type": "asset_id", "asset_id": asset_id},
            model_name=MODEL_NAME,
            temperature=TEMPERATURE,
            prompt=prompt,
            analysis_mode=analysis_mode,
            response_format=response_format,
        )
    )
    task_id = task.get("id") or task.get("task_id")
    if not task_id:
        raise TwelveLabsError(f"analyze task returned no id, keys: {sorted(task)}")

    result = _wait_for_task(client, task_id, timeout)

    # Check finish_reason in the nested result object
    task_result_obj = result.get("result", {})
    if isinstance(task_result_obj, dict):
        finish_reason = str(task_result_obj.get("finish_reason") or "").lower()
        if finish_reason == "length":
            raise TwelveLabsError(
                f"analyze task {task_id} was truncated (finish_reason=length); "
                "segments are incomplete"
            )

    return structured_payload(result)
