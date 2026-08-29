"""
CropGuard AI — Feature engineering and spatiotemporal dataset construction.

Feature tensor layout
---------------------
For each grid cell (i, j) and time step t we assemble a feature vector:

  Index  Name                         Source           Classification
  -----  ---------------------------  ---------------  --------------
  0      ndvi                         Sentinel-2       DERIVED REAL
  1      evi                          Sentinel-2       DERIVED REAL / NaN if absent
  2      temperature_2m_max           Open-Meteo/ERA5  REAL
  3      temperature_2m_min           Open-Meteo/ERA5  REAL
  4      relative_humidity_2m_max     Open-Meteo/ERA5  REAL
  5      relative_humidity_2m_min     Open-Meteo/ERA5  REAL
  6      precipitation_sum            Open-Meteo/ERA5  REAL
  7      wind_speed_10m_max           Open-Meteo/ERA5  REAL
  8      crop_type_onehot_0 (wheat)   Crop service     STATIC
  9      crop_type_onehot_1 (paddy)   Crop service     STATIC
  10     crop_type_onehot_2 (cotton)  Crop service     STATIC
  11     crop_stage_index             Crop service     STATIC
  12     susceptibility               Crop service     STATIC
  13     outbreak_frequency           Outbreak service SYNTHETIC
  14     outbreak_recency             Outbreak service SYNTHETIC

Full tensor shape: (T, H, W, F)  where F=15

Normalisation
-------------
Each feature channel is normalised independently across all cells and
time steps using training-set statistics (mean / std).  The scaler
object is persisted to disk so that inference uses training statistics.

Training split
--------------
Chronological split to avoid data leakage:
  0 – 70%  → training
  70 – 85% → validation
  85 – 100%→ test
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.config import (
    PROCESSED_DIR,
    MODELS_DIR,
    SENTINEL2_TEMPORAL_STEPS,
    WEATHER_VARIABLES,
)
from backend.utils.geo import get_cached_grid

logger = logging.getLogger(__name__)

N_FEATURES = 15
FEATURE_NAMES = [
    "ndvi",
    "evi",
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "crop_wheat",
    "crop_paddy",
    "crop_cotton",
    "crop_stage",
    "susceptibility",
    "outbreak_frequency",
    "outbreak_recency",
]

SCALER_PATH = MODELS_DIR / "feature_scaler.pkl"


# ── Feature assembly ──────────────────────────────────────────────────────────

def build_feature_tensor(
    ndvi_stack: np.ndarray,           # (T, H, W)
    evi_stack: Optional[np.ndarray],  # (T, H, W) or None
    weather_data: Dict[str, np.ndarray],  # var → (T, H, W)
    crop_grid: np.ndarray,            # (H, W) int8
    stage_grid: np.ndarray,           # (H, W) int8
    susceptibility_grid: np.ndarray,  # (H, W) float32
    outbreak_labels: np.ndarray,      # (T, H, W) float32 — used for historical context features
) -> np.ndarray:
    """
    Assemble the spatiotemporal feature tensor.

    Returns
    -------
    tensor : float32 array of shape (T, H, W, N_FEATURES)
    """
    T, H, W = ndvi_stack.shape

    tensor = np.full((T, H, W, N_FEATURES), np.nan, dtype=np.float32)

    # Channel 0: NDVI
    tensor[:, :, :, 0] = ndvi_stack

    # Channel 1: EVI (NaN if not computed)
    if evi_stack is not None:
        tensor[:, :, :, 1] = evi_stack

    # Channels 2-7: Weather variables
    for ch_idx, var in enumerate(WEATHER_VARIABLES):
        arr = weather_data.get(var)
        if arr is not None and arr.shape == (T, H, W):
            tensor[:, :, :, 2 + ch_idx] = arr
        elif arr is not None:
            # Shape mismatch — try to broadcast or skip
            logger.warning("Weather var %s shape %s ≠ (%d,%d,%d). Skipping.", var, arr.shape, T, H, W)

    # Channels 8-10: Crop one-hot  (broadcast across time)
    for crop_idx in range(3):
        tensor[:, :, :, 8 + crop_idx] = (crop_grid == crop_idx).astype(np.float32)[np.newaxis, :, :]

    # Channel 11: Crop stage (broadcast)
    tensor[:, :, :, 11] = stage_grid.astype(np.float32)[np.newaxis, :, :]

    # Channel 12: Susceptibility (broadcast)
    tensor[:, :, :, 12] = susceptibility_grid[np.newaxis, :, :]

    # Channel 13: Outbreak frequency (fraction of past steps with prob > 0.5)
    binary_labels = (outbreak_labels > 0.5).astype(np.float32)
    for t in range(T):
        window = binary_labels[:t + 1]  # all steps up to and including t
        tensor[t, :, :, 13] = window.mean(axis=0)

    # Channel 14: Outbreak recency (steps since last outbreak; normalised)
    last_outbreak = np.full((H, W), T, dtype=np.float32)
    for t in range(T):
        had_outbreak = binary_labels[t] > 0
        last_outbreak[had_outbreak] = t
    for t in range(T):
        tensor[t, :, :, 14] = (t - last_outbreak).clip(0) / float(T)

    logger.info("Feature tensor assembled: shape %s", tensor.shape)
    return tensor


# ── NaN imputation ────────────────────────────────────────────────────────────

def impute_nan(tensor: np.ndarray) -> np.ndarray:
    """
    Replace NaN values channel-by-channel with the channel median.
    If an entire channel is NaN, fill with 0.
    """
    T, H, W, F = tensor.shape
    result = tensor.copy()
    for f in range(F):
        channel = result[:, :, :, f]
        if np.isnan(channel).all():
            result[:, :, :, f] = 0.0
        elif np.isnan(channel).any():
            med = float(np.nanmedian(channel))
            result[:, :, :, f] = np.where(np.isnan(channel), med, channel)
    return result


# ── Normalisation ─────────────────────────────────────────────────────────────

class ChannelScaler:
    """Per-channel mean/std normalisation. Fit on training data only."""

    def __init__(self):
        self.means: Optional[np.ndarray] = None  # (F,)
        self.stds:  Optional[np.ndarray] = None  # (F,)
        self.fitted = False

    def fit(self, tensor: np.ndarray) -> "ChannelScaler":
        """tensor: (T, H, W, F)"""
        F = tensor.shape[-1]
        flat = tensor.reshape(-1, F)
        self.means = np.nanmean(flat, axis=0).astype(np.float32)
        self.stds  = np.nanstd(flat, axis=0).astype(np.float32)
        self.stds  = np.where(self.stds < 1e-8, 1.0, self.stds)
        self.fitted = True
        return self

    def transform(self, tensor: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("Scaler not fitted.")
        return ((tensor - self.means) / self.stds).astype(np.float32)

    def inverse_transform(self, tensor: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("Scaler not fitted.")
        return (tensor * self.stds + self.means).astype(np.float32)

    def save(self, path: Path = SCALER_PATH) -> None:
        with open(path, "wb") as fh:
            pickle.dump(self, fh)
        logger.info("Scaler saved → %s", path)

    @classmethod
    def load(cls, path: Path = SCALER_PATH) -> "ChannelScaler":
        with open(path, "rb") as fh:
            scaler = pickle.load(fh)
        logger.info("Scaler loaded from %s", path)
        return scaler


def load_or_create_scaler() -> ChannelScaler:
    if SCALER_PATH.exists():
        return ChannelScaler.load()
    return ChannelScaler()


# ── Sequence construction for ConvLSTM ───────────────────────────────────────

def build_sequences(
    tensor: np.ndarray,    # (T, H, W, F) normalised
    labels: np.ndarray,    # (T, H, W) float32
    seq_len: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Build overlapping sequences for ConvLSTM training.

    X : (N, seq_len, H, W, F)
    y : (N, H, W, 1) — label at step t+1 (next-step prediction)

    If T <= seq_len, seq_len is automatically reduced to T-1 so that
    at least one training sample is produced.  A warning is logged
    when this happens — it means the satellite/weather lookback window
    should be extended for better model quality.
    """
    T = tensor.shape[0]
    if T <= seq_len:
        adjusted = T - 1
        logger.warning(
            "Tensor has only T=%d time steps but seq_len=%d was requested. "
            "Reducing seq_len to %d to produce at least one sample. "
            "Extend the lookback window (SENTINEL2_LOOKBACK_DAYS) for better "
            "model quality.",
            T, seq_len, adjusted,
        )
        seq_len = adjusted

    if seq_len < 1:
        raise ValueError(
            f"Cannot build sequences: tensor has T={T} time steps. "
            "Need at least T=2. Check that satellite/weather ingestion produced data."
        )

    xs, ys = [], []
    for t in range(T - seq_len):
        xs.append(tensor[t: t + seq_len])
        ys.append(labels[t + seq_len, :, :, np.newaxis])
    return np.stack(xs), np.stack(ys), seq_len


