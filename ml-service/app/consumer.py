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
from app.inference import JobContext, get_pipeline
from app.project import project_catalog
from app.s3 import annotation_key_from_video_key, download_object, upload_json

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
    video_id = fields["video_id"]
    s3_key = fields["s3_key"]
    project_id = fields.get("project_id") or ""
    action_types, objects = project_catalog(project_id)
    ctx = JobContext(
        job_id=job_id,
        video_id=video_id,
        s3_key=s3_key,
        project_id=project_id,
        action_types=action_types,
        objects=objects,
    )
    tmp_path = None
    try:
        backend_client.mark_processing(job_id)
        fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="vtas-")
        os.close(fd)
        download_object(s3_key, tmp_path)
        pipeline = get_pipeline(fields.get("pipeline") or settings.pipeline)
        annotation = pipeline.run(tmp_path, ctx)
        ann_key = annotation_key_from_video_key(s3_key)
        upload_json(ann_key, json.dumps(annotation, indent=2).encode("utf-8"))
        duration = float(annotation.get("duration") or 0)
        backend_client.mark_complete(job_id, annotation, ann_key, duration, pipeline.version)
        logger.info("Job %s completed", job_id)
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        try:
            backend_client.mark_failed(job_id, f"{exc}\n{traceback.format_exc()}")
        except Exception:
            logger.exception("Failed to report failure for job %s", job_id)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def consume_loop() -> None:
    consumer = f"ml-{socket.gethostname()}-{os.getpid()}"
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
    _thread = threading.Thread(target=consume_loop, name="ml-consumer", daemon=True)
    _thread.start()


def stop_consumer() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
