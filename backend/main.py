"""
CropGuard AI — FastAPI application entry point.

Endpoints
---------
Farms
  POST   /farms/register
  GET    /farms/{farm_id}
  GET    /farms/{farm_id}/risk

Districts
  GET    /districts
  GET    /districts/{district}/risk-map

Admin
  POST   /admin/overrides
  GET    /admin/overrides
  DELETE /admin/overrides/{override_id}
  POST   /admin/alerts/trigger

Utility
  GET    /health
  GET    /risk/point?lat=&lon=&horizon=

Authentication
--------------
Admin endpoints require the X-Admin-Token header matching
settings.admin_token.  This is prototype-level authentication only.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database.db import get_db, init_db
from backend.database.models import Alert, Farm, Override
from backend.services.crop_service import get_crop_info
from backend.services.risk_service import (
    get_district_risk,
    get_farm_risk,
    notify_farms_in_override_region,
    trigger_farm_alerts,
)
from backend.utils.geo import (
    get_all_districts,
    get_district,
    is_in_punjab,
    risk_level_from_probability,
)
from backend.models.risk_model import get_forecast_risk, get_point_risk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("CropGuard AI backend started. DB initialised.")
    yield
    logger.info("CropGuard AI backend shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CropGuard AI",
    description="Satellite-based pest outbreak early warning for Punjab, India.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Admin auth ────────────────────────────────────────────────────────────────

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FarmRegisterRequest(BaseModel):
    latitude:  float
    longitude: float
    email:     EmailStr

    @field_validator("latitude")
    @classmethod
    def lat_range(cls, v):
        if not (-90 <= v <= 90):
            raise ValueError("Latitude must be between -90 and 90.")
        return v

    @field_validator("longitude")
    @classmethod
    def lon_range(cls, v):
        if not (-180 <= v <= 180):
            raise ValueError("Longitude must be between -180 and 180.")
        return v


class OverrideRequest(BaseModel):
    bottom_left_lat:     float
    bottom_left_lon:     float
    top_right_lat:       float
    top_right_lon:       float
    override_prediction: float
    override_suggestion: Optional[str] = None

    @field_validator("override_prediction")
    @classmethod
    def pred_range(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError("override_prediction must be between 0 and 1.")
        return v


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "CropGuard AI"}


# ── Farm registration ─────────────────────────────────────────────────────────

@app.post("/farms/register", status_code=status.HTTP_201_CREATED)
async def register_farm(
    body: FarmRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a farm.

    Backend validates:
    1. Email format (Pydantic EmailStr)
    2. Coordinate range
    3. Inside Punjab
    4. Determines district
    5. Determines dominant crop (STATIC)
    6. Stores farm
    7. Returns farm details + current risk
    """
    # Punjab validation
    if not is_in_punjab(body.latitude, body.longitude):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "location_outside_punjab",
                "message": "This location is outside Punjab. CropGuard AI currently supports Punjab only.",
            },
        )

    district  = get_district(body.latitude, body.longitude)
    crop_info = get_crop_info(body.latitude, body.longitude)

    farm = Farm(
        latitude=body.latitude,
        longitude=body.longitude,
        email=str(body.email),
        district=district,
        crop=crop_info.get("crop"),
    )
    db.add(farm)
    await db.commit()
    await db.refresh(farm)

    # Get current risk
    risk_info = get_point_risk(body.latitude, body.longitude, 0)

    return {
        "farm_id":          farm.id,
        "latitude":         farm.latitude,
        "longitude":        farm.longitude,
        "district":         farm.district,
        "crop":             farm.crop,
        "crop_stage":       crop_info.get("crop_stage"),
        "susceptibility":   crop_info.get("susceptibility"),
        "risk_level":       risk_info.get("risk_level"),
        "risk_probability": risk_info.get("risk_probability"),
        "message":          "Farm registered successfully.",
        "data_note":        crop_info.get("note"),
    }


# ── Farm details ──────────────────────────────────────────────────────────────

@app.get("/farms/{farm_id}")
async def get_farm(farm_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Farm).where(Farm.id == farm_id))
    farm = result.scalar_one_or_none()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found.")

    risk = await get_farm_risk(farm, db, horizon_days=0)
    return risk


# ── Farm risk ─────────────────────────────────────────────────────────────────

@app.get("/farms/{farm_id}/risk")
async def get_farm_risk_endpoint(
    farm_id:  int,
    horizon:  int = Query(0, ge=0, le=7),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Farm).where(Farm.id == farm_id))
    farm = result.scalar_one_or_none()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found.")

    # All forecast horizons
    forecasts = get_forecast_risk(farm.latitude, farm.longitude)
    current   = await get_farm_risk(farm, db, horizon_days=horizon)

    return {
        **current,
        "forecasts": forecasts,
    }


# ── District endpoints ────────────────────────────────────────────────────────