def chronological_split(
    X: np.ndarray,
    y: np.ndarray,
    train_frac: float = 0.70,
    val_frac:   float = 0.15,
) -> Tuple:
    """
    Chronological train/val/test split to avoid data leakage.

    Returns (X_train, y_train, X_val, y_val, X_test, y_test)
    """
    N = len(X)
    n_train = int(N * train_frac)
    n_val   = int(N * (train_frac + val_frac))

    logger.info(
        "Chronological split: train=%d, val=%d, test=%d",
        n_train, n_val - n_train, N - n_val,
    )

    return (
        X[:n_train],   y[:n_train],
        X[n_train:n_val], y[n_train:n_val],
        X[n_val:],     y[n_val:],
    )


# ── Complete preprocessing pipeline ──────────────────────────────────────────

def run_preprocessing(
    ndvi_stack: np.ndarray,
    evi_stack: Optional[np.ndarray],
    weather_data: Dict[str, np.ndarray],
    crop_grid: np.ndarray,
    stage_grid: np.ndarray,
    susceptibility_grid: np.ndarray,
    outbreak_labels: np.ndarray,
    seq_len: int = SENTINEL2_TEMPORAL_STEPS,
    force_refit_scaler: bool = False,
) -> Dict[str, Any]:
    """
    Full preprocessing pipeline:
    1. Build feature tensor
    2. Impute NaN
    3. Fit / load scaler
    4. Normalise
    5. Build sequences
    6. Chronological split

    Returns dict with X_train, y_train, X_val, y_val, X_test, y_test,
    scaler, feature_tensor (raw), feature_tensor_norm.
    """
    # Step 1 & 2
    tensor_raw = build_feature_tensor(
        ndvi_stack, evi_stack, weather_data,
        crop_grid, stage_grid, susceptibility_grid, outbreak_labels,
    )
    tensor_clean = impute_nan(tensor_raw)

    # Step 3 & 4
    scaler = load_or_create_scaler()
    if not scaler.fitted or force_refit_scaler:
        # Fit on first 70% only (training portion)
        T = tensor_clean.shape[0]
        n_train = int(T * 0.70)
        scaler.fit(tensor_clean[:n_train])
        scaler.save()

    tensor_norm = scaler.transform(tensor_clean)

    # Step 5
    X, y, actual_seq_len = build_sequences(tensor_norm, outbreak_labels, seq_len)
    if actual_seq_len != seq_len:
        logger.warning(
            "seq_len was reduced from %d → %d due to limited time steps. "
            "The ConvLSTM will be built with seq_len=%d.",
            seq_len, actual_seq_len, actual_seq_len,
        )
        seq_len = actual_seq_len

    # Step 6
    X_train, y_train, X_val, y_val, X_test, y_test = chronological_split(X, y)

    # Save processed dataset
    dataset_path = PROCESSED_DIR / "dataset.npz"
    np.savez_compressed(
        dataset_path,
        X_train=X_train, y_train=y_train,
        X_val=X_val,     y_val=y_val,
        X_test=X_test,   y_test=y_test,
    )
    logger.info("Dataset saved → %s", dataset_path)

    return {
        "X_train": X_train, "y_train": y_train,
        "X_val":   X_val,   "y_val":   y_val,
        "X_test":  X_test,  "y_test":  y_test,
        "scaler": scaler,
        "seq_len": seq_len,
        "feature_tensor": tensor_raw,
        "feature_tensor_norm": tensor_norm,
    }


def load_dataset() -> Optional[Dict[str, np.ndarray]]:
    """Load a previously saved dataset from disk."""
    path = PROCESSED_DIR / "dataset.npz"
    if not path.exists():
        return None
    data = np.load(path)
    return {k: data[k] for k in data.files}
