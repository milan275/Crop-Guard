"""
CropGuard AI — Historical outbreak data service.

Real data investigation
-----------------------
Sources investigated:
1. Punjab Agriculture Department — Pest surveillance bulletins exist as PDFs.
   No public API or machine-readable dataset was accessible.
2. ICAR Central Research Institute for Dryland Agriculture (CRIDA)
   — District-level reports; not in machine-readable format.
3. Punjab Agricultural University (PAU) — Pest forecasting research papers
   exist but no public dataset download.
4. Integrated Pest Management (IPM) India portal (ipm.dacnet.nic.in)
   — Static HTML, no API.
5. FAO EMPRES-i — Global pest database; Punjab-level records are sparse
   and not at field/grid level.
6. ICRISAT Open Data Portal — Limited India crop pest data.

Result: No freely accessible, spatiotemporally granular pest outbreak
dataset for Punjab could be obtained.

We therefore generate SYNTHETIC outbreak labels using a physically
motivated simulation.  This approach is explicitly labelled as SYNTHETIC
throughout the codebase.

Synthetic generation method
-----------------------------
Probability of outbreak at cell (i, j) at time t is computed as:

  P_outbreak(i,j,t) = sigmoid(
      w_ndvi   × stress(ndvi[t,i,j])
    + w_temp   × temp_suitability(temp[t,i,j], crop)
    + w_humid  × humidity_suitability(humid[t,i,j], crop)
    + w_susc   × susceptibility(crop, stage)
    + w_spatial × neighborhood_pressure(P[t-1,i,j])
    - threshold
  )

Where:
  stress(ndvi)         = max(0, mean_ndvi - ndvi) / 0.5
                         (declining NDVI indicates stress)
  temp_suitability     = 1 - |temp - optimal_temp| / 10
                         (bell curve around optimal temperature)
  humidity_suitability = clamp(humid - 60, 0, 40) / 40
                         (higher humidity → higher risk)
  neighborhood_pressure = mean risk of 8 adjacent cells at t-1
  susceptibility       = from crop calendar

Weights and thresholds are deliberately conservative so that outbreak
probability is typically LOW outside the susceptibility window.

Classification: SYNTHETIC — explicitly labelled.

Why synthetic evaluation ≠ real-world validation:
The model is trained on labels that are themselves derived from the
same features used for training.  Any metrics computed (precision,
recall, AUC) reflect the model's ability to learn the synthetic rule,
NOT its ability to predict real outbreaks.  Replacing synthetic labels
with verified historical outbreak records is the most important path
to real-world validation.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from backend.config import PROCESSED_DIR, SENTINEL2_TEMPORAL_STEPS
from backend.utils.geo import get_cached_grid
from backend.services.crop_service import get_stage_susceptibility

logger = logging.getLogger(__name__)


# ── Per-crop optimal pest conditions ─────────────────────────────────────────
# These are documented estimates from agricultural literature.
# Source classification: STATIC (domain knowledge).

PEST_CONDITIONS: Dict[str, Dict[str, float]] = {
    "wheat": {
        "optimal_temp_c":    18.0,   # Yellow rust optimal ~10–18°C
        "min_humidity_pct":  60.0,
        "temp_tolerance":    8.0,
    },
    "paddy": {
        "optimal_temp_c":    28.0,   # BPH / stem borer optimal ~25–30°C
        "min_humidity_pct":  70.0,
        "temp_tolerance":    6.0,
    },
    "cotton": {
        "optimal_temp_c":    30.0,   # Bollworm / whitefly optimal ~28–32°C
        "min_humidity_pct":  55.0,
        "temp_tolerance":    8.0,
    },
}

DEFAULT_PEST_CONDITIONS = {"optimal_temp_c": 25.0, "min_humidity_pct": 65.0, "temp_tolerance": 8.0}

# Simulation weights
W_NDVI    = 0.30
W_TEMP    = 0.25
W_HUMID   = 0.20
W_SUSC    = 0.35
W_SPATIAL = 0.15
THRESHOLD = 0.80   # logit offset — keeps baseline probability low


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _stress_from_ndvi(ndvi_t: np.ndarray, ndvi_mean: np.ndarray) -> np.ndarray:
    """Vegetation stress: declining NDVI relative to temporal mean."""
    stress = (ndvi_mean - ndvi_t) / 0.5
    return np.clip(stress, 0.0, 1.0)


def _temp_suitability(temp_t: np.ndarray, crop: str) -> np.ndarray:
    cond = PEST_CONDITIONS.get(crop, DEFAULT_PEST_CONDITIONS)
    opt = cond["optimal_temp_c"]
    tol = cond["temp_tolerance"]
    suitability = 1.0 - np.abs(temp_t - opt) / tol
    return np.clip(suitability, 0.0, 1.0)


def _humidity_suitability(humid_t: np.ndarray, crop: str) -> np.ndarray:
    cond = PEST_CONDITIONS.get(crop, DEFAULT_PEST_CONDITIONS)
    min_h = cond["min_humidity_pct"]
    suitability = (humid_t - min_h) / 40.0
    return np.clip(suitability, 0.0, 1.0)


def _neighborhood_pressure(prob_prev: np.ndarray) -> np.ndarray:
    """Mean risk of 8 neighbours from previous time step."""
    from scipy.ndimage import uniform_filter
    return uniform_filter(prob_prev, size=3)


def generate_synthetic_outbreak_labels(
    ndvi_stack: np.ndarray,           # (T, H, W)
    temp_stack: np.ndarray,           # (T, H, W)
    humid_stack: np.ndarray,          # (T, H, W)
    susceptibility_stack: np.ndarray, # (T, H, W)
    mask: np.ndarray,                 # (H, W) bool
    crop_stack: np.ndarray,           # (T, H, W) int8
    random_seed: int = 42,
) -> np.ndarray:
    """
    Generate synthetic binary outbreak labels for the spatiotemporal grid.

    Returns
    -------
    labels : (T, H, W) float32 in [0, 1] representing outbreak probability.
             Threshold at 0.5 to get binary labels.

    DATA CLASSIFICATION: SYNTHETIC
    """
    rng = np.random.default_rng(random_seed)
    T, H, W = ndvi_stack.shape

    crop_names = {0: "wheat", 1: "paddy", 2: "cotton"}
    ndvi_mean = np.nanmean(ndvi_stack, axis=0)  # (H, W)

    # Fill NaN with plausible defaults
    def _fill_nan(arr: np.ndarray, fill: float = 0.0) -> np.ndarray:
        result = arr.copy()
        result[np.isnan(result)] = fill
        return result

    ndvi_stack_f   = _fill_nan(ndvi_stack, 0.3)
    temp_stack_f   = _fill_nan(temp_stack, 25.0)
    humid_stack_f  = _fill_nan(humid_stack, 65.0)
    ndvi_mean_f    = _fill_nan(ndvi_mean, 0.3)

    probs = np.zeros((T, H, W), dtype=np.float32)

    for t in range(T):
        # Determine dominant crop at each cell for this step
        crop_t = crop_stack[t] if t < len(crop_stack) else crop_stack[-1]

        # Compute per-crop suitability arrays
        temp_suit  = np.zeros((H, W), dtype=np.float32)
        humid_suit = np.zeros((H, W), dtype=np.float32)

        for crop_idx, crop_name in crop_names.items():
            c_mask = (crop_t == crop_idx) & mask
            if c_mask.any():
                temp_suit[c_mask]  = _temp_suitability(temp_stack_f[t][c_mask], crop_name)
                humid_suit[c_mask] = _humidity_suitability(humid_stack_f[t][c_mask], crop_name)

        stress   = _stress_from_ndvi(ndvi_stack_f[t], ndvi_mean_f)
        susc     = susceptibility_stack[t] if t < len(susceptibility_stack) else susceptibility_stack[-1]
        spatial  = _neighborhood_pressure(probs[t - 1]) if t > 0 else np.zeros((H, W))

        logit = (
            W_NDVI    * stress
            + W_TEMP  * temp_suit
            + W_HUMID * humid_suit
            + W_SUSC  * susc
            + W_SPATIAL * spatial
            - THRESHOLD
        )

        prob = _sigmoid(logit)
        prob = np.where(mask, prob, 0.0)

        # Add small stochastic noise for realism
        noise = rng.uniform(-0.03, 0.03, size=(H, W)).astype(np.float32)
        prob = np.clip(prob + noise, 0.0, 1.0)

        probs[t] = prob

    logger.info(
        "Synthetic outbreak labels generated: T=%d, H=%d, W=%d, "
        "mean probability=%.3f",
        T, H, W, float(probs[mask.reshape(1, H, W).repeat(T, 0)].mean()),
    )
    return probs


def load_or_generate_outbreak_labels(
    ndvi_stack: np.ndarray,
    temp_stack: np.ndarray,
    humid_stack: np.ndarray,
    susceptibility_stack: np.ndarray,
    crop_stack: np.ndarray,
    force_regenerate: bool = False,
) -> np.ndarray:
    """
    Load cached synthetic labels or regenerate them.
    Cache path: backend/data/processed/synthetic_labels.npz
    """
    cache_path = PROCESSED_DIR / "synthetic_labels.npz"

    if not force_regenerate and cache_path.exists():
        data = np.load(cache_path)
        labels = data["labels"]
        logger.info("Synthetic labels loaded from cache (shape %s).", labels.shape)
        return labels

    grid = get_cached_grid()
    mask = grid["mask"]

    labels = generate_synthetic_outbreak_labels(
        ndvi_stack=ndvi_stack,
        temp_stack=temp_stack,
        humid_stack=humid_stack,
        susceptibility_stack=susceptibility_stack,
        mask=mask,
        crop_stack=crop_stack,
    )

    np.savez_compressed(cache_path, labels=labels)
    logger.info("Synthetic labels saved → %s", cache_path)
    return labels
