#!/usr/bin/env python3
"""
CropGuard AI — Complete Pipeline
=================================
Run this script to execute all phases end-to-end:

  Phase 1  — Ingest satellite NDVI (real Sentinel-2 via Planetary Computer,
              or physics-informed synthetic fallback if offline)
  Phase 2  — Ingest weather forecast (real Open-Meteo, or synthetic fallback)
  Phase 3  — Train PestRiskModel      → saved to backend/data/models/risk_model.keras
  Phase 4  — Train PestForecaster     → saved to backend/data/models/forecaster.keras
  Phase 5  — Run inference + save output GeoTIFFs
  Phase 6  — Print district alert summary

Usage
-----
  # Full pipeline (recommended first run)
  python run_complete_pipeline.py

  # Skip satellite download (use whatever NDVI files are already on disk)
  python run_complete_pipeline.py --skip-ingest

  # Use saved model weights — skip training, just run inference
  python run_complete_pipeline.py --skip-training

  # Quick smoke run: fewer tiles, fewer epochs
  python run_complete_pipeline.py --fast
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# ── Silence TF startup noise ─────────────────────────────────────────────────
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import rasterio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cropguard.pipeline")


# ─────────────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="CropGuard AI complete pipeline")
    p.add_argument("--skip-ingest",   action="store_true",
                   help="Skip satellite + weather ingestion")
    p.add_argument("--skip-training", action="store_true",
                   help="Skip model training (use saved weights)")
    p.add_argument("--fast",          action="store_true",
                   help="Quick run: fewer tiles & epochs (for testing)")
    p.add_argument("--scenes",        type=int, default=12,
                   help="Max NDVI scenes to fetch (default: 12)")
    p.add_argument("--epochs-risk",   type=int, default=30,
                   help="Training epochs for PestRiskModel")
    p.add_argument("--epochs-fc",     type=int, default=25,
                   help="Training epochs for PestForecaster")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
def phase1_satellite(args) -> Path:
    """Fetch NDVI time-series. Returns the ndvi_timeseries directory."""
    print("\n" + "─"*60)
    print("PHASE 1 — Satellite NDVI Ingestion")
    print("─"*60)

    from backend.utils.satellite_ingestor import SatelliteIngestor

    ndvi_dir = Path("backend/data/geotiff/ndvi_timeseries")
    existing = sorted(ndvi_dir.glob("ndvi_*.tif"))

    if args.skip_ingest:
        logger.info("--skip-ingest set. Using %d cached NDVI files in %s",
                    len(existing), ndvi_dir)
        if not existing:
            logger.error("No cached NDVI files found! Remove --skip-ingest to fetch data.")
            sys.exit(1)
        return ndvi_dir

    ingestor = SatelliteIngestor()

    # Fetch up to `scenes` cloud-free Sentinel-2 acquisitions over the past year
    end_date   = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

    logger.info("Fetching up to %d NDVI scenes (%s → %s)…",
                args.scenes, start_date, end_date)

    ts = ingestor.fetch_ndvi_timeseries(
        start_date=start_date,
        end_date=end_date,
        max_cloud=20,
        max_scenes=args.scenes,
    )

    files = sorted(ndvi_dir.glob("ndvi_*.tif"))
    logger.info("Phase 1 complete — %d NDVI scenes on disk:", len(files))
    for f in files:
        logger.info("  %s", f.name)

    return ndvi_dir


# ─────────────────────────────────────────────────────────────────────────────
def phase2_weather() -> Path:
    """Fetch weather forecast. Returns the weather CSV path."""
    print("\n" + "─"*60)
    print("PHASE 2 — Weather Ingestion")
    print("─"*60)

    from backend.utils.weather_ingestor import WeatherIngestor

    wx = WeatherIngestor()
    hourly_df, daily_df = wx.get_forecast(days=7)

    csv_path = Path("backend/data/weather/daily_forecast.csv")
    logger.info("Phase 2 complete — %d daily weather rows saved to %s",
                len(daily_df), csv_path)
    return csv_path


# ─────────────────────────────────────────────────────────────────────────────
def phase3_train_risk(ndvi_dir: Path, wx_csv: Path, args):
    """Build and train PestRiskModel. Returns the trained model instance."""
    print("\n" + "─"*60)
    print("PHASE 3 — Train PestRiskModel")
    print("─"*60)

    from backend.models.risk_model import PestRiskModel

    model = PestRiskModel()

    if args.skip_training and model.load():
        logger.info("Loaded saved PestRiskModel — skipping training.")
        return model

    ndvi_files = sorted(ndvi_dir.glob("ndvi_*.tif"))
    if len(ndvi_files) < model.n_time_steps:
        logger.error(
            "PestRiskModel needs at least %d NDVI scenes, found %d in %s.\n"
            "Run Phase 1 first (remove --skip-ingest).",
            model.n_time_steps, len(ndvi_files), ndvi_dir,
        )
        sys.exit(1)

    tiles_per_scene = 10 if args.fast else 40
    epochs          = 5  if args.fast else args.epochs_risk

    logger.info(
        "Training on %d NDVI scenes | tiles_per_scene=%d | epochs=%d",
        len(ndvi_files), tiles_per_scene, epochs,
    )

    model.build()
    model.model.summary(print_fn=logger.info)

    history = model.train(
        ndvi_dir=str(ndvi_dir),
        weather_csv=str(wx_csv) if wx_csv.exists() else "nonexistent.csv",
        tiles_per_scene=tiles_per_scene,
        epochs=epochs,
        batch_size=32,
    )

    best_auc = max(history.get("val_auc", history.get("auc", [0])))
    logger.info("Phase 3 complete — best val AUC: %.4f", best_auc)
    return model


# ─────────────────────────────────────────────────────────────────────────────
def phase4_train_forecaster(ndvi_dir: Path, wx_csv: Path, args):
    """Build and train PestForecaster. Returns the trained forecaster."""
    print("\n" + "─"*60)
    print("PHASE 4 — Train PestForecaster (7-day)")
    print("─"*60)

    from backend.models.forecaster import PestForecaster

    fc = PestForecaster()

    if args.skip_training and fc.load():
        logger.info("Loaded saved PestForecaster — skipping training.")
        return fc

    needed = fc.t_in + fc.t_out  # 12 scenes
    ndvi_files = sorted(ndvi_dir.glob("ndvi_*.tif"))

    if len(ndvi_files) < needed:
        logger.warning(
            "PestForecaster needs %d NDVI scenes, found %d — skipping Phase 4.\n"
            "Fetch more scenes with a longer date range to enable forecaster training.",
            needed, len(ndvi_files),
        )
        fc.build()
        return fc

    tiles_per_window = 5  if args.fast else 30
    epochs           = 3  if args.fast else args.epochs_fc

    logger.info(
        "Training on %d NDVI scenes | tiles_per_window=%d | epochs=%d",
        len(ndvi_files), tiles_per_window, epochs,
    )

    fc.build()
    history = fc.train(
        ndvi_dir=str(ndvi_dir),
        weather_csv=str(wx_csv) if wx_csv.exists() else "nonexistent.csv",
        tiles_per_window=tiles_per_window,
        epochs=epochs,
        batch_size=16,
    )

    best_loss = min(history.get("val_loss", history.get("loss", [999])))
    logger.info("Phase 4 complete — best val loss: %.4f", best_loss)
    return fc


# ─────────────────────────────────────────────────────────────────────────────
def phase5_inference(risk_model, forecaster, ndvi_dir: Path, wx_csv: Path):
    """Run inference → save GeoTIFFs."""
    print("\n" + "─"*60)
    print("PHASE 5 — Inference & GeoTIFF Export")
    print("─"*60)

    from backend.utils.weather_ingestor import WeatherIngestor
    from backend.models.risk_model import PUNJAB_BBOX, GRID_H, GRID_W

    # ── Load NDVI stack ───────────────────────────────────────────────────
    ndvi_tifs = sorted(ndvi_dir.glob("ndvi_*.tif"), reverse=True)
    n = min(len(ndvi_tifs), risk_model.n_time_steps)

    ndvi_arrays = []
    for tif in ndvi_tifs[:n]:
        with rasterio.open(str(tif)) as src:
            ndvi_arrays.append(src.read(1).astype(np.float32))

    H, W = ndvi_arrays[0].shape
    while len(ndvi_arrays) < risk_model.n_time_steps:
        ndvi_arrays.append(ndvi_arrays[-1])

    ndvi_stack = np.stack(ndvi_arrays, axis=-1)  # (H, W, T)

    # ── Weather features ──────────────────────────────────────────────────
    wx = WeatherIngestor()
    wx_features = wx.get_pest_weather_features(target_shape=(H, W), days_ahead=7)

    # ── Risk map ──────────────────────────────────────────────────────────
    doy = datetime.utcnow().timetuple().tm_yday
    logger.info("Running risk assessment (DOY=%d, grid=%dx%d)…", doy, H, W)
    risk_map = risk_model.predict_risk_map(ndvi_stack, wx_features, doy=doy)

    out_risk = "backend/data/geotiff/current_risk_map.tif"
    risk_model.risk_map_to_geotiff(risk_map, out_risk)
    logger.info("Risk map saved → %s  (mean=%.4f, max=%.4f)",
                out_risk, risk_map.mean(), risk_map.max())

    # ── 7-day forecast ────────────────────────────────────────────────────
    risk_history = np.stack([risk_map] * forecaster.t_in, axis=-1)  # (H,W,T_in)
    wx_4 = wx_features[:, :, [0, 3, 5, 6]]  # temp, humidity, wind, vpd
    wx_forecast = np.stack([wx_4] * forecaster.t_out, axis=2)       # (H,W,T_out,4)

    logger.info("Running 7-day forecast…")
    forecast_maps = forecaster.forecast(risk_history, wx_forecast)

    paths = forecaster.save_forecast_geotiffs(
        forecast_maps, "backend/data/geotiff/forecasts"
    )
    logger.info("Phase 5 complete — saved %d forecast GeoTIFFs.", len(paths))

    return risk_map, forecast_maps


# ─────────────────────────────────────────────────────────────────────────────
def phase6_summary(risk_model, risk_map, forecast_maps):
    """Print district alert summary."""
    print("\n" + "─"*60)
    print("PHASE 6 — District Alert Summary")
    print("─"*60)

    from backend.utils.crop_calendar import (
        get_calendar_summary, get_dominant_crop, risk_to_alert_level
    )

    doy = datetime.utcnow().timetuple().tm_yday
    crop = get_dominant_crop(doy)
    calendar = get_calendar_summary(doy)

    print(f"\nDate        : {datetime.utcnow().strftime('%Y-%m-%d')}")
    print(f"DOY         : {doy}")
    print(f"Active crop : {crop.upper()}")
    print(f"Crop stages : ", end="")
    for c, info in calendar.items():
        print(f"{c}={info['stage_name']}", end="  ")
    print()

    # Overall risk stats
    print(f"\nRisk Map Stats:")
    print(f"  Mean risk   : {risk_map.mean():.3f}")
    print(f"  Max risk    : {risk_map.max():.3f}")
    print(f"  P90 risk    : {np.percentile(risk_map, 90):.3f}")
    high_frac = (risk_map > 0.6).mean() * 100
    print(f"  High-risk   : {high_frac:.1f}% of Punjab grid cells")

    # District breakdown
    districts = risk_model.aggregate_district_risk(risk_map)
    print(f"\nDistrict Alerts ({len(districts)} districts):")

    alert_order = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2, "NORMAL": 3}
    sorted_districts = sorted(
        districts.items(), key=lambda x: alert_order.get(x[1]["alert_level"], 4)
    )

    counts = {"CRITICAL": 0, "WARNING": 0, "ADVISORY": 0, "NORMAL": 0}
    for name, info in sorted_districts:
        level = info["alert_level"]
        counts[level] = counts.get(level, 0) + 1
        symbol = {"CRITICAL": "🔴", "WARNING": "🟠", "ADVISORY": "🟡", "NORMAL": "🟢"}.get(level, "⚪")
        print(f"  {symbol} {name:<16} {level:<10}  mean={info['mean_risk']:.3f}  p75={info['p75_risk']:.3f}")

    print(f"\nSummary: CRITICAL={counts['CRITICAL']}  WARNING={counts['WARNING']}  "
          f"ADVISORY={counts['ADVISORY']}  NORMAL={counts['NORMAL']}")

    # 7-day forecast summary
    if forecast_maps is not None:
        print(f"\n7-Day Forecast:")
        for t in range(forecast_maps.shape[0]):
            day_risk = forecast_maps[t]
            date = (datetime.utcnow() + timedelta(days=t+1)).strftime("%Y-%m-%d")
            high = (day_risk > 0.6).mean() * 100
            level = risk_to_alert_level(float(np.percentile(day_risk, 75)), crop)
            symbol = {"CRITICAL": "🔴", "WARNING": "🟠", "ADVISORY": "🟡", "NORMAL": "🟢"}.get(level, "⚪")
            print(f"  Day {t+1} ({date})  {symbol} {level:<10}  "
                  f"mean={day_risk.mean():.3f}  high-risk={high:.1f}%")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    print("=" * 60)
    print("  CropGuard AI — Pest Outbreak Early Warning (Punjab)")
    print("=" * 60)
    print(f"  Mode     : {'FAST (smoke)' if args.fast else 'FULL'}")
    print(f"  Ingest   : {'SKIPPED' if args.skip_ingest else 'ENABLED'}")
    print(f"  Training : {'SKIPPED (load saved)' if args.skip_training else 'ENABLED'}")

    start = datetime.utcnow()

    # Phase 1 — Satellite
    ndvi_dir = phase1_satellite(args)

    # Phase 2 — Weather
    if args.skip_ingest:
        wx_csv = Path("backend/data/weather/daily_forecast.csv")
        logger.info("Using cached weather CSV: %s", wx_csv)
    else:
        wx_csv = phase2_weather()

    # Phase 3 — Risk model
    risk_model = phase3_train_risk(ndvi_dir, wx_csv, args)

    # Phase 4 — Forecaster
    forecaster = phase4_train_forecaster(ndvi_dir, wx_csv, args)

    # Phase 5 — Inference
    risk_map, forecast_maps = phase5_inference(risk_model, forecaster, ndvi_dir, wx_csv)

    # Phase 6 — Summary
    phase6_summary(risk_model, risk_map, forecast_maps)

    elapsed = (datetime.utcnow() - start).total_seconds()
    print("\n" + "=" * 60)
    print(f"  Pipeline complete in {elapsed:.0f}s")
    print("=" * 60)

    print("\nOutputs:")
    print("  backend/data/geotiff/current_risk_map.tif  — today's risk map")
    print("  backend/data/geotiff/forecasts/            — 7-day forecast GeoTIFFs")
    print("  backend/data/models/risk_model.keras       — trained risk model")
    print("  backend/data/models/forecaster.keras       — trained forecaster")
    print("\nTo serve the dashboard:")
    print("  python -m uvicorn backend.main:app --port 8000")
    print("  Then open http://localhost:8000/ui")


if __name__ == "__main__":
    main()
