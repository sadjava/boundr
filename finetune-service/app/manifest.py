from __future__ import annotations

import json
from typing import Any


def build_manifest(
    dataset: dict[str, Any],
    downloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Stub training manifest — no real Unsloth run in this mock."""
    return {
        "mocked": True,
        "name": dataset.get("name"),
        "project_id": dataset.get("project_id"),
        "task_ids": dataset.get("task_ids") or [],
        "videos": [
            {
                "video_id": item["video_id"],
                "s3_key": item["s3_key"],
                "bytes": item["bytes"],
                "segment_count": item["segment_count"],
            }
            for item in downloads
        ],
        "video_count": len(downloads),
        "total_bytes": sum(item["bytes"] for item in downloads),
    }


if __name__ == "__main__":
    manifest = build_manifest(
        {
            "name": "marlin_ft_abc123",
            "project_id": "p1",
            "task_ids": ["t1"],
        },
        [
            {
                "video_id": "v1",
                "s3_key": "projects/p1/videos/v1/original.mp4",
                "bytes": 100,
                "segment_count": 2,
            }
        ],
    )
    assert manifest["mocked"] is True
    assert manifest["video_count"] == 1
    assert manifest["total_bytes"] == 100
    assert manifest["videos"][0]["segment_count"] == 2
    print(json.dumps(manifest, indent=2))
    print("ok")
