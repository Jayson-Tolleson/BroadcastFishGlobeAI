from __future__ import annotations

from typing import Any

from server.gfs.providers.coastwatch import CHL_DATASET_META, CHL_DATASET_SOURCES
from server.gfs.providers.rtofs import HYCOM_DATASET_META

MOCK_BBOX = [-118.6, 32.6, -117.8, 33.4]


def build_source_check_payload() -> dict[str, Any]:
    nasa_source = CHL_DATASET_SOURCES[0] if CHL_DATASET_SOURCES else CHL_DATASET_META
    coastwatch_fallback = CHL_DATASET_SOURCES[1] if len(CHL_DATASET_SOURCES) > 1 else CHL_DATASET_META

    payload = {
        "ok": True,
        "mock_bbox": MOCK_BBOX,
        "sources": {
            "thredds_gfs": {"status": "configured"},
            "hycom_ncss_ocean": {
                "dataset": HYCOM_DATASET_META.get("dataset"),
                "lon_convention": HYCOM_DATASET_META.get("lon_convention"),
                "request_vars": HYCOM_DATASET_META.get("request_vars", []),
            },
            "coastwatch_chlorophyll": {
                "dataset": CHL_DATASET_META.get("dataset"),
                "var_name": CHL_DATASET_META.get("var_name"),
                "lon_convention": CHL_DATASET_META.get("lon_convention"),
            },
            "chlorophyll": {
                "primary": {
                    "name": nasa_source.get("name", "nasa_8day"),
                    "dataset": nasa_source.get("dataset"),
                    "var_name": nasa_source.get("var_name", "chlorophyll"),
                },
                "fallback": {
                    "name": coastwatch_fallback.get("name", "coastwatch"),
                    "dataset": coastwatch_fallback.get("dataset"),
                    "var_name": coastwatch_fallback.get("var_name", "chlor_a"),
                },
            },
        },
    }
    return payload


__all__ = ["MOCK_BBOX", "build_source_check_payload", "CHL_DATASET_META", "CHL_DATASET_SOURCES"]
