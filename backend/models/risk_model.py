"""
CropGuard AI — Risk model: wraps ConvLSTM and exposes a clean interface
for the FastAPI service layer.

Responsibilities
----------------
1. Load (or train) the ConvLSTM model.
2. Build the latest feature sequence from cached data.
3. Generate current and forecast risk maps.
4. Apply expert overrides.
5. Return structured risk output.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from backend.config import (
    OUTPUTS_DIR,
    PROCESSED_DIR,
    SENTINEL2_TEMPORAL_STEPS,
    CONVLSTM_CONFIG,
)
from backend.models.convlstm_forecaster import (
    MODEL_PATH,
    load_model,
    predict_risk,
    predict_multi_step_risk,
)
from backend.models.preprocessing import (
    SCALER_PATH,
    ChannelScaler,
    N_FEATURES,
    impute_nan,
)
from backend.utils.geo import (
    get_cached_grid,
    risk_level_from_probability,
    bbox_to_grid_indices,
)
from backend.utils.grid import risk_map_to_geojson, save_risk_map, district_risk_summary

logger = logging.getLogger(__name__)

# Forecast horizons in days
FORECAST_HORIZONS = [0, 1, 3, 7]

# In-memory cache of latest risk maps (populated after inference)
_risk_cache: Dict[int, np.ndarray] = {}   # horizon_days → (H, W) array
_risk_timestamps: Dict[int, str]   = {}   # horizon_days → ISO timestamp


# ── Risk map loading / generation ─────────────────────────────────────────────

def _load_latest_tensor() -> Optional[np.ndarray]:
    """Load the latest normalised feature tensor from disk if available."""
    path = PROCESSED_DIR / "latest_tensor.npz"
    if path.exists():
        data = np.load(path)
        return data["tensor"]
    return None


def _ensure_risk_maps() -> bool:
    """
    Populate _risk_cache from saved GeoJSON outputs or by running inference.
    Returns True if at least the current (0-day) map is available.
    """
    global _risk_cache, _risk_timestamps

    # Try to load from previously saved outputs
    for horizon in FORECAST_HORIZONS:
        path = OUTPUTS_DIR / f"risk_latest_{horizon}d.npz"
        if path.exists():
            data = np.load(path)
            _risk_cache[horizon] = data["risk_map"]
            _risk_timestamps[horizon] = str(data.get("timestamp", b"unknown"))

    if 0 in _risk_cache:
        return True

    # Attempt inference
    return run_inference_pipeline()


def run_inference_pipeline() -> bool:
    """
    Run the full inference pipeline to produce fresh risk maps.
    1. Load model
    2. Load latest feature tensor
    3. Predict current + forecast risk
    4. Cache results
    Returns True on success.
    """
    global _risk_cache, _risk_timestamps

    model = load_model()
    if model is None:
        logger.warning("Model not found — cannot run inference.")
        return False

    tensor = _load_latest_tensor()
    if tensor is None:
        logger.warning("No feature tensor found — run the pipeline first.")
        return False

    scaler = ChannelScaler.load() if SCALER_PATH.exists() else None
    if scaler is None:
        logger.warning("Scaler not found — inference skipped.")
        return False

    # tensor shape: (T, H, W, F) — take last seq_len steps
    seq_len = CONVLSTM_CONFIG["sequence_length"]
    if tensor.shape[0] < seq_len:
        seq_len = tensor.shape[0]
        logger.warning("Tensor shorter than config seq_len; using seq_len=%d for inference.", seq_len)

    seq = tensor[-seq_len:]  # (seq_len, H, W, F)
    grid = get_cached_grid()
    mask = grid["mask"]

    now = datetime.utcnow().isoformat()

    # Current risk
    current_risk = predict_risk(model, seq)
    current_risk = np.where(mask, current_risk, 0.0)
    _risk_cache[0] = current_risk
    _risk_timestamps[0] = now

    # Multi-step forecasts
    forecasts = predict_multi_step_risk(model, seq, n_steps=7, mask=mask)
    for day in [1, 3, 7]:
        if day <= forecasts.shape[0]:
            _risk_cache[day] = forecasts[day - 1]
            _risk_timestamps[day] = now

    # Persist
    for horizon, risk_map in _risk_cache.items():
        path = OUTPUTS_DIR / f"risk_latest_{horizon}d.npz"
        np.savez_compressed(path, risk_map=risk_map, timestamp=np.bytes_(now))
        save_risk_map(risk_map, now, f"{horizon}d")

    logger.info("Inference pipeline complete. Risk maps generated for horizons: %s", list(_risk_cache.keys()))
    return True


# ── Override application ──────────────────────────────────────────────────────

def apply_overrides(
    risk_map: np.ndarray,
    overrides: List[Dict],
) -> np.ndarray:
    """
    Apply expert geographic overrides to a risk map.

    Override dict fields: bottom_left_lat, bottom_left_lon,
                          top_right_lat, top_right_lon,
                          override_prediction (float 0-1)

    Steps:
    1. For each active override, find affected grid cells.
    2. Replace risk values at those cells.
    3. Return updated map.
    """
    result = risk_map.copy()

    for ov in overrides:
        if not ov.get("active", True):
            continue

        indices = bbox_to_grid_indices(
            south=ov["bottom_left_lat"],
            west=ov["bottom_left_lon"],
            north=ov["top_right_lat"],
            east=ov["top_right_lon"],
        )

        pred = float(ov["override_prediction"])
        for (r, c) in indices:
            result[r, c] = pred

        logger.debug(
            "Override applied: %d cells → %.2f",
            len(indices), pred,
        )

    return result


# ── Public API used by FastAPI services ───────────────────────────────────────

def get_risk_map(
    horizon_days: int = 0,
    overrides: Optional[List[Dict]] = None,
) -> Optional[np.ndarray]:
    """Return (H, W) risk map for given horizon, with optional overrides."""
    _ensure_risk_maps()
    risk_map = _risk_cache.get(horizon_days)
    if risk_map is None:
        return None
    if overrides:
        risk_map = apply_overrides(risk_map, overrides)
    return risk_map


def get_cell_risk(
    row: int,
    col: int,
    horizon_days: int = 0,
    overrides: Optional[List[Dict]] = None,
) -> Optional[Dict[str, Any]]:
    """Return risk info for a single grid cell."""
    risk_map = get_risk_map(horizon_days, overrides)
    if risk_map is None:
        return None

    prob = float(risk_map[row, col])
    return {
        "risk_probability": round(prob, 4),
        "risk_level": risk_level_from_probability(prob),
        "horizon_days": horizon_days,
        "timestamp": _risk_timestamps.get(horizon_days, "unknown"),
    }


def get_point_risk(
    lat: float,
    lon: float,
    horizon_days: int = 0,
    overrides: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Return risk for an arbitrary (lat, lon)."""
    from backend.utils.geo import latlon_to_grid_index

    idx = latlon_to_grid_index(lat, lon)
    if idx is None:
        return {"error": "Location outside grid extent."}

    row, col = idx
    result = get_cell_risk(row, col, horizon_days, overrides)
    if result is None:
        result = {
            "risk_probability": None,
            "risk_level": None,
            "horizon_days": horizon_days,
            "timestamp": None,
            "note": "Risk map not yet available. Run pipeline first.",
        }
    result["lat"] = lat
    result["lon"] = lon
    return result


def get_district_risk_map(
    district: str,
    horizon_days: int = 0,
    overrides: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Return district-level risk summary and per-cell data."""
    risk_map = get_risk_map(horizon_days, overrides)
    if risk_map is None:
        return {
            "district": district,
            "error": "Risk map not available.",
            "cells": [],
        }
    summary = district_risk_summary(risk_map, district)
    summary["horizon_days"] = horizon_days
    summary["timestamp"] = _risk_timestamps.get(horizon_days, "unknown")
    return summary


def get_forecast_risk(
    lat: float,
    lon: float,
    overrides: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Return risk across all forecast horizons for a point."""
    results = []
    for horizon in FORECAST_HORIZONS:
        r = get_point_risk(lat, lon, horizon, overrides)
        results.append(r)
    return results
