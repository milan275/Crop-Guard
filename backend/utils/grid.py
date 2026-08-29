"""
CropGuard AI — Grid I/O helpers.

Provides serialisation / deserialisation of the spatiotemporal feature
tensor and risk output maps, including GeoJSON and GeoTIFF export.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from backend.config import OUTPUTS_DIR, GRID_RESOLUTION_DEG
from backend.utils.geo import get_cached_grid, risk_level_from_probability

logger = logging.getLogger(__name__)


def risk_map_to_geojson(
    risk_map: np.ndarray,
    timestamp: str,
    forecast_horizon: str = "current",
) -> Dict[str, Any]:
    """
    Convert a (H × W) risk probability array to GeoJSON FeatureCollection.

    Each cell becomes a GeoJSON Feature (polygon) with:
        risk_probability, risk_level, lat, lon, forecast_horizon, timestamp

    Cells outside Punjab (mask=False) are omitted.
    """
    grid = get_cached_grid()
    lat_grid = grid["lat_grid"]
    lon_grid = grid["lon_grid"]
    mask = grid["mask"]
    res = grid["resolution"]
    half = res / 2.0

    features = []
    H, W = risk_map.shape
    for i in range(H):
        for j in range(W):
            if not mask[i, j]:
                continue
            prob = float(risk_map[i, j])
            lat = float(lat_grid[i, j])
            lon = float(lon_grid[i, j])
            level = risk_level_from_probability(prob)

            cell_poly = {
                "type": "Polygon",
                "coordinates": [[
                    [lon - half, lat - half],
                    [lon + half, lat - half],
                    [lon + half, lat + half],
                    [lon - half, lat + half],
                    [lon - half, lat - half],
                ]],
            }
            features.append({
                "type": "Feature",
                "geometry": cell_poly,
                "properties": {
                    "lat": lat,
                    "lon": lon,
                    "row": i,
                    "col": j,
                    "risk_probability": round(prob, 4),
                    "risk_level": level,
                    "forecast_horizon": forecast_horizon,
                    "timestamp": timestamp,
                },
            })

    return {"type": "FeatureCollection", "features": features}


def save_risk_map(
    risk_map: np.ndarray,
    timestamp: str,
    forecast_horizon: str = "current",
    filename: Optional[str] = None,
) -> Path:
    """Save a risk map as GeoJSON to the outputs directory."""
    if filename is None:
        safe_ts = timestamp.replace(":", "-").replace(" ", "_")
        filename = f"risk_map_{safe_ts}_{forecast_horizon}.geojson"

    out_path = OUTPUTS_DIR / filename
    gj = risk_map_to_geojson(risk_map, timestamp, forecast_horizon)

    with open(out_path, "w") as fh:
        json.dump(gj, fh, separators=(",", ":"))

    logger.info("Risk map saved → %s (%d features).", out_path, len(gj["features"]))
    return out_path


def load_risk_map_geojson(path: Path) -> Optional[Dict]:
    """Load a previously saved risk-map GeoJSON."""
    if not path.exists():
        return None
    with open(path, "r") as fh:
        return json.load(fh)


def district_risk_summary(
    risk_map: np.ndarray,
    district: str,
) -> Dict[str, Any]:
    """
    Compute summary statistics for a district from the risk map.

    Returns mean, max, and cell-level list for heatmap rendering.
    """
    from backend.utils.geo import load_district_boundaries, PUNJAB_DISTRICT_CENTROIDS, get_cached_grid
    from shapely.geometry import Point

    grid = get_cached_grid()
    lat_grid = grid["lat_grid"]
    lon_grid = grid["lon_grid"]
    mask = grid["mask"]

    # Try to find district polygon
    district_boundaries = load_district_boundaries()
    district_poly = district_boundaries.get(district)

    cells: List[Dict] = []
    H, W = risk_map.shape
    for i in range(H):
        for j in range(W):
            if not mask[i, j]:
                continue
            lat = float(lat_grid[i, j])
            lon = float(lon_grid[i, j])

            if district_poly is not None:
                if not district_poly.contains(Point(lon, lat)):
                    continue
            else:
                # Fallback: use nearest centroid to decide district
                from backend.utils.geo import get_district
                if get_district(lat, lon) != district:
                    continue

            prob = float(risk_map[i, j])
            cells.append({
                "lat": lat,
                "lon": lon,
                "row": i,
                "col": j,
                "risk_probability": round(prob, 4),
                "risk_level": risk_level_from_probability(prob),
            })

    if not cells:
        return {"district": district, "cells": [], "mean_risk": 0.0, "max_risk": 0.0}

    probs = [c["risk_probability"] for c in cells]
    return {
        "district": district,
        "cells": cells,
        "mean_risk": round(float(np.mean(probs)), 4),
        "max_risk": round(float(np.max(probs)), 4),
        "cell_count": len(cells),
    }


def try_export_geotiff(risk_map: np.ndarray, out_path: Path) -> bool:
    """
    Export risk map as GeoTIFF if rasterio is available.

    Returns True on success, False otherwise.
    """
    try:
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.crs import CRS
        from backend.config import PUNJAB_BBOX

        H, W = risk_map.shape
        transform = from_bounds(
            west=PUNJAB_BBOX["west"],
            south=PUNJAB_BBOX["south"],
            east=PUNJAB_BBOX["east"],
            north=PUNJAB_BBOX["north"],
            width=W,
            height=H,
        )
        with rasterio.open(
            out_path,
            "w",
            driver="GTiff",
            height=H,
            width=W,
            count=1,
            dtype=np.float32,
            crs=CRS.from_epsg(4326),
            transform=transform,
        ) as dst:
            dst.write(risk_map.astype(np.float32), 1)

        logger.info("GeoTIFF exported → %s", out_path)
        return True
    except Exception as exc:
        logger.warning("GeoTIFF export skipped: %s", exc)
        return False
