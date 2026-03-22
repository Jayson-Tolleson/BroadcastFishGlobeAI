from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class GfsConfig:
    debug_enabled: bool = False
    api_base: str = "/gfs/api"
    ws_base: str = "/ws/gfs"

    def to_dict(self) -> dict:
        return asdict(self)


def load_gfs_config(debug_enabled: bool = False) -> GfsConfig:
    return GfsConfig(debug_enabled=bool(debug_enabled))
