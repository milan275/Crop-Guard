"""
CropGuard AI — Tests: FastAPI endpoints (async).

Uses httpx.AsyncClient with the FastAPI app directly (no running server needed).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.config import settings

ADMIN_TOKEN = settings.admin_token

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        # Initialise DB
        from backend.database.db import init_db
        await init_db()
        yield ac


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Districts ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_districts(client):
    resp = await client.get("/districts")
    assert resp.status_code == 200
    data = resp.json()
    assert "districts" in data
    assert len(data["districts"]) >= 20


# ── Farm registration ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_valid_farm(client):
    resp = await client.post("/farms/register", json={
        "latitude":  30.901,
        "longitude": 75.857,
        "email":     "test@example.com",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "farm_id" in data
    assert data["farm_id"] is not None
    assert data["district"] is not None


@pytest.mark.asyncio
async def test_register_invalid_email(client):
    resp = await client.post("/farms/register", json={
        "latitude":  30.901,
        "longitude": 75.857,
        "email":     "not-an-email",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_outside_punjab(client):
    resp = await client.post("/farms/register", json={
        "latitude":  28.613,   # Delhi
        "longitude": 77.209,
        "email":     "delhi@example.com",
    })
    assert resp.status_code == 422
    data = resp.json()
    assert "location_outside_punjab" in str(data)


@pytest.mark.asyncio
async def test_register_invalid_coords(client):
    resp = await client.post("/farms/register", json={
        "latitude":  999.0,
        "longitude": 75.857,
        "email":     "bad@example.com",
    })
    assert resp.status_code == 422


# ── Farm retrieval ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_farm_not_found(client):
    resp = await client.get("/farms/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_farm_after_register(client):
    reg = await client.post("/farms/register", json={
        "latitude":  31.325,
        "longitude": 75.576,
        "email":     "jalandhar@example.com",
    })
    farm_id = reg.json()["farm_id"]
    resp = await client.get(f"/farms/{farm_id}")
    assert resp.status_code == 200
    assert resp.json()["farm_id"] == farm_id


# ── Admin overrides ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_override_no_token(client):
    resp = await client.post("/admin/overrides", json={
        "bottom_left_lat":     30.8,
        "bottom_left_lon":     75.6,
        "top_right_lat":       31.0,
        "top_right_lon":       75.9,
        "override_prediction": 0.85,
        "override_suggestion": "Test override",
    })
    assert resp.status_code == 422   # missing header


@pytest.mark.asyncio
async def test_create_override_wrong_token(client):
    resp = await client.post("/admin/overrides",
        json={
            "bottom_left_lat":     30.8,
            "bottom_left_lon":     75.6,
            "top_right_lat":       31.0,
            "top_right_lon":       75.9,
            "override_prediction": 0.85,
        },
        headers={"X-Admin-Token": "WRONG"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_override_valid(client):
    resp = await client.post("/admin/overrides",
        json={
            "bottom_left_lat":     30.8,
            "bottom_left_lon":     75.6,
            "top_right_lat":       31.0,
            "top_right_lon":       75.9,
            "override_prediction": 0.85,
            "override_suggestion": "Immediate field verification recommended",
        },
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "override_id" in data
    assert data["override_id"] is not None


@pytest.mark.asyncio
async def test_create_override_reversed_corners(client):
    resp = await client.post("/admin/overrides",
        json={
            "bottom_left_lat":     31.0,   # reversed: BL > TR
            "bottom_left_lon":     75.9,
            "top_right_lat":       30.8,
            "top_right_lon":       75.6,
            "override_prediction": 0.5,
        },
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_override_outside_punjab(client):
    resp = await client.post("/admin/overrides",
        json={
            "bottom_left_lat":     20.0,  # Rajasthan
            "bottom_left_lon":     72.0,
            "top_right_lat":       21.0,
            "top_right_lon":       73.0,
            "override_prediction": 0.5,
        },
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_override_invalid_prediction(client):
    resp = await client.post("/admin/overrides",
        json={
            "bottom_left_lat":     30.8,
            "bottom_left_lon":     75.6,
            "top_right_lat":       31.0,
            "top_right_lon":       75.9,
            "override_prediction": 1.5,   # > 1
        },
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_overrides(client):
    resp = await client.get("/admin/overrides",
        headers={"X-Admin-Token": ADMIN_TOKEN})
    assert resp.status_code == 200
    assert "overrides" in resp.json()


@pytest.mark.asyncio
async def test_deactivate_override(client):
    # Create
    cr = await client.post("/admin/overrides",
        json={
            "bottom_left_lat":     30.9,
            "bottom_left_lon":     75.7,
            "top_right_lat":       31.1,
            "top_right_lon":       75.9,
            "override_prediction": 0.6,
        },
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    ov_id = cr.json()["override_id"]

    # Deactivate
    resp = await client.delete(f"/admin/overrides/{ov_id}",
        headers={"X-Admin-Token": ADMIN_TOKEN})
    assert resp.status_code == 200


# ── Point risk ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_point_risk_inside_punjab(client):
    resp = await client.get("/risk/point",
        params={"lat": 31.0, "lon": 75.5, "horizon": 0})
    # Either 200 with data or 200 with null risk (if model not trained)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_point_risk_outside_punjab(client):
    resp = await client.get("/risk/point",
        params={"lat": 28.0, "lon": 77.0})
    assert resp.status_code == 422
