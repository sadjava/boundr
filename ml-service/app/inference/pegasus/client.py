from __future__ import annotations

import json
import logging
import os
import time

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MODEL_NAME = "pegasus1.5"
TEMPERATURE = 0.2
POLL_INTERVAL = 3.0
# 2-minute job SLA. 32k tokens took ~6 minutes on P27_01; 4096 leaves room for upload.
MAX_TOKENS = 4096

logger = logging.getLogger(__name__)


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


def salvage_truncated_json(text: str) -> dict | list:
    """Parse JSON, or drop an incomplete tail and close open [ { so json.loads works.

    TwelveLabs sets finish_reason=length and may cut the string mid-object. The
    complete prefix is kept; the truncated last item is discarded.
    """
    text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    else:
        if isinstance(payload, (dict, list)):
            return payload
        raise TwelveLabsError(
            f"structured payload must be dict or list, got {type(payload).__name__}"
        )

    if not text or text[0] not in "{[":
        raise TwelveLabsError(f"task result data is not valid JSON; excerpt: {text[:200]}")

    recovered: dict | list | None = None
    in_string = False
    escape = False
    depth: list[str] = []
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth.append("}")
        elif ch == "[":
            depth.append("]")
        elif ch in "}]":
            if not depth or depth[-1] != ch:
                break
            depth.pop()
            got = _closed_prefix(text[: i + 1], depth)
            if got is not None:
                recovered = got

    if recovered is None:
        raise TwelveLabsError(
            f"task result data is not valid JSON; excerpt: {text[:200]}"
        )
    return recovered


def _closed_prefix(prefix: str, depth: list[str]) -> dict | list | None:
    candidate = prefix.rstrip().rstrip(",") + "".join(reversed(depth))
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, (dict, list)) else None


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
        try:
            payload = salvage_truncated_json(data_str)
            logger.warning("Salvaged truncated TwelveLabs JSON")
        except TwelveLabsError:
            excerpt = data_str[:200]
            raise TwelveLabsError(
                f"task result data is not valid JSON: {e}; excerpt: {excerpt}"
            ) from e

    if not isinstance(payload, (dict, list)):
        raise TwelveLabsError(
            f"structured payload must be dict or list, got {type(payload).__name__}"
        )

    return payload


def _wait_for_status(client, *, retrieve, timeout: float, describe: str) -> dict:
    """Poll retrieve() until the object is ready or failed, bounded by the timeout budget."""
    start = time.time()
    while True:
        obj = _as_dict(retrieve())
        status = str(obj.get("status") or "").lower()

        if status == "ready":
            return obj
        if status == "failed":
            error = obj.get("error", {})
            error_msg = (
                error.get("message", "unknown error")
                if isinstance(error, dict)
                else str(error)
            )
            raise TwelveLabsError(f"{describe} failed: {error_msg}")

        elapsed = time.time() - start
        if elapsed > timeout:
            raise TwelveLabsError(
                f"{describe} did not become ready within {timeout} seconds "
                f"(status: {status})"
            )

        time.sleep(POLL_INTERVAL)


def _wait_for_task(client, task_id: str, timeout: float) -> dict:
    return _wait_for_status(
        client,
        retrieve=lambda: client.analyze_async.tasks.retrieve(task_id=task_id),
        timeout=timeout,
        describe=f"analyze task {task_id}",
    )


def _wait_for_asset(client, asset_id: str, timeout: float) -> dict:
    return _wait_for_status(
        client,
        retrieve=lambda: client.assets.retrieve(asset_id=asset_id),
        timeout=timeout,
        describe=f"asset {asset_id}",
    )


def _remaining(timeout: float, start: float) -> float:
    return max(timeout - (time.time() - start), 0.0)


def analyze(
    video_path: str,
    *,
    prompt: str | None = None,
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

    # One clock for the whole upload + analysis round trip: every wait gets the
    # remaining budget, so a stuck upload cannot double the stated TIMEOUT.
    start = time.time()
    asset_id: str | None = None
    try:
        with open(video_path, "rb") as fh:
            asset = _as_dict(client.assets.create(method="direct", file=fh))
        asset_id = asset.get("id") or asset.get("asset_id")
        if not asset_id:
            raise TwelveLabsError(f"asset upload returned no id, keys: {sorted(asset)}")

        # Uploads are processed asynchronously; the asset must be ready before use.
        _wait_for_asset(client, asset_id, _remaining(timeout, start))

        create_kwargs: dict = {
            "video": {"type": "asset_id", "asset_id": asset_id},
            "model_name": MODEL_NAME,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "analysis_mode": analysis_mode,
            "response_format": response_format,
        }
        # The API rejects the prompt parameter in SME mode (time_based_metadata) with a
        # 400; prompting there goes through response_format.segment_definitions[].description.
        if prompt is not None:
            create_kwargs["prompt"] = prompt
        task = _as_dict(
            client.analyze_async.tasks.create(**create_kwargs)
        )
        task_id = task.get("id") or task.get("task_id")
        if not task_id:
            raise TwelveLabsError(f"analyze task returned no id, keys: {sorted(task)}")

        result = _wait_for_task(client, task_id, _remaining(timeout, start))

        task_result_obj = result.get("result", {})
        if isinstance(task_result_obj, dict):
            finish_reason = str(task_result_obj.get("finish_reason") or "").lower()
            if finish_reason == "length":
                logger.warning(
                    "analyze task %s truncated (finish_reason=length); "
                    "keeping a valid JSON prefix",
                    task_id,
                )

        return structured_payload(result)
    finally:
        # Every job, successful or failed, leaves an asset behind on the account.
        # Never mask the real error: deletion failures are logged, not raised.
        if asset_id:
            try:
                client.assets.delete(asset_id=asset_id)
            except Exception as exc:
                logger.warning(
                    "Failed to delete TwelveLabs asset %s: %s", asset_id, exc
                )
