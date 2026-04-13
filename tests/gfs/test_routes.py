import asyncio

import pytest
from quart import Quart
from server.app_factory import create_app

@pytest.fixture(name="app")
def app_fixture() -> Quart:
    """Create and configure a new app instance for each test."""
    app = create_app()
    app.config.update({"TESTING": True})
    # In a real test suite, we might mock external services here.
    # For this verification, we rely on the service's fallback mechanisms.
    return app

@pytest.fixture
def client(app: Quart):
    """A test client for the app."""
    return app.test_client()

def test_gfs_bootstrap_and_index(client):
    """
    Tests that the app boots and the GFS index page is served.
    This covers the basic contract of test_watch_and_gfs_bootstrap.py.
    """
    async def _run() -> None:
        response = await client.get("/gfs/")
        assert response.status_code == 200
        content = await response.get_data(as_text=True)
        assert 'id="globe"' in content
    asyncio.run(_run())

def test_gfs_api_health_contract(client):
    """
    Tests the /gfs/api/health endpoint for basic contract adherence.
    This covers a part of test_gfs_route_contract.py.
    """
    async def _run() -> None:
        response = await client.get("/gfs/api/health")
        assert response.status_code == 200
        data = await response.get_json()
        assert data["ok"] is True
        assert "ingest" in data
        assert "status" in data["ingest"]
        assert "fish_count" in data
    asyncio.run(_run())

def test_gfs_api_weather_contract(client):
    """
    Tests the /gfs/api/weather endpoint for payload structure.
    This covers a part of test_gfs_frontend_refresh_contract.py.
    The GFSService has fallbacks, so this should return a valid structure
    even if live data fetching fails in a test environment.
    """
    async def _run() -> None:
        response = await client.get("/gfs/api/weather")
        assert response.status_code in {200, 503}
        data = await response.get_json()
        # Endpoint contract for both live/stale and unavailable cases.
        assert "source" in data
        assert "source_status" in data
    asyncio.run(_run())

def test_gfs_api_tiles_contract(client):
    """
    Tests the /gfs/api/tiles/<layer>/... endpoint.
    """
    # Test a low-zoom tile for clouds
    async def _run() -> None:
        response = await client.get("/gfs/api/tiles/clouds/0/0/0")
        assert response.status_code == 200
        data = await response.get_json()
        assert "features" in data
        assert "meta" in data
        assert data["meta"]["layer"] == "clouds"
        assert "status" in data and "ok" in data["status"]
    asyncio.run(_run())

def test_gfs_api_location_media_contract(client):
    """
    Tests the location/media endpoints.
    """
    async def _run() -> None:
        location_key = "test-spot-123"
        response = await client.get(f"/gfs/api/location/{location_key}/media")
        assert response.status_code == 200
        data = await response.get_json()
        assert data["ok"] is True
        assert data["location_key"] == location_key
        assert data["report_text"] == ""
    asyncio.run(_run())
