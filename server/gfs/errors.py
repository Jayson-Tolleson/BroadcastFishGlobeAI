from __future__ import annotations

from typing import Any


class GfsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "gfs_error", detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code)
        self.code = code
        self.detail = detail or {}

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": self.code,
            "message": self.message,
            "detail": self.detail,
        }
