from __future__ import annotations

import asyncio

from server.app_factory import create_app


def test_ws_gfs_route_is_registered_authoritative():
    app = create_app()
    rules = {str(rule.rule) for rule in app.url_map.iter_rules()}
    assert "/ws/gfs" in rules
    # legacy compatibility path may exist under /gfs/ws via blueprint websocket.
    assert "/gfs/ws" in rules


def test_locations_and_intelligence_share_canonical_identity(monkeypatch):
    app = create_app()
    app.config.update({"TESTING": True})
    engine = app.extensions["gfs_engine"]

    canonical = "csv-canonical-key-1"
    fake_item = {
        "id": "noncanonical-id",
        "location_key": canonical,
        "name": "Canonical Spot",
        "lat": 33.1,
        "lon": -117.2,
        "confidence": 0.8,
        "probability": 0.8,
    }

    monkeypatch.setattr(
        engine,
        "locations_fast",
        lambda bbox, budget_ms=1800: {
            "ok": True,
            "source": "fish_csv",
            "entity_type": "location_markers",
            "derived": False,
            "items": [fake_item],
            "count": 1,
        },
    )
    monkeypatch.setattr(
        engine,
        "location_media",
        lambda location_key: {
            "ok": True,
            "location_key": location_key,
            "report_text": "steady bite",
            "uploads": [],
            "live": {"active": False, "stream_url": "", "updated_at": None},
            "ts": 123,
        },
    )

    async def _run() -> None:
        client = app.test_client()
        locations_resp = await client.get("/gfs/api/locations")
        assert locations_resp.status_code == 200
        locations_data = await locations_resp.get_json()
        assert locations_data["count"] == 1
        marker = locations_data["locations"][0]
        assert marker["id"] == canonical
        assert marker["location_key"] == canonical

        loc_resp = await client.get(f"/gfs/api/location/{canonical}")
        intel_resp = await client.get(f"/gfs/api/intelligence/node/{canonical}")
        assert loc_resp.status_code == 200
        assert intel_resp.status_code == 200
        loc_data = await loc_resp.get_json()
        intel_data = await intel_resp.get_json()

        assert loc_data["id"] == canonical
        assert loc_data["location_key"] == canonical
        assert intel_data["id"] == canonical
        assert intel_data["location_key"] == canonical
        assert loc_data == intel_data

    asyncio.run(_run())
