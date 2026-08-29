"""
CropGuard AI — Crop identification and calendar service.

Crop data sources investigated
-------------------------------
1. Punjab Remote Sensing Centre (PRSC) crop maps  — not programmatically
   accessible without institutional agreement.
2. ICAR-NAAS crop distribution maps               — available as reports,
   not machine-readable rasters.
3. FAO GAEZ crop suitability rasters              — global, coarse (5 arcmin).
4. IARI Crop mapping                              — regional reports, not API.
5. ESA World Cover 2021                           — land cover (not crop type).
6. Kharif/Rabi season district-level statistics   — tabular, not spatially
   resolved at field level.

Result
------
No freely accessible, field-level crop-type raster for Punjab could be
obtained programmatically.  We implement a two-level fallback:

  Level 1 — District-level crop fraction table (STATIC, sourced from
             Punjab Statistical Abstract / PAU publications).
             Provides probability weights for each crop per district.

  Level 2 — Season-based rule:
             Rabi season  (Oct–Mar) → Wheat dominant
             Kharif season (Jun–Sep) → Paddy or Cotton depending on district

Both levels are EXPLICITLY LABELLED as STATIC/SYNTHETIC.

Crop calendar data is STATIC configuration derived from Punjab Agricultural
University (PAU) published calendars.

Classification
--------------
Crop data         → STATIC (derived from published district statistics)
Crop calendar     → STATIC (from PAU publications)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.config import CROP_CALENDAR, SUPPORTED_CROPS, GRID_RESOLUTION_DEG
from backend.utils.geo import get_cached_grid, get_district

logger = logging.getLogger(__name__)


# ── District-level crop fraction table ───────────────────────────────────────
# Source: Punjab Statistical Abstract 2022–23, PAU crop area statistics.
# Values are approximate fractions (wheat, paddy, cotton) per district.
# Districts with significant cotton: Bathinda, Mansa, Muktsar, Fazilka, Ferozepur.
# Remaining districts: primarily wheat/paddy rotation.

DISTRICT_CROP_FRACTIONS: Dict[str, Dict[str, float]] = {
    "Amritsar":          {"wheat": 0.55, "paddy": 0.40, "cotton": 0.05},
    "Barnala":           {"wheat": 0.50, "paddy": 0.30, "cotton": 0.20},
    "Bathinda":          {"wheat": 0.40, "paddy": 0.15, "cotton": 0.45},
    "Faridkot":          {"wheat": 0.45, "paddy": 0.25, "cotton": 0.30},
    "Fatehgarh Sahib":   {"wheat": 0.60, "paddy": 0.38, "cotton": 0.02},
    "Fazilka":           {"wheat": 0.35, "paddy": 0.10, "cotton": 0.55},
    "Ferozepur":         {"wheat": 0.40, "paddy": 0.20, "cotton": 0.40},
    "Gurdaspur":         {"wheat": 0.55, "paddy": 0.42, "cotton": 0.03},
    "Hoshiarpur":        {"wheat": 0.60, "paddy": 0.37, "cotton": 0.03},
    "Jalandhar":         {"wheat": 0.58, "paddy": 0.38, "cotton": 0.04},
    "Kapurthala":        {"wheat": 0.55, "paddy": 0.42, "cotton": 0.03},
    "Ludhiana":          {"wheat": 0.58, "paddy": 0.38, "cotton": 0.04},
    "Malerkotla":        {"wheat": 0.50, "paddy": 0.28, "cotton": 0.22},
    "Mansa":             {"wheat": 0.38, "paddy": 0.12, "cotton": 0.50},
    "Moga":              {"wheat": 0.50, "paddy": 0.30, "cotton": 0.20},
    "Mohali":            {"wheat": 0.62, "paddy": 0.35, "cotton": 0.03},
    "Muktsar":           {"wheat": 0.38, "paddy": 0.12, "cotton": 0.50},
    "Nawanshahr":        {"wheat": 0.60, "paddy": 0.37, "cotton": 0.03},
    "Pathankot":         {"wheat": 0.55, "paddy": 0.42, "cotton": 0.03},
    "Patiala":           {"wheat": 0.58, "paddy": 0.38, "cotton": 0.04},
    "Rupnagar":          {"wheat": 0.58, "paddy": 0.39, "cotton": 0.03},
    "Sangrur":           {"wheat": 0.50, "paddy": 0.28, "cotton": 0.22},
    "Sri Muktsar Sahib": {"wheat": 0.38, "paddy": 0.12, "cotton": 0.50},
    "Tarn Taran":        {"wheat": 0.55, "paddy": 0.40, "cotton": 0.05},
}

DEFAULT_CROP_FRACTIONS: Dict[str, float] = {
    "wheat": 0.55, "paddy": 0.35, "cotton": 0.10
}


# ── Crop identification ───────────────────────────────────────────────────────

def get_dominant_crop(lat: float, lon: float, query_date: Optional[date] = None) -> str:
    """
    Return the most likely crop at (lat, lon) for query_date.

    Method:
    1. Get district.
    2. Get district crop fractions.
    3. Apply seasonal weighting: during Kharif (Jun–Oct) up-weight
       paddy/cotton; during Rabi (Nov–Apr) up-weight wheat.
    4. Return highest-weighted crop.

    DATA CLASSIFICATION: STATIC — not real field observations.
    """
    district = get_district(lat, lon)
    fractions = DISTRICT_CROP_FRACTIONS.get(district, DEFAULT_CROP_FRACTIONS).copy()

    if query_date is None:
        query_date = date.today()

    month = query_date.month

    # Seasonal weighting
    if 6 <= month <= 10:  # Kharif
        fractions["wheat"] *= 0.3
        fractions["paddy"] *= 1.6
        fractions["cotton"] *= 1.4
    else:                 # Rabi
        fractions["wheat"] *= 1.6
        fractions["paddy"] *= 0.4
        fractions["cotton"] *= 0.5

    return max(fractions, key=fractions.__getitem__)


def get_crop_grid(query_date: Optional[date] = None) -> np.ndarray:
    """
    Return (H × W) integer array mapping each grid cell to a crop index.

    Crop index:
        0 = wheat
        1 = paddy
        2 = cotton

    DATA CLASSIFICATION: STATIC
    """
    crop_to_idx = {"wheat": 0, "paddy": 1, "cotton": 2}
    grid = get_cached_grid()
    H, W = grid["height"], grid["width"]
    lat_grid = grid["lat_grid"]
    lon_grid = grid["lon_grid"]
    mask = grid["mask"]

    crop_grid = np.zeros((H, W), dtype=np.int8)
    for i in range(H):
        for j in range(W):
            if mask[i, j]:
                crop = get_dominant_crop(
                    float(lat_grid[i, j]),
                    float(lon_grid[i, j]),
                    query_date,
                )
                crop_grid[i, j] = crop_to_idx.get(crop, 0)
    return crop_grid


# ── Crop calendar & growth stage ─────────────────────────────────────────────

def get_crop_stage(crop: str, query_date: Optional[date] = None) -> str:
    """
    Return the growth stage for the given crop on query_date.

    Returns one of: sowing, vegetative, reproductive, maturity, off_season.

    DATA CLASSIFICATION: STATIC — from PAU crop calendar.
    """
    if query_date is None:
        query_date = date.today()

    calendar = CROP_CALENDAR.get(crop.lower())
    if not calendar:
        return "off_season"

    month, day = query_date.month, query_date.day

    def in_period(m1, d1, m2, d2):
        """True if (month, day) is within the stage window."""
        start = (m1, d1)
        end = (m2, d2)
        current = (month, day)
        if start <= end:
            return start <= current <= end
        else:  # wraps year (e.g. Nov–Jan)
            return current >= start or current <= end

    for stage, (m1, d1, m2, d2) in calendar.items():
        if in_period(m1, d1, m2, d2):
            return stage

    return "off_season"


def get_stage_susceptibility(crop: str, stage: str) -> float:
    """
    Return a pest-susceptibility weight (0–1) for the crop/stage combination.

    These weights reflect known agronomic vulnerability windows and are
    used as a feature in the synthetic outbreak generator.

    DATA CLASSIFICATION: STATIC — expert domain knowledge.
    """
    susceptibility_table: Dict[Tuple[str, str], float] = {
        ("wheat", "sowing"):       0.3,
        ("wheat", "vegetative"):   0.5,
        ("wheat", "reproductive"): 0.9,  # yellow rust, aphids peak
        ("wheat", "maturity"):     0.4,
        ("paddy", "sowing"):       0.4,
        ("paddy", "vegetative"):   0.7,  # BPH, stem borer
        ("paddy", "reproductive"): 0.8,
        ("paddy", "maturity"):     0.3,
        ("cotton", "sowing"):      0.3,
        ("cotton", "vegetative"):  0.6,
        ("cotton", "reproductive"):0.9,  # bollworm, whitefly
        ("cotton", "maturity"):    0.5,
    }
    return susceptibility_table.get((crop.lower(), stage.lower()), 0.2)


def get_crop_stage_grid(query_date: Optional[date] = None) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return:
        stage_grid         : (H × W) int8 — stage index (0=sowing…3=maturity, 4=off_season)
        susceptibility_grid: (H × W) float32 — susceptibility weight

    DATA CLASSIFICATION: STATIC
    """
    stage_to_idx = {"sowing": 0, "vegetative": 1, "reproductive": 2, "maturity": 3, "off_season": 4}
    crop_to_str = {0: "wheat", 1: "paddy", 2: "cotton"}

    crop_grid = get_crop_grid(query_date)
    grid = get_cached_grid()
    H, W = grid["height"], grid["width"]
    mask = grid["mask"]

    stage_grid = np.full((H, W), 4, dtype=np.int8)
    susc_grid = np.zeros((H, W), dtype=np.float32)

    for i in range(H):
        for j in range(W):
            if mask[i, j]:
                crop_str = crop_to_str.get(int(crop_grid[i, j]), "wheat")
                stage = get_crop_stage(crop_str, query_date)
                stage_grid[i, j] = stage_to_idx.get(stage, 4)
                susc_grid[i, j] = get_stage_susceptibility(crop_str, stage)

    return stage_grid, susc_grid


def get_crop_info(lat: float, lon: float, query_date: Optional[date] = None) -> Dict:
    """
    Return crop information for a specific location.
    Used by the farm registration and details APIs.
    """
    if query_date is None:
        query_date = date.today()

    district = get_district(lat, lon)
    crop = get_dominant_crop(lat, lon, query_date)
    stage = get_crop_stage(crop, query_date)
    susceptibility = get_stage_susceptibility(crop, stage)

    return {
        "crop": crop,
        "district": district,
        "crop_stage": stage,
        "susceptibility": susceptibility,
        "data_classification": "STATIC",
        "note": "Crop type is estimated from district-level statistics, not real field observation.",
    }
