"""
CropGuard AI — Geographic utility functions.

Provides Punjab boundary loading, coordinate validation, district
identification, and grid generation.

Punjab boundary source
----------------------
We use the GeoJSON boundary bundled in the repository
(backend/data/boundaries/punjab_boundary.geojson).

If the file is absent, the module falls back to the approximate bounding-box
polygon.  The boundary file should be obtained from a public administrative
dataset (e.g. GADM level-1, Natural Earth, or Bhuvan) and placed at the
path above.  The bounding-box fallback is explicitly documented as an
approximation.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import Point, Polygon, shape, mapping
from shapely.ops import unary_union

from backend.config import PUNJAB_BBOX, BOUNDARIES_DIR, GRID_RESOLUTION_DEG

logger = logging.getLogger(__name__)


# ── Punjab district centroids (approximate, from published sources) ───────────
# Used when a proper district shapefile is absent.
# Source: Wikipedia / Census of India district pages.
PUNJAB_DISTRICT_CENTROIDS: Dict[str, Tuple[float, float]] = {
    "Amritsar":     (31.634, 74.872),
    "Barnala":      (30.378, 75.547),
    "Bathinda":     (30.211, 74.946),
    "Faridkot":     (30.675, 74.755),
    "Fatehgarh Sahib": (30.648, 76.393),
    "Fazilka":      (30.400, 74.028),
    "Ferozepur":    (30.923, 74.615),
    "Gurdaspur":    (32.038, 75.405),
    "Hoshiarpur":   (31.534, 75.912),
    "Jalandhar":    (31.325, 75.576),
    "Kapurthala":   (31.381, 75.380),
    "Ludhiana":     (30.901, 75.857),
    "Malerkotla":   (30.529, 75.881),
    "Mansa":        (29.987, 75.397),
    "Moga":         (30.818, 75.173),
    "Mohali":       (30.704, 76.717),
    "Muktsar":      (30.473, 74.516),
    "Nawanshahr":   (31.125, 76.116),
    "Pathankot":    (32.274, 75.652),
    "Patiala":      (30.340, 76.386),
    "Rupnagar":     (30.963, 76.525),
    "Sangrur":      (30.246, 75.844),
    "Sri Muktsar Sahib": (30.473, 74.516),
    "Tarn Taran":   (31.451, 74.928),
}


@lru_cache(maxsize=1)
def load_punjab_boundary() -> Polygon:
    """
    Return a Shapely Polygon representing Punjab's boundary.

    Priority:
    1. backend/data/boundaries/punjab_boundary.geojson  (real boundary)
    2. Approximate bounding-box polygon                 (fallback)
    """
    boundary_file = BOUNDARIES_DIR / "punjab_boundary.geojson"

    if boundary_file.exists():
        try:
            with open(boundary_file, "r") as fh:
                gj = json.load(fh)
            geoms = []
            features = gj.get("features", [gj])
            for feat in features:
                geom = feat.get("geometry") if "geometry" in feat else feat
                if geom:
                    geoms.append(shape(geom))
            if geoms:
                boundary = unary_union(geoms)
                logger.info("Punjab boundary loaded from GeoJSON (%d feature(s)).", len(geoms))
                return boundary
        except Exception as exc:
            logger.warning("Failed to parse punjab_boundary.geojson: %s. Using bbox fallback.", exc)

    # Fallback: approximate bounding box
    logger.warning(
        "Using approximate bounding-box polygon for Punjab. "
        "Place a real boundary at backend/data/boundaries/punjab_boundary.geojson "
        "for production use."
    )
    bb = PUNJAB_BBOX
    return Polygon([
        (bb["west"], bb["south"]),
        (bb["east"], bb["south"]),
        (bb["east"], bb["north"]),
        (bb["west"], bb["north"]),
    ])


@lru_cache(maxsize=1)
def load_district_boundaries() -> Dict[str, Polygon]:
    """
    Return a dict mapping district name → Shapely Polygon.

    Priority:
    1. backend/data/boundaries/punjab_districts.geojson
    2. Voronoi/centroid-based approximate districts (fallback)
    """
    district_file = BOUNDARIES_DIR / "punjab_districts.geojson"

    if district_file.exists():
        try:
            with open(district_file, "r") as fh:
                gj = json.load(fh)
            districts: Dict[str, Polygon] = {}
            for feat in gj.get("features", []):
                name = (
                    feat.get("properties", {}).get("district")
                    or feat.get("properties", {}).get("NAME_2")
                    or feat.get("properties", {}).get("name")
                    or "Unknown"
                )
                geom = shape(feat["geometry"])
                districts[name] = geom
            if districts:
                logger.info("District boundaries loaded (%d districts).", len(districts))
                return districts
        except Exception as exc:
            logger.warning("Failed to parse punjab_districts.geojson: %s. Using centroid fallback.", exc)

    # Fallback: approximate using nearest centroid
    logger.warning("Using centroid-based district approximation.")
    return {}   # empty → callers fall back to nearest-centroid logic


def is_in_punjab(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) falls inside Punjab's boundary."""
    boundary = load_punjab_boundary()
    return boundary.contains(Point(lon, lat))


