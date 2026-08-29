"""
CropGuard AI — Weather ingestion service.

Data source
-----------
Required / ideal source : IMD (India Meteorological Department)
Actual prototype source  : Open-Meteo (https://open-meteo.com)
Reason                   : IMD does not provide a free, programmatic,
                           machine-readable API suitable for automated
                           historical data retrieval.  The Open-Meteo
                           Historical Weather API is backed by ERA5
                           reanalysis data (ECMWF), which is itself a
                           widely used meteorological reference dataset.
                           Open-Meteo forecasts use ECMWF IFS / GFS.

Classification
--------------
Weather data             → REAL  (real observations via Open-Meteo/ERA5)

Spatial resolution
------------------
Open-Meteo returns point-level data for a given (lat, lon).
We query one representative point per grid cell.  For a hackathon
prototype we use a coarser sub-sampling: one weather point per
~0.5° × 0.5° tile covering Punjab, then bilinearly interpolate
to the full grid.  This is explicitly documented — we do not imply
high-resolution weather measurements.

Caching
-------
Weather data is cached as .json files under backend/data/raw/weather/
keyed by (lat, lon, start_date, end_date).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.config import (
    PUNJAB_BBOX,
    RAW_DIR,
    WEATHER_FORECAST_DAYS,
    WEATHER_LOOKBACK_DAYS,
    WEATHER_VARIABLES,
    GRID_RESOLUTION_DEG,
    SENTINEL2_TEMPORAL_STEPS,
)
from backend.utils.geo import get_cached_grid

logger = logging.getLogger(__name__)

WEATHER_CACHE_DIR = RAW_DIR / "weather"
WEATHER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Sub-sample resolution for weather queries (coarser than satellite grid)
WEATHER_SAMPLE_RESOLUTION = 0.5  # degrees

# Open-Meteo endpoints
OPEN_METEO_HISTORICAL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST   = "https://api.open-meteo.com/v1/forecast"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _weather_cache_key(lat: float, lon: float, start: str, end: str, kind: str) -> Path:
    key = f"{lat:.3f}_{lon:.3f}_{start}_{end}_{kind}"
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return WEATHER_CACHE_DIR / f"{h}.json"


def _load_cache(path: Path) -> Optional[Dict]:
    if path.exists():
        with open(path) as fh:
            return json.load(fh)
    return None


def _save_cache(path: Path, data: Dict) -> None:
    with open(path, "w") as fh:
        json.dump(data, fh)


# ── Open-Meteo fetchers ───────────────────────────────────────────────────────

def _fetch_historical(lat: float, lon: float, start: str, end: str) -> Optional[Dict]:
    """Fetch daily historical weather from Open-Meteo archive (ERA5-backed)."""
    cache_path = _weather_cache_key(lat, lon, start, end, "hist")
    cached = _load_cache(cache_path)
    if cached:
        return cached

    try:
        import httpx
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "daily": ",".join(WEATHER_VARIABLES),
            "timezone": "Asia/Kolkata",
        }
        resp = httpx.get(OPEN_METEO_HISTORICAL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        _save_cache(cache_path, data)
        return data
    except Exception as exc:
        logger.warning("Open-Meteo historical fetch failed (%s, %s): %s", lat, lon, exc)
        return None


def _fetch_forecast(lat: float, lon: float, days: int = WEATHER_FORECAST_DAYS) -> Optional[Dict]:
    """Fetch weather forecast from Open-Meteo."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cache_path = _weather_cache_key(lat, lon, today, f"forecast{days}", "fcast")
    cached = _load_cache(cache_path)
    if cached:
        return cached

    try:
        import httpx
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(WEATHER_VARIABLES),
            "forecast_days": days,
            "timezone": "Asia/Kolkata",
        }
        resp = httpx.get(OPEN_METEO_FORECAST, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        _save_cache(cache_path, data)
        return data
    except Exception as exc:
        logger.warning("Open-Meteo forecast fetch failed (%s, %s): %s", lat, lon, exc)
        return None


# ── Spatial interpolation ─────────────────────────────────────────────────────

def _sample_grid_points() -> List[Tuple[float, float]]:
    """
    Return a list of (lat, lon) sample points covering Punjab at
    WEATHER_SAMPLE_RESOLUTION spacing.  These are the points for
    which we actually query Open-Meteo.
    """
    bb = PUNJAB_BBOX
    lats = np.arange(
        bb["south"] + WEATHER_SAMPLE_RESOLUTION / 2,
        bb["north"],
        WEATHER_SAMPLE_RESOLUTION,
    )
    lons = np.arange(
        bb["west"] + WEATHER_SAMPLE_RESOLUTION / 2,
        bb["east"],
        WEATHER_SAMPLE_RESOLUTION,
    )
    points = []
    for lat in lats:
        for lon in lons:
            points.append((float(lat), float(lon)))
    return points


def _bilinear_interpolate(
    sample_lats: np.ndarray,
    sample_lons: np.ndarray,
    sample_values: np.ndarray,  # shape (n_samples,)
    target_lat_grid: np.ndarray,  # shape (H, W)
    target_lon_grid: np.ndarray,  # shape (H, W)
) -> np.ndarray:
    """
    Bilinearly interpolate sparse sample values to the full grid.

    Falls back to nearest-neighbour when grid is too coarse for bilinear.
    """
    from scipy.interpolate import griddata

    points = np.column_stack([sample_lats, sample_lons])
    interpolated = griddata(
        points,
        sample_values,
        (target_lat_grid, target_lon_grid),
        method="linear",
    )
    # Fill NaN (extrapolation edges) with nearest
    nan_mask = np.isnan(interpolated)
    if nan_mask.any():
        nearest = griddata(
            points,
            sample_values,
            (target_lat_grid[nan_mask], target_lon_grid[nan_mask]),
            method="nearest",
        )
        interpolated[nan_mask] = nearest

    return interpolated.astype(np.float32)


# ── Main entry points ─────────────────────────────────────────────────────────

def ingest_weather_historical(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    n_steps: int = SENTINEL2_TEMPORAL_STEPS,
) -> Dict[str, Any]:
    """
    Fetch historical daily weather for all sample points covering Punjab.
    Interpolate each variable to the full satellite grid.

    Returns dict:
        {variable_name: (n_steps, H, W) float32 array, ...}
        dates: list of ISO date strings (length n_steps)
    """
    if end_date is None:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (
            datetime.utcnow() - timedelta(days=WEATHER_LOOKBACK_DAYS)
        ).strftime("%Y-%m-%d")

    grid = get_cached_grid()
    H, W = grid["height"], grid["width"]
    lat_grid = grid["lat_grid"]
    lon_grid = grid["lon_grid"]

    sample_points = _sample_grid_points()
    n_samples = len(sample_points)

    # Collect raw time series per sample point
    # result_map[variable][sample_idx] = list of daily values
    raw: Dict[str, List[List[float]]] = {v: [] for v in WEATHER_VARIABLES}
    all_dates: Optional[List[str]] = None

    for lat, lon in sample_points:
        data = _fetch_historical(lat, lon, start_date, end_date)
        if data and "daily" in data:
            dates = data["daily"].get("time", [])
            if all_dates is None:
                all_dates = dates
            for var in WEATHER_VARIABLES:
                vals = data["daily"].get(var, [None] * len(dates))
                raw[var].append([v if v is not None else np.nan for v in vals])
        else:
            for var in WEATHER_VARIABLES:
                raw[var].append([])

    if all_dates is None or len(all_dates) == 0:
        logger.warning("No weather data retrieved. Returning NaN arrays.")
        result: Dict[str, Any] = {}
        for var in WEATHER_VARIABLES:
            result[var] = np.full((n_steps, H, W), np.nan, dtype=np.float32)
        result["dates"] = ["missing"] * n_steps
        return result

    # Trim to last n_steps days
    total_days = len(all_dates)
    step_indices = _select_step_indices(total_days, n_steps)
    selected_dates = [all_dates[i] for i in step_indices]

    sample_lats = np.array([p[0] for p in sample_points])
    sample_lons = np.array([p[1] for p in sample_points])

    result = {}
    for var in WEATHER_VARIABLES:
        stack = np.full((n_steps, H, W), np.nan, dtype=np.float32)
        for t_idx, day_idx in enumerate(step_indices):
            sample_vals = []
            valid_lats, valid_lons = [], []
            for s_idx in range(n_samples):
                series = raw[var][s_idx]
                if day_idx < len(series) and not np.isnan(series[day_idx]):
                    sample_vals.append(series[day_idx])
                    valid_lats.append(sample_points[s_idx][0])
                    valid_lons.append(sample_points[s_idx][1])

            if len(sample_vals) >= 3:
                stack[t_idx] = _bilinear_interpolate(
                    np.array(valid_lats),
                    np.array(valid_lons),
                    np.array(sample_vals),
                    lat_grid,
                    lon_grid,
                )
        result[var] = stack

    result["dates"] = selected_dates
    logger.info(
        "Weather ingestion complete: %d variables × %d steps × (%d × %d) grid.",
        len(WEATHER_VARIABLES), n_steps, H, W,
    )
    return result


def ingest_weather_forecast(days: int = WEATHER_FORECAST_DAYS) -> Dict[str, Any]:
    """
    Fetch weather forecast for all Punjab sample points and
    interpolate to the grid.

    Returns same structure as ingest_weather_historical but for
    forecast days.
    """
    grid = get_cached_grid()
    H, W = grid["height"], grid["width"]
    lat_grid = grid["lat_grid"]
    lon_grid = grid["lon_grid"]

    sample_points = _sample_grid_points()
    n_samples = len(sample_points)

    raw: Dict[str, List[List[float]]] = {v: [] for v in WEATHER_VARIABLES}
    all_dates: Optional[List[str]] = None

    for lat, lon in sample_points:
        data = _fetch_forecast(lat, lon, days)
        if data and "daily" in data:
            dates = data["daily"].get("time", [])
            if all_dates is None:
                all_dates = dates
            for var in WEATHER_VARIABLES:
                vals = data["daily"].get(var, [None] * len(dates))
                raw[var].append([v if v is not None else np.nan for v in vals])
        else:
            for var in WEATHER_VARIABLES:
                raw[var].append([])

    if all_dates is None:
        logger.warning("No forecast data. Returning NaN arrays.")
        result = {v: np.full((days, H, W), np.nan, dtype=np.float32) for v in WEATHER_VARIABLES}
        result["dates"] = ["missing"] * days
        return result

    sample_lats = np.array([p[0] for p in sample_points])
    sample_lons = np.array([p[1] for p in sample_points])

    result = {}
    for var in WEATHER_VARIABLES:
        stack = np.full((len(all_dates), H, W), np.nan, dtype=np.float32)
        for t_idx in range(len(all_dates)):
            sample_vals, valid_lats, valid_lons = [], [], []
            for s_idx in range(n_samples):
                series = raw[var][s_idx]
                if t_idx < len(series) and not np.isnan(series[t_idx]):
                    sample_vals.append(series[t_idx])
                    valid_lats.append(sample_points[s_idx][0])
                    valid_lons.append(sample_points[s_idx][1])
            if len(sample_vals) >= 3:
                stack[t_idx] = _bilinear_interpolate(
                    np.array(valid_lats),
                    np.array(valid_lons),
                    np.array(sample_vals),
                    lat_grid,
                    lon_grid,
                )
        result[var] = stack

    result["dates"] = all_dates
    return result


def get_point_weather(lat: float, lon: float, days_back: int = 30) -> Dict[str, Any]:
    """
    Return recent weather for a single point.
    Used by the farm details API.
    """
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    data = _fetch_historical(lat, lon, start_date, end_date)
    if data and "daily" in data:
        return data["daily"]
    return {}


# ── Helper ────────────────────────────────────────────────────────────────────

def _select_step_indices(total: int, n_steps: int) -> List[int]:
    """
    Choose n_steps evenly-spaced indices from [0, total-1],
    always including the last index.
    """
    if total <= n_steps:
        return list(range(total))
    step = total / n_steps
    indices = [int(i * step) for i in range(n_steps - 1)]
    indices.append(total - 1)
    return indices
