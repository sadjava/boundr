from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
import time
import traceback

import redis

from app import backend_client
from app.config import get_settings
from app.manifest import build_manifest
from app.s3 import download_object, upload_json

logger = logging.getLogger(__name__)
settings = get_settings()

_stop = threading.Event()
_thread: threading.Thread | None = None


def _ensure_group(r: redis.Redis) -> None:
    try:
        r.xgroup_create(settings.redis_stream, settings.redis_group, id="0", mkstream=True)
        logger.info("Created consumer group %s on %s", settings.redis_group, settings.redis_stream)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _process_message(fields: dict[str, str]) -> None:
    job_id = fields["job_id"]
    tmp_dir = None
    try:
        status_row = backend_client.mark_processing(job_id)
        if status_row.get("status") != "PROCESSING":
            logger.info(
                "Fine-tune %s skipped (status=%s)",
                job_id,
                status_row.get("status"),
            )
            return
        dataset = backend_client.fetch_dataset(job_id)
        videos = dataset.get("videos") or []
        if not videos:
            raise ValueError("dataset has no annotated videos with segments")

        s3_prefix = (dataset.get("s3_prefix") or "").rstrip("/") + "/"
        tmp_dir = tempfile.mkdtemp(prefix="boundr-ft-")
        downloads: list[dict] = []

        for video in videos:
            s3_key = video["s3_key"]
            video_id = video["video_id"]
            dest = os.path.join(tmp_dir, f"{video_id}.mp4")
            download_object(s3_key, dest)
            size = os.path.getsize(dest)
            if size <= 0:
                raise ValueError(f"downloaded empty object for {s3_key}")
            segments = video.get("segments") or []
            logger.info(
                "Downloaded video %s (%d bytes, %d segments) from %s",
                video_id,
                size,
                len(segments),
                s3_key,
            )
            downloads.append(
                {
                    "video_id": video_id,
                    "s3_key": s3_key,
                    "bytes": size,
                    "segment_count": len(segments),
                }
            )

        manifest = build_manifest(dataset, downloads)
        upload_json(
            f"{s3_prefix}manifest.json",
            json.dumps(manifest, indent=2).encode("utf-8"),
        )
        # Stub checkpoint — real Unsloth would write a GGUF here.
        upload_json(
            f"{s3_prefix}checkpoint.json",
            json.dumps(
                {
                    "mocked": True,
                    "name": dataset.get("name"),
                    "note": "placeholder; replace with GGUF from Unsloth",
                },
                indent=2,
            ).encode("utf-8"),
        )
        backend_client.mark_complete(job_id, s3_prefix, manifest)
        logger.info(
            "Fine-tune %s finished mock train (%d videos, prefix=%s)",
            job_id,
            len(downloads),
            s3_prefix,
        )
    except Exception as exc:
        logger.exception("Fine-tune %s failed", job_id)
        try:
            backend_client.mark_failed(job_id, f"{exc}\n{traceback.format_exc()}")
        except Exception:
            logger.exception("Failed to report failure for fine-tune %s", job_id)
    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            for name in os.listdir(tmp_dir):
                try:
                    os.remove(os.path.join(tmp_dir, name))
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass


def consume_loop() -> None:
    consumer = f"ft-{socket.gethostname()}-{os.getpid()}"
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    while not _stop.is_set():
        try:
            _ensure_group(r)
            break
        except Exception:
            logger.exception("Waiting for Redis stream")
            time.sleep(2)

    logger.info("Consumer %s listening on %s", consumer, settings.redis_stream)
    while not _stop.is_set():
        try:
            resp = r.xreadgroup(
                settings.redis_group,
                consumer,
                {settings.redis_stream: ">"},
                count=1,
                block=2000,
            )
        except Exception:
            logger.exception("XREADGROUP failed")
            time.sleep(2)
            continue
        if not resp:
            continue
        for _stream, messages in resp:
            for msg_id, fields in messages:
                _process_message(fields)
                try:
                    r.xack(settings.redis_stream, settings.redis_group, msg_id)
                except Exception:
                    logger.exception("XACK failed for %s", msg_id)


def start_consumer() -> None:
    global _thread
    _stop.clear()
    _thread = threading.Thread(target=consume_loop, name="ft-consumer", daemon=True)
    _thread.start()


def stop_consumer() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
