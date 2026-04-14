from __future__ import annotations

from typing import Any


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "10m:UGRD": ("10m:UGRD", "10m:u10", "10m:u"),
    "10m:VGRD": ("10m:VGRD", "10m:v10", "10m:v"),
    "isobaricInhPa:UGRD": ("isobaricInhPa:UGRD", "isobaricInhPa:u"),
    "isobaricInhPa:VGRD": ("isobaricInhPa:VGRD", "isobaricInhPa:v"),
    "isobaricInhPa:TMP": ("isobaricInhPa:TMP", "isobaricInhPa:t"),
    "isobaricInhPa:RH": ("isobaricInhPa:RH", "isobaricInhPa:r"),
    "isobaricInhPa:HGT": ("isobaricInhPa:HGT", "isobaricInhPa:gh"),
}


def aliases_for(name: str) -> tuple[str, ...]:
    return FIELD_ALIASES.get(name, (name,))


def resolve_aliases(available: set[str], required: list[str]) -> dict[str, Any]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    alias_matches: dict[str, str] = {}
    for req in required:
        matched = next((candidate for candidate in aliases_for(req) if candidate in available), None)
        if matched is None:
            missing.append(req)
            continue
        resolved[req] = matched
        if matched != req:
            alias_matches[req] = matched
    return {
        "resolved": resolved,
        "missing": missing,
        "alias_matches": alias_matches,
    }
