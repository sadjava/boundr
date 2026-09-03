from fastapi import Header, HTTPException, status

from app.config import get_settings

settings = get_settings()


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not x_internal_token or x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")
