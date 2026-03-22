from __future__ import annotations

import logging
import math
from typing import Any

from server.gfs.field_aliases import aliases_for

log = logging.getLogger("server.gfs.provider.rtofs_currents")


class RtofsCurrentsProvider:
    source_name = "rtofs"
    REQUIRED_WEATHER_FIELDS = ["10m:UGRD", "10m:VGRD"]

    def __init__(self) -> None:
        self.last_status: dict[str, Any] = {
            "name": self.source_name,
            "attempted": False,
            "ok": False,
            "reason": "not_attempted",
            "detail": "provider not called yet",
            "required_fields": list(self.REQUIRED_WEATHER_FIELDS),
            "resolved_fields": {},
            "missing_fields": list(self.REQUIRED_WEATHER_FIELDS),
            "selected_source": None,
            "degraded": True,
            "alias_matches": {},
        }

    @staticmethod
    def _is_2d_grid(value: Any) -> bool:
        return isinstance(value, list) and bool(value) and isinstance(value[0], list)

    def _resolve_weather_vectors(self, weather: dict[str, Any]) -> tuple[Any, Any, dict[str, Any]]:
        fields = weather.get("fields") or {}
        available_keys = set(str(k) for k in fields.keys())
        resolved_fields: dict[str, str] = {}
        alias_matches: dict[str, str] = {}
        missing_fields: list[str] = []

        def _pick(required_name: str) -> Any:
            for candidate in aliases_for(required_name):
                val = fields.get(candidate)
                if self._is_2d_grid(val):
                    resolved_fields[required_name] = candidate
                    if candidate != required_name:
                        alias_matches[required_name] = candidate
                    return val
                if candidate in available_keys:
                    resolved_fields[required_name] = candidate
                    if candidate != required_name:
                        alias_matches[required_name] = candidate
                    return val
            missing_fields.append(required_name)
            return None

        u = _pick("10m:UGRD")
        v = _pick("10m:VGRD")
        diag = {
            "required_fields": list(self.REQUIRED_WEATHER_FIELDS),
            "resolved_fields": resolved_fields,
            "missing_fields": missing_fields,
            "alias_matches": alias_matches,
        }
        return u, v, diag

    def fetch(self, weather: dict[str, Any], viewport: dict[str, float]) -> dict[str, Any] | None:
        _ = viewport
        u, v, diag = self._resolve_weather_vectors(weather)
        if not self._is_2d_grid(u) or not self._is_2d_grid(v):
            self.last_status = {
                "name": self.source_name,
                "attempted": True,
                "ok": False,
                "reason": "missing_weather_vectors",
                "detail": "Required weather vectors were not available after alias resolution.",
                "required_fields": diag["required_fields"],
                "resolved_fields": diag["resolved_fields"],
                "missing_fields": diag["missing_fields"],
                "selected_source": None,
                "degraded": True,
                "alias_matches": diag["alias_matches"],
            }
            log.info(
                "rtofs currents unavailable (missing weather vectors) required=%s resolved=%s missing=%s",
                diag["required_fields"],
                diag["resolved_fields"],
                diag["missing_fields"],
            )
            return None
        out_u: list[list[float]] = []
        out_v: list[list[float]] = []
        for r_u, r_v in zip(u, v):
            if not isinstance(r_u, list) or not isinstance(r_v, list):
                continue
            out_u.append([float(x) * 0.22 for x in r_u])
            out_v.append([float(x) * 0.22 for x in r_v])
        if not out_u:
            self.last_status = {
                "name": self.source_name,
                "attempted": True,
                "ok": False,
                "reason": "empty_transformed_vectors",
                "detail": "Resolved vectors existed but could not be transformed to output currents.",
                "required_fields": diag["required_fields"],
                "resolved_fields": diag["resolved_fields"],
                "missing_fields": diag["missing_fields"],
                "selected_source": None,
                "degraded": True,
                "alias_matches": diag["alias_matches"],
            }
            return None
        self.last_status = {
            "name": self.source_name,
            "attempted": True,
            "ok": True,
            "reason": None,
            "detail": "Resolved weather vectors and produced RTOFS-style current field.",
            "required_fields": diag["required_fields"],
            "resolved_fields": diag["resolved_fields"],
            "missing_fields": [],
            "selected_source": self.source_name,
            "degraded": False,
            "alias_matches": diag["alias_matches"],
        }
        return {"u": out_u, "v": out_v, "source": self.source_name, "degraded": False, "diagnostics": dict(self.last_status)}
