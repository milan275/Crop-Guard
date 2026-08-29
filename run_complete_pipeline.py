"""
CropGuard AI — Master pipeline script.

Orchestrates the full ML and data pipeline:

  1.  Satellite ingestion       (Microsoft Planetary Computer / Sentinel-2)
  2.  NDVI / EVI computation
  3.  Weather ingestion         (Open-Meteo / ERA5)
  4.  Crop grid preparation     (STATIC district statistics)
  5.  Crop stage grid           (STATIC PAU crop calendar)
  6.  Synthetic outbreak labels (SYNTHETIC — see outbreak_service.py)
  7.  Feature engineering       (15-channel spatiotemporal tensor)
  8.  Dataset construction      (sequences, chronological split)
  9.  ConvLSTM model training
  10. Model evaluation          (NOTE: on SYNTHETIC labels)
  11. Risk map generation       (current + 1d/3d/7d forecast)
  12. GeoJSON export
  13. (Optional) GeoTIFF export

Usage
-----
    python run_complete_pipeline.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
                                    [--skip-satellite] [--skip-weather]
                                    [--skip-training] [--force-retrain]

Arguments
---------
  --start-date     Start of satellite/weather search window (default: 180 days ago)
  --end-date       End of window (default: today)
  --skip-satellite Use cached NDVI stacks if available
  --skip-weather   Use cached weather if available
  --skip-training  Skip training; load existing model for inference only
  --force-retrain  Force retrain even if model exists

Data classification reminder
-----------------------------
  Sentinel-2 NDVI/EVI  → DERIVED REAL
  Weather (Open-Meteo) → REAL
  Crop grid            → STATIC
  Crop stage           → STATIC
  Outbreak labels      → SYNTHETIC
  Model training       → on SYNTHETIC labels
  Evaluation metrics   → on SYNTHETIC data (NOT real-world validation)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent))

from backend.config import (
    PROCESSED_DIR,
    OUTPUTS_DIR,
    SENTINEL2_TEMPORAL_STEPS,
    CONVLSTM_CONFIG,
)
from backend.utils.geo import get_cached_grid
from backend.utils.grid import save_risk_map, try_export_geotiff

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def parse_args():
    p = argparse.ArgumentParser(description="CropGuard AI — full pipeline")
    p.add_argument("--start-date",      default=None)
    p.add_argument("--end-date",        default=None)
    p.add_argument("--skip-satellite",  action="store_true")
    p.add_argument("--skip-weather",    action="store_true")
    p.add_argument("--skip-training",   action="store_true")
    p.add_argument("--force-retrain",   action="store_true")
    return p.parse_args()


def step1_satellite(args) -> dict:
    logger.info("═" * 60)
    logger.info("STEP 1-2  Sentinel-2 ingestion + NDVI/EVI")
    logger.info("═" * 60)

    ndvi_cache = PROCESSED_DIR / "ndvi_stack.npz"
    if args.skip_satellite and ndvi_cache.exists():
        logger.info("Skipping download — using cached NDVI stack.")
        data = np.load(ndvi_cache)
        return {"ndvi_stack": data["ndvi_stack"], "evi_stack": data.get("evi_stack"),
                "timestamps": list(data["timestamps"]), "scene_count": int(data.get("scene_count", 0))}

    from backend.services.satellite_service import ingest_sentinel2
    result = ingest_sentinel2(start_date=args.start_date, end_date=args.end_date)

    # Cache
    save_dict = {"ndvi_stack": result["ndvi_stack"], "timestamps": np.array(result["timestamps"])}
    if result["evi_stack"] is not None:
        save_dict["evi_stack"] = result["evi_stack"]
    save_dict["scene_count"] = np.array(result["scene_count"])
    np.savez_compressed(ndvi_cache, **save_dict)
    logger.info("NDVI stack cached → %s", ndvi_cache)

    return result


def step3_weather(args, n_steps: int) -> dict:
    logger.info("═" * 60)
    logger.info("STEP 3  Weather ingestion (Open-Meteo / ERA5-backed)")
    logger.info("DATA SOURCE: Open-Meteo  |  CLASSIFICATION: REAL")
    logger.info("═" * 60)

    weather_cache = PROCESSED_DIR / "weather_data.npz"
    if args.skip_weather and weather_cache.exists():
        logger.info("Skipping download — using cached weather data.")
        data = np.load(weather_cache, allow_pickle=True)
        return {k: data[k] for k in data.files}

    from backend.services.weather_service import ingest_weather_historical
    result = ingest_weather_historical(
        start_date=args.start_date,
        end_date=args.end_date,
        n_steps=n_steps,
    )

    save_dict = {k: v for k, v in result.items() if isinstance(v, np.ndarray)}
    save_dict["dates"] = np.array(result.get("dates", []))
    np.savez_compressed(weather_cache, **save_dict)
    logger.info("Weather data cached → %s", weather_cache)
    return result


def step4_crop(n_steps: int) -> tuple:
    logger.info("═" * 60)
    logger.info("STEP 4  Crop grid + stage  |  CLASSIFICATION: STATIC")
    logger.info("═" * 60)

    from backend.services.crop_service import get_crop_grid, get_crop_stage_grid
    from datetime import date

    crop_grid = get_crop_grid()
    stage_grid, susceptibility_grid = get_crop_stage_grid()

    # Broadcast to temporal dimension
    crop_stack  = np.stack([crop_grid]  * n_steps, axis=0)
    stage_stack = np.stack([stage_grid] * n_steps, axis=0)
    susc_stack  = np.stack([susceptibility_grid] * n_steps, axis=0)

    logger.info("Crop grid shape: %s", crop_grid.shape)
    unique, counts = np.unique(crop_grid, return_counts=True)
    crop_names = {0: "wheat", 1: "paddy", 2: "cotton"}
    for u, c in zip(unique, counts):
        logger.info("  %s: %d cells", crop_names.get(int(u), "?"), c)

    return crop_stack, stage_stack, susc_stack


def step5_outbreak_labels(ndvi_stack, temp_stack, humid_stack, susc_stack, crop_stack) -> np.ndarray:
    logger.info("═" * 60)
    logger.info("STEP 5  Outbreak labels  |  CLASSIFICATION: SYNTHETIC")
    logger.info("WARNING: Synthetic labels — evaluation is NOT real-world validation.")
    logger.info("═" * 60)

    from backend.services.outbreak_service import load_or_generate_outbreak_labels

    grid = get_cached_grid()
    labels = load_or_generate_outbreak_labels(
        ndvi_stack=ndvi_stack,
        temp_stack=temp_stack,
        humid_stack=humid_stack,
        susceptibility_stack=susc_stack,
        crop_stack=crop_stack,
    )
    logger.info("Label shape: %s  |  Mean probability: %.3f", labels.shape, labels.mean())
    return labels


def step6_preprocessing(ndvi_stack, evi_stack, weather_data, crop_stack,
                         stage_stack, susc_stack, outbreak_labels):
    logger.info("═" * 60)
    logger.info("STEP 6  Feature engineering + dataset construction")
    logger.info("═" * 60)

    from backend.models.preprocessing import run_preprocessing

    result = run_preprocessing(
        ndvi_stack=ndvi_stack,
        evi_stack=evi_stack,
        weather_data=weather_data,
        crop_grid=crop_stack[0],
        stage_grid=stage_stack[0],
        susceptibility_grid=susc_stack[0],
        outbreak_labels=outbreak_labels,
        seq_len=CONVLSTM_CONFIG["sequence_length"],
    )

    # Save normalised tensor for inference
    tensor_path = PROCESSED_DIR / "latest_tensor.npz"
    np.savez_compressed(tensor_path, tensor=result["feature_tensor_norm"])
    logger.info("Normalised tensor saved → %s", tensor_path)

    logger.info(
        "Dataset: X_train=%s  X_val=%s  X_test=%s",
        result["X_train"].shape, result["X_val"].shape, result["X_test"].shape,
    )
    return result


def step7_train(dataset, args):
    logger.info("═" * 60)
    logger.info("STEP 7  ConvLSTM training")
    logger.info("═" * 60)

    from backend.models.convlstm_forecaster import MODEL_PATH, load_model, train_model

    if args.skip_training:
        logger.info("--skip-training flag set. Loading existing model.")
        return load_model()

    if MODEL_PATH.exists() and not args.force_retrain:
        logger.info("Model already exists at %s. Use --force-retrain to overwrite.", MODEL_PATH)
        return load_model()

    # Use the actual seq_len determined during preprocessing (may be < config default)
    actual_seq_len = dataset.get("seq_len", CONVLSTM_CONFIG["sequence_length"])
    cfg = {**CONVLSTM_CONFIG, "sequence_length": actual_seq_len}
    logger.info("Training with seq_len=%d", actual_seq_len)

    model, history = train_model(
        X_train=dataset["X_train"],
        y_train=dataset["y_train"],
        X_val=dataset["X_val"],
        y_val=dataset["y_val"],
        cfg=cfg,
    )
    return model


def step8_evaluate(model, dataset):
    logger.info("═" * 60)
    logger.info("STEP 8  Model evaluation  |  NOTE: SYNTHETIC labels")
    logger.info("═" * 60)

    if model is None:
        logger.warning("No model available — skipping evaluation.")
        return

    from backend.models.convlstm_forecaster import evaluate_model
    metrics = evaluate_model(model, dataset["X_test"], dataset["y_test"])

    logger.info("Evaluation results (SYNTHETIC — not real-world):")
    for k, v in metrics.items():
        logger.info("  %-20s : %s", k, v)


def step9_risk_maps(model, dataset):
    logger.info("═" * 60)
    logger.info("STEP 9  Risk map generation and export")
    logger.info("═" * 60)

    if model is None:
        logger.warning("No model — generating placeholder risk maps.")
        grid = get_cached_grid()
        H, W = grid["height"], grid["width"]
        mask = grid["mask"]
        # Placeholder: uniform low risk
        risk_map = np.where(mask, 0.15, 0.0).astype(np.float32)
    else:
        from backend.models.convlstm_forecaster import predict_risk, predict_multi_step_risk

        tensor = np.load(PROCESSED_DIR / "latest_tensor.npz")["tensor"]
        seq_len = dataset.get("seq_len", CONVLSTM_CONFIG["sequence_length"])
        seq_len = min(seq_len, tensor.shape[0])
        seq = tensor[-seq_len:]   # (seq_len, H, W, F)

        grid = get_cached_grid()
        mask = grid["mask"]

        risk_map = predict_risk(model, seq)
        risk_map = np.where(mask, risk_map, 0.0)

    now = datetime.utcnow().isoformat()

    # Save current risk
    save_risk_map(risk_map, now, "current")
    np.savez_compressed(OUTPUTS_DIR / "risk_latest_0d.npz",
                        risk_map=risk_map, timestamp=np.bytes_(now))

    if model is not None:
        from backend.models.convlstm_forecaster import predict_multi_step_risk
        tensor = np.load(PROCESSED_DIR / "latest_tensor.npz")["tensor"]
        seq_len = dataset.get("seq_len", CONVLSTM_CONFIG["sequence_length"])
        seq_len = min(seq_len, tensor.shape[0])
        seq = tensor[-seq_len:]
        forecasts = predict_multi_step_risk(model, seq, n_steps=7, mask=mask)

        for day in [1, 3, 7]:
            fm = np.where(mask, forecasts[day - 1], 0.0)
            save_risk_map(fm, now, f"{day}d")
            np.savez_compressed(OUTPUTS_DIR / f"risk_latest_{day}d.npz",
                                risk_map=fm, timestamp=np.bytes_(now))

    # Optional GeoTIFF
    tiff_path = OUTPUTS_DIR / "risk_current.tif"
    try_export_geotiff(risk_map, tiff_path)

    logger.info(
        "Risk map generated. Mean risk: %.3f  |  Max risk: %.3f",
        float(risk_map[risk_map > 0].mean()) if (risk_map > 0).any() else 0.0,
        float(risk_map.max()),
    )
    return risk_map


def main():
    args = parse_args()
    logger.info("CropGuard AI — Complete Pipeline")
    logger.info("Start: %s  |  End: %s",
                args.start_date or "auto (180d ago)",
                args.end_date   or "auto (today)")

    n_steps = SENTINEL2_TEMPORAL_STEPS

    # Steps 1-2: Satellite
    satellite = step1_satellite(args)
    ndvi_stack = satellite["ndvi_stack"]
    evi_stack  = satellite.get("evi_stack")
    logger.info("Scenes processed: %d", satellite.get("scene_count", 0))

    # Step 3: Weather
    weather_data = step3_weather(args, n_steps)
    temp_stack   = weather_data.get("temperature_2m_max",
                       np.full_like(ndvi_stack, 25.0))
    humid_stack  = weather_data.get("relative_humidity_2m_max",
                       np.full_like(ndvi_stack, 65.0))

    # Step 4: Crop
    crop_stack, stage_stack, susc_stack = step4_crop(n_steps)

    # Step 5: Outbreak labels (SYNTHETIC)
    outbreak_labels = step5_outbreak_labels(
        ndvi_stack, temp_stack, humid_stack, susc_stack, crop_stack)

    # Step 6: Feature engineering
    dataset = step6_preprocessing(
        ndvi_stack, evi_stack, weather_data,
        crop_stack, stage_stack, susc_stack, outbreak_labels,
    )

    # Step 7: Training
    model = step7_train(dataset, args)

    # Step 8: Evaluation
    step8_evaluate(model, dataset)

    # Step 9: Risk maps
    risk_map = step9_risk_maps(model, dataset)

    logger.info("═" * 60)
    logger.info("Pipeline complete.")
    logger.info("Risk maps saved to: %s", OUTPUTS_DIR)
    logger.info("Start the FastAPI backend with:")
    logger.info("  uvicorn backend.main:app --reload")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
