from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GFSState:
    enabled: bool = True
    source_name: str = "gfs"
    cache_ttl_seconds: int = 30
    last_refresh_ts: int | None = None
    last_error: str | None = None

    ingest_status: str = "idle"
    ingest_last_attempt_ts: int | None = None
    ingest_last_success_ts: int | None = None
    ingest_error: str | None = None
    degraded_mode: bool = False
    using_last_known_good: bool = False

    model_cycle: str | None = None
    model_forecast_hour: int | None = None
    model_valid_time: str | None = None
    model_analysis_time: str | None = None
    model_source_url: str | None = None
    model_cache_path: str | None = None
    model_source_format: str = "grib2"

    fields_available: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    decode_backend: str = "none"
    data_source_mode: str = "heuristic"
    last_good_model_state: dict[str, Any] | None = None
    scalar_fields: dict[str, Any] = field(default_factory=dict)

    fish_points: list[dict[str, Any]] = field(default_factory=list)
    tile_cache: dict[str, Any] = field(default_factory=dict)
    scene_cache: dict[str, Any] | None = None
    scene_cache_ts: int | None = None
    tile_diagnostics: dict[str, Any] = field(default_factory=dict)
    layer_feature_index: dict[str, Any] = field(default_factory=dict)
    layer_feature_meta: dict[str, Any] = field(default_factory=dict)
    layer_feature_store: dict[str, Any] = field(default_factory=dict)
