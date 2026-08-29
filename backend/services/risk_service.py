"""
CropGuard AI — Risk service.

Bridges the risk model with the database-persisted overrides and
the farm alert system.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Override, Farm
from backend.models.risk_model import (
    get_point_risk,
    get_district_risk_map,
    get_forecast_risk,
    get_risk_map,
    apply_overrides,
)
from backend.services.crop_service import get_crop_info, get_crop_stage
from backend.services.email_service import check_and_send_alert
from backend.utils.geo import (
    risk_level_from_probability,
    get_district,
    bbox_to_grid_indices,
)
from backend.config import ALERT_RISK_THRESHOLD

logger = logging.getLogger(__name__)


async def _load_active_overrides(db: AsyncSession) -> List[Dict]:
    """Load all active overrides from the database."""
    result = await db.execute(select(Override).where(Override.active == True))
    rows = result.scalars().all()
    return [
        {
            "id":                  ov.id,
            "bottom_left_lat":     ov.bottom_left_lat,
            "bottom_left_lon":     ov.bottom_left_lon,
            "top_right_lat":       ov.top_right_lat,
            "top_right_lon":       ov.top_right_lon,
            "override_prediction": ov.override_prediction,
            "override_suggestion": ov.override_suggestion,
            "active":              ov.active,
        }
        for ov in rows
    ]


async def get_farm_risk(
    farm: Farm,
    db: AsyncSession,
    horizon_days: int = 0,
) -> Dict[str, Any]:
    """
    Return full risk payload for a single farm, including overrides applied.
    """
    overrides = await _load_active_overrides(db)
    risk_info = get_point_risk(farm.latitude, farm.longitude, horizon_days, overrides)

    prob  = risk_info.get("risk_probability")
    level = risk_info.get("risk_level") or (risk_level_from_probability(prob) if prob else None)

    from datetime import date
    crop_info = get_crop_info(farm.latitude, farm.longitude)
    stage = crop_info.get("crop_stage", "unknown")

    # Recommendation based on risk level
    recommendation = _build_recommendation(level, crop_info.get("crop"), stage)

    return {
        "farm_id":           farm.id,
        "latitude":          farm.latitude,
        "longitude":         farm.longitude,
        "district":          farm.district,
        "crop":              farm.crop or crop_info.get("crop"),
        "crop_stage":        stage,
        "risk_level":        level,
        "risk_probability":  prob,
        "forecast_horizon":  f"{horizon_days}d",
        "recommendation":    recommendation,
        "satellite_timestamp": risk_info.get("timestamp"),
        "weather_timestamp":   None,   # populated by weather service
        "last_updated":        risk_info.get("timestamp"),
        "data_classification": {
            "risk":   "DERIVED REAL (satellite + weather) with SYNTHETIC training labels",
            "crop":   "STATIC",
            "stage":  "STATIC",
        },
    }


async def get_district_risk(
    district: str,
    db: AsyncSession,
    horizon_days: int = 0,
) -> Dict[str, Any]:
    """Return district risk map, overrides applied."""
    overrides = await _load_active_overrides(db)
    return get_district_risk_map(district, horizon_days, overrides)


async def trigger_farm_alerts(db: AsyncSession) -> int:
    """
    Check all registered farms against current risk; send alerts where needed.
    Returns count of alerts sent.
    """
    overrides = await _load_active_overrides(db)
    farms_result = await db.execute(select(Farm))
    farms = farms_result.scalars().all()

    sent = 0
    for farm in farms:
        risk_info = get_point_risk(farm.latitude, farm.longitude, 0, overrides)
        prob = risk_info.get("risk_probability")
        if prob is None:
            continue

        level = risk_level_from_probability(prob)
        crop_info = get_crop_info(farm.latitude, farm.longitude)
        recommendation = _build_recommendation(level, crop_info.get("crop"), crop_info.get("crop_stage"))

        success = await check_and_send_alert(
            db_session=db,
            farm_id=farm.id,
            to_email=farm.email,
            district=farm.district or "Unknown",
            risk_level=level,
            risk_probability=prob,
            lat=farm.latitude,
            lon=farm.longitude,
            recommendation=recommendation,
        )
        if success:
            sent += 1

    logger.info("Alert sweep complete. %d alert(s) sent.", sent)
    return sent


async def notify_farms_in_override_region(
    override: Override,
    db: AsyncSession,
) -> int:
    """
    After an override is applied, notify registered farms inside the
    override region if risk probability crosses the alert threshold.
    """
    indices = bbox_to_grid_indices(
        south=override.bottom_left_lat,
        west=override.bottom_left_lon,
        north=override.top_right_lat,
        east=override.top_right_lon,
    )
    if not indices:
        return 0

    # Find farms inside the override bounding box
    stmt = select(Farm).where(
        Farm.latitude  >= override.bottom_left_lat,
        Farm.latitude  <= override.top_right_lat,
        Farm.longitude >= override.bottom_left_lon,
        Farm.longitude <= override.top_right_lon,
    )
    result = await db.execute(stmt)
    farms = result.scalars().all()

    sent = 0
    for farm in farms:
        prob  = float(override.override_prediction)
        level = risk_level_from_probability(prob)
        recommendation = override.override_suggestion or _build_recommendation(level, farm.crop, None)

        success = await check_and_send_alert(
            db_session=db,
            farm_id=farm.id,
            to_email=farm.email,
            district=farm.district or "Unknown",
            risk_level=level,
            risk_probability=prob,
            lat=farm.latitude,
            lon=farm.longitude,
            recommendation=recommendation,
        )
        if success:
            sent += 1

    return sent


def _build_recommendation(
    risk_level: Optional[str],
    crop: Optional[str],
    stage: Optional[str],
) -> str:
    """Build a human-readable recommendation from risk level and crop context."""
    if risk_level in ("HIGH", "CRITICAL"):
        base = "Immediate field monitoring is strongly advised. "
        if stage == "reproductive":
            base += "The crop is in its most susceptible growth stage. "
        base += "Contact your local agricultural extension officer if any pest symptoms are observed."
    elif risk_level == "MODERATE":
        base = "Increased field monitoring is recommended. Watch for early signs of pest activity."
        if crop == "cotton":
            base += " Inspect for bollworm and whitefly."
        elif crop == "wheat":
            base += " Watch for yellow rust and aphids."
        elif crop == "paddy":
            base += " Monitor for brown plant hopper and stem borer."
    else:
        base = "Risk is currently low. Continue standard monitoring practices."

    return base
