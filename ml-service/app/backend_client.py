import httpx

from app.config import get_settings

settings = get_settings()


def _headers() -> dict[str, str]:
    return {"X-Internal-Token": settings.internal_api_token}


def mark_processing(job_id: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.backend_url}/api/internal/jobs/{job_id}/status",
            json={"status": "PROCESSING"},
            headers=_headers(),
        )
        r.raise_for_status()


def mark_complete(
    job_id: str, annotation: dict, s3_key: str, duration: float, model_version: int = 1
) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.backend_url}/api/internal/jobs/{job_id}/complete",
            json={
                "annotation": annotation,
                "s3_key": s3_key,
                "duration": duration,
                "model_version": model_version,
            },
            headers=_headers(),
        )
        r.raise_for_status()


def mark_failed(job_id: str, error_msg: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.backend_url}/api/internal/jobs/{job_id}/fail",
            json={"error_msg": error_msg[:4000]},
            headers=_headers(),
        )
        r.raise_for_status()
