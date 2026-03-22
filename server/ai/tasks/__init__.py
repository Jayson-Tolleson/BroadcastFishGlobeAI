from __future__ import annotations

from typing import Any


def score_value(payload: dict[str, Any], key: str, default: float = 0.5) -> float:
    raw = payload.get(key, default)
    try:
        value = float(raw)
    except Exception:
        value = float(default)
    return max(0.0, min(1.0, value))
