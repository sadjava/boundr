import httpx

from app.config import get_settings

settings = get_settings()


def _headers() -> dict[str, str]:
    return {"X-Internal-Token": settings.internal_api_token}


def fetch_dataset(job_id: str) -> dict:
    with httpx.Client(timeout=60.0) as client:
        r = client.get(
            f"{settings.backend_url}/api/internal/fine-tunes/{job_id}/dataset",
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


def mark_processing(job_id: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.backend_url}/api/internal/fine-tunes/{job_id}/status",
            json={"status": "PROCESSING"},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


def mark_complete(job_id: str, s3_prefix: str, manifest: dict) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.backend_url}/api/internal/fine-tunes/{job_id}/complete",
            json={"s3_prefix": s3_prefix, "manifest": manifest},
            headers=_headers(),
        )
        r.raise_for_status()


def mark_failed(job_id: str, error_msg: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{settings.backend_url}/api/internal/fine-tunes/{job_id}/fail",
            json={"error_msg": error_msg[:4000]},
            headers=_headers(),
        )
        r.raise_for_status()
