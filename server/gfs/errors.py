from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GfsError(Exception):
    message: str
    status_code: int = 400
    error: str = "gfs_error"
    detail: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def to_json(self) -> dict[str, Any]:
        payload = {"ok": False, "error": self.error, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class InvalidBBoxError(GfsError):
    def __init__(self, message: str = "invalid bbox", detail: dict[str, Any] | None = None):
        super().__init__(message=message, status_code=400, error="invalid_bbox", detail=detail)


class ProviderUnavailableError(GfsError):
    def __init__(self, message: str = "provider unavailable", detail: dict[str, Any] | None = None):
        super().__init__(message=message, status_code=503, error="provider_unavailable", detail=detail)
