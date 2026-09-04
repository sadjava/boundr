from __future__ import annotations

import os
import time

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MODEL_NAME = "pegasus1.5"
TEMPERATURE = 0.2
POLL_INTERVAL = 3.0

# Keys the SDK may carry the structured payload under; checked in order.
PAYLOAD_KEYS = ("data", "result", "content", "output")


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


def structured_payload(result: dict) -> dict | list:
    for key in PAYLOAD_KEYS:
        value = result.get(key)
        if isinstance(value, (dict, list)):
            return value
    raise TwelveLabsError(f"no structured payload in task result, keys: {sorted(result)}")


def _wait_for_task(client, task_id: str, timeout: float) -> dict:
    """Poll tasks.retrieve() until task reaches terminal state or timeout."""
    start = time.time()
    while True:
        task = _as_dict(client.analyze_async.tasks.retrieve(task_id=task_id))
        status = str(task.get("status") or "").lower()

        # Check for terminal states
        if status in ("ready", "done", "completed"):
            return task
        if status == "failed":
            error = task.get("error", {})
            error_msg = error.get("message", "unknown error") if isinstance(error, dict) else str(error)
            raise TwelveLabsError(f"analyze task {task_id} failed: {error_msg}")

        # Check timeout
        elapsed = time.time() - start
        if elapsed > timeout:
            raise TwelveLabsError(
                f"analyze task {task_id} did not complete within {timeout} seconds (status: {status})"
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
            video={"type": "asset", "asset_id": asset_id},
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

    status = str(result.get("status") or "").lower()
    if status and status not in ("ready", "done", "completed"):
        raise TwelveLabsError(f"analyze task {task_id} finished with status {status}")
    if str(result.get("finish_reason") or "").lower() == "length":
        raise TwelveLabsError(
            f"analyze task {task_id} was truncated (finish_reason=length); segments are incomplete"
        )
    return structured_payload(result)
