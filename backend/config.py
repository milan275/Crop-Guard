"""
CropGuard AI — Central configuration.

All tuneable parameters are collected here so that nothing is hardcoded
deep inside service modules.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Repository paths ──────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent          # backend/
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"
OUTPUTS_DIR = DATA_DIR / "outputs"
BOUNDARIES_DIR = DATA_DIR / "boundaries"

for _d in (RAW_DIR, PROCESSED_DIR, MODELS_DIR, OUTPUTS_DIR, BOUNDARIES_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ── Punjab bounding box (approximate, for STAC queries) ──────────────────────
PUNJAB_BBOX = {
    "west": 73.8,
    "south": 29.5,
    "east": 76.9,
    "north": 32.6,
}

# ── Grid resolution (degrees) ─────────────────────────────────────────────────
# ~5 km at Punjab latitude — fine enough for district-level heatmaps and
# coarse enough to keep data volumes manageable for a prototype.
GRID_RESOLUTION_DEG: float = 0.05   # ~5 km

# ── Sentinel-2 ────────────────────────────────────────────────────────────────
SENTINEL2_COLLECTION = "sentinel-2-l2a"
SENTINEL2_MAX_CLOUD_COVER = 30          # percent
SENTINEL2_LOOKBACK_DAYS = 365           # search 1 year back to find 60 scenes
SENTINEL2_TEMPORAL_STEPS = 60          # number of time steps kept per cell

# Band names as they appear in Planetary Computer STAC items
SENTINEL2_BANDS = {
    "red": "B04",
    "nir": "B08",
    "blue": "B02",
    "green": "B03",
    "swir1": "B11",
    "swir2": "B12",
}

# ── Weather ───────────────────────────────────────────────────────────────────
WEATHER_LOOKBACK_DAYS = 365
WEATHER_FORECAST_DAYS = 7

# Open-Meteo variables (historical archive + forecast)
WEATHER_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
]

# ── Crop calendar (Punjab, indicative dates) ─────────────────────────────────
# These are STATIC configuration values derived from published Punjab
# agricultural calendars (PAU, Punjab Agriculture Dept.).
# Stored as (month_start, day_start, month_end, day_end) tuples.
CROP_CALENDAR: dict = {
    "wheat": {
        "sowing":       (11, 1,  11, 30),
        "vegetative":   (12, 1,   2, 28),
        "reproductive": (3,  1,   4, 15),
        "maturity":     (4, 16,   5, 15),
    },
    "paddy": {
        "sowing":       (6,  1,   6, 30),
        "vegetative":   (7,  1,   8, 31),
        "reproductive": (9,  1,   9, 30),
        "maturity":     (10, 1,  10, 31),
    },
    "cotton": {
        "sowing":       (4,  15,  5, 31),
        "vegetative":   (6,  1,   7, 31),
        "reproductive": (8,  1,   9, 30),
        "maturity":     (10, 1,  11, 15),
    },
}

SUPPORTED_CROPS: List[str] = list(CROP_CALENDAR.keys())

# ── Risk thresholds ───────────────────────────────────────────────────────────
RISK_THRESHOLDS = {
    "LOW":      (0.00, 0.30),
    "MODERATE": (0.30, 0.55),
    "HIGH":     (0.55, 0.75),
    "CRITICAL": (0.75, 1.01),
}

ALERT_RISK_THRESHOLD = 0.55   # trigger email at >= MODERATE/HIGH boundary

# ── Alert deduplication window (hours) ────────────────────────────────────────
ALERT_COOLDOWN_HOURS = 24

# ── ConvLSTM model hyper-parameters ──────────────────────────────────────────
CONVLSTM_CONFIG = {
    "sequence_length": 12,      # time steps fed to the model
    "filters": [32, 16],        # ConvLSTM layer filter counts
    "kernel_size": (3, 3),
    "dropout": 0.2,
    "dense_units": 64,
    "learning_rate": 1e-3,
    "epochs": 80,               # more headroom; early stopping on val_auc
    "batch_size": 4,
    "loss": "binary_crossentropy",
    "optimizer": "adam",
}

# ── FastAPI ───────────────────────────────────────────────────────────────────
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = "dev-secret-key"
    database_url: str = "sqlite:///./cropguard.db"
    admin_token: str = "dev-admin-token"

    # Brevo
    brevo_api_key: str = ""
    brevo_sender_email: str = ""
    brevo_sender_name: str = "CropGuard AI"


settings = Settings()
