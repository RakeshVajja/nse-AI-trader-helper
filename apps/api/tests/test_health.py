"""Health check endpoint tests."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_default(async_client: AsyncClient):
    """Test that the /api/v1/health endpoint returns a valid response."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database"] in ("connected", "disconnected")
    assert "timestamp" in data
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_endpoint_healthy_state(async_client: AsyncClient):
    """Test /api/v1/health when database connection is successful."""
    with patch("app.api.v1.health.check_db_connection", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = True
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_health_endpoint_degraded_state(async_client: AsyncClient):
    """Test /api/v1/health when database connection fails."""
    with patch("app.api.v1.health.check_db_connection", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = False
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "disconnected"


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    """Test that root metadata endpoint responds correctly."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "NSE AI Trading Agent" in data["name"]
    assert data["status"] == "online"
