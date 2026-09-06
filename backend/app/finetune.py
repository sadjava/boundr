"""Fine-tune name validation and defaults."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

# Fits jobs.pipeline / fine_tunes.name varchar(32): "marlin_ft_" + up to 22 chars.
FINE_TUNE_NAME_RE = re.compile(r"^marlin_ft_[a-z0-9_]{1,22}$")
_MAX_NAME = 32


def slugify_project(name: str, max_len: int = 8) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return (cleaned or "proj")[:max_len]


def default_fine_tune_name(project_name: str = "proj") -> str:
    """marlin_ft_{project}_{YYYYMMDD}_{hex} — unique, ≤32 chars."""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = secrets.token_hex(2)  # 4 hex chars
    # 10 ("marlin_ft_") + slug + 1 + 8 + 1 + 4 ≤ 32 → slug ≤ 8
    slug = slugify_project(project_name, max_len=8)
    return f"marlin_ft_{slug}_{date}_{suffix}"


def default_display_name(project_name: str, pipeline_name: str) -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proj = (project_name or "project").strip() or "project"
    return f"{proj} · {date} ({pipeline_name})"


def validate_fine_tune_name(name: str) -> str:
    cleaned = (name or "").strip().lower()
    if len(cleaned) > _MAX_NAME or not FINE_TUNE_NAME_RE.match(cleaned):
        raise ValueError(
            "name must match marlin_ft_<suffix> (lowercase letters, digits, underscore; "
            f"at most {_MAX_NAME} chars total)"
        )
    return cleaned


if __name__ == "__main__":
    assert FINE_TUNE_NAME_RE.match("marlin_ft_a3f21c")
    assert FINE_TUNE_NAME_RE.match("marlin_ft_wh_ab12")
    assert not FINE_TUNE_NAME_RE.match("marlin")
    assert not FINE_TUNE_NAME_RE.match("marlin_ft_")
    assert not FINE_TUNE_NAME_RE.match("Marlin_ft_abc")
    n = default_fine_tune_name("Warehouse Cam")
    assert n.startswith("marlin_ft_warehous_"), n  # slug truncated to 8 chars
    assert validate_fine_tune_name(n) == n
    assert len(n) <= 32, n
    assert slugify_project("My Project!!") == "my_proje"  # default max_len=8
    assert slugify_project("My Project!!", max_len=20) == "my_project"
    from app.s3 import fine_tune_s3_prefix

    prefix = fine_tune_s3_prefix("u1", "ft1")
    assert prefix == "users/u1/models/ft1/"
    assert not prefix.startswith("projects/")
    print("ok")