def get_district(lat: float, lon: float) -> Optional[str]:
    """
    Return the district name for (lat, lon).

    Uses district GeoJSON if available; otherwise uses nearest-centroid
    approximation.
    """
    districts = load_district_boundaries()

    if districts:
        pt = Point(lon, lat)
        for name, poly in districts.items():
            if poly.contains(pt):
                return name

    # Nearest-centroid fallback
    if not PUNJAB_DISTRICT_CENTROIDS:
        return None

    min_dist = float("inf")
    nearest = None
    for district, (d_lat, d_lon) in PUNJAB_DISTRICT_CENTROIDS.items():
        d = (lat - d_lat) ** 2 + (lon - d_lon) ** 2
        if d < min_dist:
            min_dist = d
            nearest = district
    return nearest


def get_all_districts() -> List[str]:
    """Return sorted list of all Punjab districts."""
    districts = load_district_boundaries()
    if districts:
        return sorted(districts.keys())
    return sorted(PUNJAB_DISTRICT_CENTROIDS.keys())


# ── Grid generation ───────────────────────────────────────────────────────────

def generate_punjab_grid(resolution: float = GRID_RESOLUTION_DEG) -> Dict:
    """
    Generate a regular lat/lon grid clipped to Punjab's boundary.

    Returns
    -------
    dict with keys:
        lats      : 1-D array of cell-centre latitudes
        lons      : 1-D array of cell-centre longitudes
        lat_grid  : 2-D array (H × W) of latitudes
        lon_grid  : 2-D array (H × W) of longitudes
        mask      : 2-D boolean array; True where cell is inside Punjab
        height    : int
        width     : int
        resolution: float
    """
    bb = PUNJAB_BBOX
    boundary = load_punjab_boundary()

    lats = np.arange(bb["south"] + resolution / 2, bb["north"], resolution)
    lons = np.arange(bb["west"] + resolution / 2, bb["east"], resolution)

    lon_grid, lat_grid = np.meshgrid(lons, lats)  # shape (H, W)
    H, W = lat_grid.shape

    mask = np.zeros((H, W), dtype=bool)
    for i in range(H):
        for j in range(W):
            mask[i, j] = boundary.contains(Point(lon_grid[i, j], lat_grid[i, j]))

    logger.info(
        "Punjab grid generated: %d × %d (%d cells inside boundary, %.1f %% coverage).",
        H, W,
        mask.sum(),
        100.0 * mask.sum() / (H * W),
    )

    return {
        "lats": lats,
        "lons": lons,
        "lat_grid": lat_grid,
        "lon_grid": lon_grid,
        "mask": mask,
        "height": H,
        "width": W,
        "resolution": resolution,
    }


@lru_cache(maxsize=1)
def get_cached_grid() -> Dict:
    """Cached grid (computed once per process)."""
    return generate_punjab_grid()


def latlon_to_grid_index(lat: float, lon: float) -> Optional[Tuple[int, int]]:
    """
    Convert (lat, lon) to (row, col) indices in the Punjab grid.

    Returns None if the point falls outside the grid extent.
    """
    grid = get_cached_grid()
    res = grid["resolution"]
    lats = grid["lats"]
    lons = grid["lons"]

    row = int(round((lat - lats[0]) / res))
    col = int(round((lon - lons[0]) / res))

    if 0 <= row < grid["height"] and 0 <= col < grid["width"]:
        return (row, col)
    return None


def bbox_to_grid_indices(
    south: float, west: float, north: float, east: float
) -> List[Tuple[int, int]]:
    """
    Return all grid (row, col) pairs whose cell centres fall within
    the given bounding box AND inside the Punjab boundary.
    """
    grid = get_cached_grid()
    lats = grid["lats"]
    lons = grid["lons"]
    mask = grid["mask"]

    # Fast exit: bbox entirely outside grid extent
    if north < lats[0] or south > lats[-1] or east < lons[0] or west > lons[-1]:
        return []

    row_min = max(0, int(np.searchsorted(lats, south)))
    row_max = min(grid["height"] - 1, int(np.searchsorted(lats, north)))
    col_min = max(0, int(np.searchsorted(lons, west)))
    col_max = min(grid["width"] - 1, int(np.searchsorted(lons, east)))

    indices = []
    for r in range(row_min, row_max + 1):
        for c in range(col_min, col_max + 1):
            # Only include cells whose centre is actually within the bbox
            if lats[r] < south or lats[r] > north:
                continue
            if lons[c] < west or lons[c] > east:
                continue
            if mask[r, c]:
                indices.append((r, c))
    return indices


def risk_level_from_probability(prob: float) -> str:
    """Convert a risk probability (0-1) to a category string."""
    from backend.config import RISK_THRESHOLDS
    for level, (lo, hi) in RISK_THRESHOLDS.items():
        if lo <= prob < hi:
            return level
    return "LOW"
