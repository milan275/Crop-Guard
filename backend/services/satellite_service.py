"""
CropGuard AI — Microsoft Planetary Computer / Sentinel-2 ingestion service.

Data source
-----------
Real data:  Microsoft Planetary Computer STAC API
Collection: sentinel-2-l2a
Bands used: B04 (Red), B08 (NIR) for NDVI
            B02 (Blue), B03 (Green), B11 (SWIR1) for EVI (optional)

Classification
--------------
Sentinel-2 scenes       → REAL
NDVI computed from bands → DERIVED REAL
EVI  computed from bands → DERIVED REAL (if bands available)

Notes
-----
- Sentinel-1 / SAR was investigated.  Planetary Computer hosts the
  'sentinel-1-rtc' collection (Radiometric Terrain Corrected backscatter).
  Retrieval is possible via the same STAC API.  However, aligning two
  independent raster datasets (different orbits, resolutions, timestamps)
  within a hackathon timeline adds substantial complexity.  SAR is
  documented as a *future enhancement* and is NOT implemented here.
  This file contains a stub `fetch_sentinel1_stub` that demonstrates
  how the query would look.

Caching
-------
Downloaded band arrays are cached as .npz files under
backend/data/raw/sentinel2/<scene_id>.npz so that re-runs do not
re-download the same scenes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.config import (
    PUNJAB_BBOX,
    RAW_DIR,
    PROCESSED_DIR,
    SENTINEL2_BANDS,
    SENTINEL2_COLLECTION,
    SENTINEL2_LOOKBACK_DAYS,
    SENTINEL2_MAX_CLOUD_COVER,
    SENTINEL2_TEMPORAL_STEPS,
    GRID_RESOLUTION_DEG,
)
from backend.utils.geo import get_cached_grid

logger = logging.getLogger(__name__)

SENTINEL2_CACHE_DIR = RAW_DIR / "sentinel2"
SENTINEL2_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── STAC query helpers ────────────────────────────────────────────────────────

def _stac_client():
    """Return a signed Planetary Computer STAC client."""
    import planetary_computer
    import pystac_client

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    return catalog


def search_sentinel2_scenes(
    start_date: str,
    end_date: str,
    max_cloud: int = SENTINEL2_MAX_CLOUD_COVER,
) -> List[Any]:
    """
    Query Planetary Computer for Sentinel-2 L2A scenes covering Punjab.

    Parameters
    ----------
    start_date, end_date : ISO-8601 strings, e.g. "2024-01-01"
    max_cloud            : maximum cloud cover percentage

    Returns
    -------
    List of pystac Item objects, sorted oldest → newest.
    """
    bbox = [
        PUNJAB_BBOX["west"],
        PUNJAB_BBOX["south"],
        PUNJAB_BBOX["east"],
        PUNJAB_BBOX["north"],
    ]

    catalog = _stac_client()
    search = catalog.search(
        collections=[SENTINEL2_COLLECTION],
        bbox=bbox,
        datetime=f"{start_date}/{end_date}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        sortby="datetime",
    )
    items = list(search.items())
    logger.info(
        "Sentinel-2 search [%s → %s]: %d scenes (cloud < %d%%).",
        start_date, end_date, len(items), max_cloud,
    )
    return items


# ── Band retrieval & NDVI ─────────────────────────────────────────────────────

def _cache_key(scene_id: str) -> Path:
    return SENTINEL2_CACHE_DIR / f"{scene_id}.npz"


def _load_band_array(item: Any, band_key: str, target_shape: Tuple[int, int]) -> Optional[np.ndarray]:
    """
    Download a single band from a Planetary Computer item,
    reproject to EPSG:4326, and resample to target_shape (H, W).

    Returns float32 array or None on failure.
    """
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject

        band_name = SENTINEL2_BANDS[band_key]
        href = item.assets[band_name].href

        with rasterio.open(href) as src:
            # Reproject to WGS84
            transform, width, height = calculate_default_transform(
                src.crs, "EPSG:4326", src.width, src.height, *src.bounds
            )

            kwargs = src.meta.copy()
            kwargs.update(
                crs="EPSG:4326",
                transform=transform,
                width=width,
                height=height,
                driver="MEM",
            )

            import rasterio.io
            with rasterio.io.MemoryFile() as memfile:
                with memfile.open(**kwargs) as dst:
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=rasterio.band(dst, 1),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs="EPSG:4326",
                        resampling=Resampling.bilinear,
                    )
                    data = dst.read(
                        1,
                        out_shape=target_shape,
                        resampling=Resampling.bilinear,
                    ).astype(np.float32)

        # Sentinel-2 L2A reflectance is stored as DN (0–10000); normalise
        data = np.where(data > 0, data / 10000.0, np.nan)
        return data

    except Exception as exc:
        logger.warning("Band %s load failed for scene %s: %s", band_key, item.id, exc)
        return None


def compute_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    NDVI = (NIR - Red) / (NIR + Red)

    Both inputs should be float32 reflectance (0–1 range, NaN for invalid).
    Output is clipped to [-1, 1].
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
    ndvi = np.where(np.isfinite(ndvi), np.clip(ndvi, -1.0, 1.0), np.nan)
    return ndvi.astype(np.float32)


def compute_evi(blue: np.ndarray, red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    EVI = 2.5 × (NIR - Red) / (NIR + 6×Red - 7.5×Blue + 1)

    Requires B02 (Blue), B04 (Red), B08 (NIR).
    Output clipped to [-1, 1].
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        evi = 2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1.0)
    evi = np.where(np.isfinite(evi), np.clip(evi, -1.0, 1.0), np.nan)
    return evi.astype(np.float32)


def process_scene(item: Any, grid_shape: Tuple[int, int]) -> Optional[Dict[str, np.ndarray]]:
    """
    Load required bands for one scene, compute NDVI (and EVI if possible).

    Results are cached in SENTINEL2_CACHE_DIR.

    Returns dict with keys: ndvi, evi (optional), timestamp (ISO string)
    or None on total failure.
    """
    cache_path = _cache_key(item.id)

    if cache_path.exists():
        data = np.load(cache_path, allow_pickle=True)
        result: Dict[str, Any] = {k: data[k] for k in data.files}
        result["timestamp"] = str(result.get("timestamp", "unknown"))
        logger.debug("Scene %s loaded from cache.", item.id)
        return result

    H, W = grid_shape
    red = _load_band_array(item, "red", (H, W))
    nir = _load_band_array(item, "nir", (H, W))

    if red is None or nir is None:
        logger.warning("Skipping scene %s: required bands missing.", item.id)
        return None

    ndvi = compute_ndvi(red, nir)
    result: Dict[str, Any] = {
        "ndvi": ndvi,
        "timestamp": item.datetime.isoformat() if item.datetime else "unknown",
    }

    # EVI (optional — needs blue band)
    blue = _load_band_array(item, "blue", (H, W))
    if blue is not None:
        result["evi"] = compute_evi(blue, red, nir)
    else:
        logger.debug("EVI skipped for scene %s (blue band unavailable).", item.id)

    # Save cache
    save_dict = {k: v for k, v in result.items() if isinstance(v, np.ndarray)}
    save_dict["timestamp"] = np.array(result["timestamp"])
    np.savez_compressed(cache_path, **save_dict)
    logger.info("Scene %s processed and cached.", item.id)

    return result


# ── Temporal aggregation to grid ──────────────────────────────────────────────

def build_temporal_ndvi_stack(
    scenes: List[Dict],
    n_steps: int = SENTINEL2_TEMPORAL_STEPS,
) -> Tuple[np.ndarray, List[str]]:
    """
    Given a list of processed scene dicts, aggregate into an
    (n_steps × H × W) NDVI temporal stack.

    Missing steps are filled with np.nan.

    Returns
    -------
    stack      : float32 array (n_steps, H, W)
    timestamps : list of ISO strings (length n_steps)
    """
    if not scenes:
        raise ValueError("No scenes provided for temporal stacking.")

    H, W = scenes[0]["ndvi"].shape

    # Use the most recent n_steps scenes
    recent = scenes[-n_steps:]
    # Pad at the front with NaN scenes if fewer than n_steps available
    pad_count = n_steps - len(recent)

    stack = np.full((n_steps, H, W), np.nan, dtype=np.float32)
    timestamps = ["missing"] * n_steps

    for idx, scene in enumerate(recent):
        stack[pad_count + idx] = scene["ndvi"]
        timestamps[pad_count + idx] = scene.get("timestamp", "unknown")

    logger.info(
        "NDVI stack built: %d steps (%d real, %d padded).",
        n_steps, len(recent), pad_count,
    )
    return stack, timestamps


def build_temporal_evi_stack(
    scenes: List[Dict],
    n_steps: int = SENTINEL2_TEMPORAL_STEPS,
) -> Optional[Tuple[np.ndarray, List[str]]]:
    """
    Same as NDVI stack but for EVI.  Returns None if no scene has EVI data.
    """
    evi_scenes = [s for s in scenes if "evi" in s]
    if not evi_scenes:
        return None

    H, W = evi_scenes[0]["evi"].shape
    recent = evi_scenes[-n_steps:]
    pad_count = n_steps - len(recent)

    stack = np.full((n_steps, H, W), np.nan, dtype=np.float32)
    timestamps = ["missing"] * n_steps
    for idx, scene in enumerate(recent):
        stack[pad_count + idx] = scene["evi"]
        timestamps[pad_count + idx] = scene.get("timestamp", "unknown")

    return stack, timestamps


# ── Main entry point for the pipeline ────────────────────────────────────────

def ingest_sentinel2(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full Sentinel-2 ingestion pipeline for Punjab.

    1. Search Planetary Computer
    2. Process each scene (NDVI, EVI)
    3. Build temporal stacks

    Returns dict with:
        ndvi_stack  : (n_steps, H, W) float32
        evi_stack   : (n_steps, H, W) float32 or None
        timestamps  : list of ISO strings
        grid_shape  : (H, W)
    """
    if end_date is None:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (datetime.utcnow() - timedelta(days=SENTINEL2_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    grid = get_cached_grid()
    grid_shape = (grid["height"], grid["width"])

    items = search_sentinel2_scenes(start_date, end_date)
    if not items:
        logger.warning("No Sentinel-2 scenes found. Returning NaN stacks.")
        H, W = grid_shape
        n = SENTINEL2_TEMPORAL_STEPS
        return {
            "ndvi_stack": np.full((n, H, W), np.nan, dtype=np.float32),
            "evi_stack": None,
            "timestamps": ["missing"] * n,
            "grid_shape": grid_shape,
            "scene_count": 0,
        }

    processed = []
    for item in items:
        result = process_scene(item, grid_shape)
        if result is not None:
            processed.append(result)

    if not processed:
        logger.error("All scenes failed to process.")
        H, W = grid_shape
        n = SENTINEL2_TEMPORAL_STEPS
        return {
            "ndvi_stack": np.full((n, H, W), np.nan, dtype=np.float32),
            "evi_stack": None,
            "timestamps": ["missing"] * n,
            "grid_shape": grid_shape,
            "scene_count": 0,
        }

    ndvi_stack, timestamps = build_temporal_ndvi_stack(processed)
    evi_result = build_temporal_evi_stack(processed)
    evi_stack = evi_result[0] if evi_result else None

    return {
        "ndvi_stack": ndvi_stack,
        "evi_stack": evi_stack,
        "timestamps": timestamps,
        "grid_shape": grid_shape,
        "scene_count": len(processed),
    }


# ── Sentinel-1 stub (future enhancement) ─────────────────────────────────────

def fetch_sentinel1_stub(start_date: str, end_date: str) -> None:
    """
    STUB — Sentinel-1 / SAR ingestion.

    Sentinel-1 RTC data IS available on Microsoft Planetary Computer via
    the 'sentinel-1-rtc' collection.  A STAC query would look like:

        catalog.search(
            collections=["sentinel-1-rtc"],
            bbox=[73.8, 29.5, 76.9, 32.6],
            datetime=f"{start_date}/{end_date}",
        )

    Relevant bands: VV (vertical transmit / vertical receive),
                    VH (vertical transmit / horizontal receive).
    VV/VH ratio is correlated with soil moisture and canopy structure.

    Why NOT implemented in this prototype:
    - Sentinel-1 RTC scenes have a different revisit schedule than S-2.
    - Temporal alignment of two independent raster stacks requires
      significant additional engineering.
    - Scene-level footprints differ from Sentinel-2 tiles.
    - Within hackathon time constraints, adding unreliable SAR features
      would risk destabilising the core NDVI pipeline.

    This is documented as a *high-value future enhancement*.
    VV/VH features would be especially beneficial during the
    kharif (monsoon) season when cloud cover is high and Sentinel-2
    optical observations are sparse.
    """
    raise NotImplementedError(
        "Sentinel-1 is documented as a future enhancement. See docstring."
    )
