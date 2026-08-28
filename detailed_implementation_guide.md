# CropGuard AI: Detailed Implementation & Architecture Guide

This document provides a deep dive into the CropGuard AI codebase, its architecture, and the data pipelines. It is designed to help you understand exactly how the system works under the hood, how the machine learning models are structured, and how the new Punjab-specific features (like prediction overrides) are implemented.

---

## 1. Directory Structure & Execution Flow

### Execution Entry Point (`run_complete_pipeline.py`)
This is the master script that orchestrates the entire system. When you run `python run_complete_pipeline.py`, it executes four distinct phases sequentially:

1. **Phase 1 (Data Ingestion):** Fetches Satellite (NDVI) and Weather data for the target bounding box (now configured for Punjab).
2. **Phase 2 (Pest Detection - Initial State):** Trains a ResNet-50 Convolutional Neural Network (CNN) to detect pests from high-resolution (drone/field) images. This establishes the "Day 0" pest locations.
3. **Phase 3 (Pest Spread Forecasting):** Trains a ConvLSTM (Convolutional Long Short-Term Memory) network. This model takes the Day 0 pest map, weather data, and satellite data to predict how the pests will spread over the next 3 to 7 days.
4. **Phase 4 (Results & Export):** Saves all generated GeoTIFF maps and trained `.h5`/`.keras` model weights to the `backend/data/` directory.

---

## 2. The Data Pipelines

### 2.1 Satellite Ingestion (`backend/utils/satellite_processor.py`)
**Goal:** Track vegetation stress which is a leading indicator of pest damage.
* **Mechanism:** The system fetches multi-spectral imagery (currently configured for Sentinel-2 optical data). It extracts the Red and Near-Infrared (NIR) bands.
* **Calculation:** It computes the Normalized Difference Vegetation Index (NDVI) using the formula: `(NIR - Red) / (NIR + Red)`. A sudden drop in NDVI indicates crop stress.
* **The "Monsoon Blindspot":** For Punjab, the Kharif season (Paddy/Cotton) has heavy cloud cover. While the current script pulls optical data, the architecture is designed so that you can swap or fuse this with Sentinel-1 SAR (Radar) backscatter data, which penetrates clouds, ensuring the model isn't blind during the monsoon.

### 2.2 Weather Ingestion (`backend/utils/weather_processor.py`)
**Goal:** Micro-climate conditions (high humidity, specific temperature ranges) are the primary catalysts for pest breeding (e.g., Whitefly in cotton).
* **Mechanism:** Queries the Open-Meteo API for hourly forecast data (temperature, wind speed, humidity) for the specified coordinates.
* **Spatial Interpolation:** Because weather APIs provide point data or coarse grids, the system maps this data across our high-resolution agricultural bounding box, generating spatial weather layers (saved as GeoTIFFs) so every pixel in the field has assigned weather conditions.

---

## 3. Machine Learning Models

CropGuard uses two distinct AI architectures to solve the problem.

### 3.1 Initial Pest Detection Model (ResNet-50)
* **File:** `backend/models/plant_disease_detector.py`
* **Purpose:** To identify where pests *currently* are.
* **How it works:** It uses a pre-trained ResNet-50 backbone (Transfer Learning). The model looks at RGB images (e.g., from drones or farmer smartphones) and classifies them into different disease/pest categories.
* **Output:** It generates an `initial_pests.tif` heatmap showing the probability of infestation across the grid.

### 3.2 Spatiotemporal Forecaster (ConvLSTM)
* **File:** `backend/models/convlstm_forecaster.py` & `backend/models/risk_model.py`
* **Purpose:** To predict where pests will spread *tomorrow* and *next week*.
* **Why ConvLSTM?** 
  * Standard CNNs are great at spatial data (images).
  * Standard LSTMs are great at temporal data (time-series).
  * **ConvLSTM** combines both. It looks at the spatial map of the farm, but also looks at the timeline (how the weather and NDVI are changing over days).
* **The Fusion Architecture:**
  1. **Temporal Branch:** Looks at the last 8-12 satellite passes (NDVI history) to detect an ongoing downward trend in crop health.
  2. **Context Branch:** Looks at the weather maps and crop calendar (susceptibility).
  3. **Fusion:** It combines these inputs to predict the future state of the `initial_pests` map. If a pixel has high humidity, dropping NDVI, and an infected neighbor, its future risk score skyrockets.

---

## 4. The Punjab Override System

The most critical addition for a real-world deployment in Punjab is the ability for human experts to override the AI. If the Agriculture Department knows there is a severe Whitefly outbreak in a specific village, they must be able to force a "High Risk" alert regardless of what the satellite says.

### 4.1 The SQLite Database (`backend/utils/db_manager.py`)
We implemented a lightweight database with the following schema:
* `lat`, `lon`: The geographic coordinates of the outbreak.
* `width`, `height`: The size of the affected area.
* `override_prediction`: The forced risk score (e.g., `0.95` for Critical).
* `override_suggestion`: Text instructions (e.g., "Spray Neem Oil immediately").

### 4.2 Interception Logic (`backend/main.py`)
In the FastAPI backend, when the `/run-risk-assessment` endpoint is called:
1. The AI model generates the raw `risk_map` matrix.
2. **Before returning**, the code calls `apply_overrides(risk_map, PUNJAB_BBOX, H, W)`.
3. This function converts the database `lat/lon` coordinates into matrix indices (pixels).
4. It surgically overwrites the AI's prediction values with the database's `override_prediction` for those specific pixels.
5. The final, corrected map is then served to the frontend.
