from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalViewport:
    west: float
    south: float
    east: float
    north: float
    stride: int = 1

    def as_dict(self) -> dict[str, float | int]:
        return {
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
            "stride": self.stride,
        }

    def as_bbox(self) -> list[float]:
        return [self.west, self.south, self.east, self.north]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def snap_value(value: float, step: float) -> float:
    return round(value / step) * step


def canonicalize_viewport(raw: dict[str, Any] | None) -> CanonicalViewport:
    raw = raw or {}
    west = _safe_float(raw.get("west"), -180.0)
    south = _safe_float(raw.get("south"), -80.0)
    east = _safe_float(raw.get("east"), 180.0)
    north = _safe_float(raw.get("north"), 80.0)

    if east <= west:
        east = west + 0.5
    if north <= south:
        north = south + 0.5

    span = max(east - west, north - south)
    stride = 4 if span > 14 else 2 if span > 6 else 1
    step = 0.25 * stride

    west = max(-179.9, snap_value(west, step))
    south = max(-89.9, snap_value(south, step))
    east = min(179.9, snap_value(east, step))
    north = min(89.9, snap_value(north, step))
    return CanonicalViewport(west=west, south=south, east=east, north=north, stride=stride)


def parse_viewport_args(args: Any) -> CanonicalViewport:
    raw_bbox = args.get("bbox") if hasattr(args, "get") else None
    if isinstance(raw_bbox, str) and raw_bbox.strip():
        try:
            west, south, east, north = [float(part.strip()) for part in raw_bbox.split(",")]
            return canonicalize_viewport({"west": west, "south": south, "east": east, "north": north})
        except Exception:
            pass
    raw = {
        "west": args.get("west") if hasattr(args, "get") else None,
        "south": args.get("south") if hasattr(args, "get") else None,
        "east": args.get("east") if hasattr(args, "get") else None,
        "north": args.get("north") if hasattr(args, "get") else None,
    }
    return canonicalize_viewport(raw)