@app.get("/districts")
async def list_districts():
    return {"districts": get_all_districts()}


@app.get("/districts/{district}/risk-map")
async def district_risk_map(
    district: str,
    horizon:  int = Query(0, ge=0, le=7),
    db: AsyncSession = Depends(get_db),
):
    all_districts = get_all_districts()
    # Normalise
    matched = next((d for d in all_districts if d.lower() == district.lower()), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"District '{district}' not found.")

    data = await get_district_risk(matched, db, horizon_days=horizon)
    return data


# ── Risk point query ──────────────────────────────────────────────────────────

@app.get("/risk/point")
async def point_risk(
    lat:     float = Query(..., ge=-90,  le=90),
    lon:     float = Query(..., ge=-180, le=180),
    horizon: int   = Query(0,   ge=0,   le=7),
    db: AsyncSession = Depends(get_db),
):
    if not is_in_punjab(lat, lon):
        raise HTTPException(
            status_code=422,
            detail="Location is outside Punjab.",
        )
    overrides_rows = await db.execute(select(Override).where(Override.active == True))
    overrides = [
        {
            "bottom_left_lat":     ov.bottom_left_lat,
            "bottom_left_lon":     ov.bottom_left_lon,
            "top_right_lat":       ov.top_right_lat,
            "top_right_lon":       ov.top_right_lon,
            "override_prediction": ov.override_prediction,
            "active":              ov.active,
        }
        for ov in overrides_rows.scalars().all()
    ]
    return get_point_risk(lat, lon, horizon, overrides)


# ── Admin: overrides ──────────────────────────────────────────────────────────

@app.post("/admin/overrides", dependencies=[Depends(verify_admin)], status_code=201)
async def create_override(
    body: OverrideRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create an expert geographic override.

    Validates:
    - Coordinate ranges
    - Corners inside Punjab
    - Rectangle orientation (bl < tr)
    - Prediction value 0-1
    """
    # Orientation check
    if body.bottom_left_lat >= body.top_right_lat:
        raise HTTPException(422, "bottom_left_lat must be < top_right_lat.")
    if body.bottom_left_lon >= body.top_right_lon:
        raise HTTPException(422, "bottom_left_lon must be < top_right_lon.")

    # Punjab containment — at least one corner must be in Punjab
    corners = [
        (body.bottom_left_lat, body.bottom_left_lon),
        (body.top_right_lat,   body.top_right_lon),
    ]
    if not any(is_in_punjab(lat, lon) for lat, lon in corners):
        raise HTTPException(422, "Override region does not overlap Punjab.")

    override = Override(
        bottom_left_lat=body.bottom_left_lat,
        bottom_left_lon=body.bottom_left_lon,
        top_right_lat=body.top_right_lat,
        top_right_lon=body.top_right_lon,
        override_prediction=body.override_prediction,
        override_suggestion=body.override_suggestion,
        active=True,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)

    # Notify affected farms
    notified = await notify_farms_in_override_region(override, db)

    # Determine affected grid cells
    from backend.utils.geo import bbox_to_grid_indices
    cells = bbox_to_grid_indices(
        south=body.bottom_left_lat,
        west=body.bottom_left_lon,
        north=body.top_right_lat,
        east=body.top_right_lon,
    )

    return {
        "override_id":        override.id,
        "affected_cells":     len(cells),
        "farms_notified":     notified,
        "risk_level":         risk_level_from_probability(body.override_prediction),
        "message":            "Override applied. Risk map updated.",
    }


@app.get("/admin/overrides", dependencies=[Depends(verify_admin)])
async def list_overrides(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Override))
    overrides = result.scalars().all()
    return {
        "overrides": [
            {
                "id":                  ov.id,
                "bottom_left_lat":     ov.bottom_left_lat,
                "bottom_left_lon":     ov.bottom_left_lon,
                "top_right_lat":       ov.top_right_lat,
                "top_right_lon":       ov.top_right_lon,
                "override_prediction": ov.override_prediction,
                "override_suggestion": ov.override_suggestion,
                "active":              ov.active,
                "created_at":          ov.created_at.isoformat() if ov.created_at else None,
            }
            for ov in overrides
        ]
    }


@app.delete("/admin/overrides/{override_id}", dependencies=[Depends(verify_admin)])
async def deactivate_override(override_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Override).where(Override.id == override_id))
    ov = result.scalar_one_or_none()
    if not ov:
        raise HTTPException(404, "Override not found.")
    ov.active = False
    await db.commit()
    return {"message": f"Override {override_id} deactivated."}


# ── Admin: trigger alerts ─────────────────────────────────────────────────────

@app.post("/admin/alerts/trigger", dependencies=[Depends(verify_admin)])
async def trigger_alerts(db: AsyncSession = Depends(get_db)):
    """Manually trigger the alert sweep for all registered farms."""
    sent = await trigger_farm_alerts(db)
    return {"alerts_sent": sent}
