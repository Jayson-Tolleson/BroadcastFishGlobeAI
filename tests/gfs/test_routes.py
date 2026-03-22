import pytest
from quart import Quart
from server.app_factory import create_app

# Mark all tests in this file as async for pytest-asyncio
pytestmark = pytest.mark.asyncio

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

async def test_gfs_bootstrap_and_index(client):
    """
    Tests that the app boots and the GFS index page is served.
    This covers the basic contract of test_watch_and_gfs_bootstrap.py.
    """
    response = await client.get("/gfs/")
    assert response.status_code == 200
    content = await response.get_data(as_text=True)
    assert "GFS Globe" in content
    assert 'id="globe-canvas"' in content

async def test_gfs_api_health_contract(client):
    """
    Tests the /gfs/api/health endpoint for basic contract adherence.
    This covers a part of test_gfs_route_contract.py.
    """
    response = await client.get("/gfs/api/health")
    assert response.status_code == 200
    data = await response.get_json()
    assert data["ok"] is True
    assert "ingest" in data
    assert "status" in data["ingest"]
    assert "fish_count" in data

async def test_gfs_api_weather_contract(client):
    """
    Tests the /gfs/api/weather endpoint for payload structure.
    This covers a part of test_gfs_frontend_refresh_contract.py.
    The GFSService has fallbacks, so this should return a valid structure
    even if live data fetching fails in a test environment.
    """
    response = await client.get("/gfs/api/weather")
    assert response.status_code == 200
    data = await response.get_json()

    # Check for key fields the frontend JS would need
    assert "ok" in data
    assert "source" in data
    assert "items" in data or "tiles" in data # 'items' is used in fallback, 'tiles' in real
    assert "scene" in data
    assert "summary" in data
    assert "meta" in data
    assert "status" in data
    assert data["status"]["ok"] is True

async def test_gfs_api_tiles_contract(client):
    """
    Tests the /gfs/api/tiles/<layer>/... endpoint.
    """
    # Test a low-zoom tile for clouds
    response = await client.get("/gfs/api/tiles/clouds/0/0/0")
    assert response.status_code == 200
    data = await response.get_json()
    assert "features" in data
    assert "meta" in data
    assert data["meta"]["layer"] == "clouds"
    assert data["status"]["ok"] is True

async def test_gfs_api_location_media_contract(client):
    """
    Tests the location/media endpoints.
    """
    location_key = "test-spot-123"
    # Get initial state
    response = await client.get(f"/gfs/api/location/{location_key}/media")
    assert response.status_code == 200
    data = await response.get_json()
    assert data["ok"] is True
    assert data["location_key"] == location_key
    assert data["report_text"] == ""