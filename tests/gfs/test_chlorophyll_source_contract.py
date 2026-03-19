from __future__ import annotations

import json

from server.gfs.models import BBox
from server.gfs.providers.coastwatch import CHL_DATASET_META, CoastwatchProvider
from server.gfs.source_check import build_source_check_payload


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_chl_dataset_meta_backward_compatible_contract():
    assert isinstance(CHL_DATASET_META, dict)
    assert CHL_DATASET_META["var_name"] == "chlorophyll"
    assert "dataset" in CHL_DATASET_META


def test_source_check_payload_preserves_legacy_sources_shape():
    payload = build_source_check_payload()
    assert payload["ok"] is True
    assert payload["mock_bbox"] == [-118.6, 32.6, -117.8, 33.4]
    assert "coastwatch_chlorophyll" in payload["sources"]
    assert payload["sources"]["chlorophyll"]["primary"]["var_name"] == "chlorophyll"
    assert payload["sources"]["chlorophyll"]["fallback"]["var_name"] == "chlor_a"


def test_chlorophyll_provider_falls_back_to_coastwatch_when_nasa_fails(monkeypatch):
    seen = []

    def _urlopen(req, timeout=0):
        _ = timeout
        url = req.full_url if hasattr(req, "full_url") else str(req)
        seen.append(url)
        if "erdMH1chla8day" in url:
            raise RuntimeError("NASA outage")
        if "noaacwNPPN20VIIRSDINEOFDaily" in url:
            return _Resp(b"time,latitude,longitude,chlor_a\n2024-01-01T00:00:00Z,34,-120,0.8\n")
        return _Resp(json.dumps({}).encode())

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)

    payload, _ = CoastwatchProvider()._fetch_subset_sync(bbox=BBox(-121, 33, -119, 35), stride=4, valid_time=None)

    assert payload["chlorophyll"]
    assert payload["source_meta"]["bio_dataset"] == "coastwatch"
    assert any("erdMH1chla8day" in url for url in seen)
    assert any("noaacwNPPN20VIIRSDINEOFDaily" in url for url in seen)
