import secrets

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


def require_internal_key(
    x_internal_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Shared-secret auth between n8n and the API."""
    expected = settings.internal_api_key
    if not expected or not x_internal_key or not secrets.compare_digest(x_internal_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal key")
