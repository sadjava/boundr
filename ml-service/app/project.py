from __future__ import annotations

import json
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def _dsn() -> str:
    url = get_settings().database_url
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = json.loads(value or "[]")
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


def project_catalog(project_id: str) -> tuple[list[str], list[str]]:
    if not project_id:
        return [], []
    try:
        import psycopg

        with psycopg.connect(_dsn()) as conn:
            row = conn.execute(
                "SELECT action_types, objects FROM projects WHERE id = %s",
                (project_id,),
            ).fetchone()
    except Exception:
        logger.exception("Failed to load project %s catalogs from postgres", project_id)
        return [], []
    if not row:
        return [], []
    return _as_list(row[0]), _as_list(row[1])
