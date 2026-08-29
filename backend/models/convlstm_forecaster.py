"""
CropGuard AI — ConvLSTM spatiotemporal forecasting model.

Architecture
------------
Input shape  : (batch, T, H, W, F)
               T = sequence_length (12)
               H = grid height
               W = grid width
               F = feature channels (15)

Network:
  ConvLSTM2D(filters=32, kernel=(3,3), padding='same', return_sequences=True)
  → Dropout(0.2)
  → ConvLSTM2D(filters=16, kernel=(3,3), padding='same', return_sequences=False)
  → Dropout(0.2)
  → Conv2D(filters=64, kernel=(1,1), activation='relu')
  → Conv2D(filters=1,  kernel=(1,1), activation='sigmoid')

Output shape : (batch, H, W, 1) — risk probability per grid cell

Loss    : binary_crossentropy
Optimizer: Adam (lr=1e-3)
Metrics : AUC, binary_accuracy

Notes
-----
- The model learns both spatial context (ConvLSTM spatial kernel) and
  temporal dynamics (LSTM recurrence).
- Output is per-cell sigmoid probability, not a classification directly —
  categorical thresholds are applied post-hoc (see config.RISK_THRESHOLDS).
- Batch size is small (4) because the full grid is large.
- Model is saved as .keras format; inference loads it back for prediction.
- For the prototype a single-step forecast is primary.  Multi-step
  forecasting is achieved by rolling the forecast forward (autoregressively
  feeding predictions back as "synthetic" future observations).

Training data classification
-----------------------------
Labels used  → SYNTHETIC (see outbreak_service.py)
Evaluation   → ON SYNTHETIC DATA — not equivalent to real-world validation.
"""

from __future__ import annotations

import logging
import numpy as np
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from backend.config import CONVLSTM_CONFIG, MODELS_DIR

logger = logging.getLogger(__name__)

MODEL_PATH   = MODELS_DIR / "convlstm_model.keras"
HISTORY_PATH = MODELS_DIR / "training_history.npz"


# ── Model construction ────────────────────────────────────────────────────────

def build_model(
    height: int,
    width:  int,
    n_features: int,
    seq_len: int,
    cfg: Dict = CONVLSTM_CONFIG,
) -> Any:
    """
    Build and compile the ConvLSTM model.

    Returns a compiled tf.keras.Model.
    """
    import tensorflow as tf
    from tensorflow.keras import layers, Model, Input

    inp = Input(shape=(seq_len, height, width, n_features), name="feature_sequence")
    x = inp

    # First ConvLSTM block — return full sequence
    x = layers.ConvLSTM2D(
        filters=cfg["filters"][0],
        kernel_size=cfg["kernel_size"],
        padding="same",
        return_sequences=True,
        name="convlstm_1",
    )(x)
    x = layers.Dropout(cfg["dropout"], name="drop_1")(x)

    # Second ConvLSTM block — return last step only
    x = layers.ConvLSTM2D(
        filters=cfg["filters"][1],
        kernel_size=cfg["kernel_size"],
        padding="same",
        return_sequences=False,
        name="convlstm_2",
    )(x)
    x = layers.Dropout(cfg["dropout"], name="drop_2")(x)

    # 1×1 conv bottleneck
    x = layers.Conv2D(
        cfg["dense_units"],
        kernel_size=(1, 1),
        activation="relu",
        padding="same",
        name="bottleneck",
    )(x)

    # Output layer
    out = layers.Conv2D(
        1,
        kernel_size=(1, 1),
        activation="sigmoid",
        padding="same",
        name="risk_output",
    )(x)

    model = Model(inputs=inp, outputs=out, name="CropGuard_ConvLSTM")

    # Use sigmoid focal crossentropy to handle class imbalance better
    # than plain binary_crossentropy
    try:
        loss_fn = tf.keras.losses.BinaryFocalCrossentropy(gamma=2.0, from_logits=False)
    except AttributeError:
        # Older TF versions — fall back to weighted binary crossentropy
        loss_fn = cfg["loss"]

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=cfg["learning_rate"]),
        loss=loss_fn,
        metrics=[
            tf.keras.metrics.AUC(name="auc"),
            tf.keras.metrics.BinaryAccuracy(name="accuracy", threshold=0.3),
            tf.keras.metrics.Precision(name="precision", thresholds=0.3),
            tf.keras.metrics.Recall(name="recall", thresholds=0.3),
        ],
    )
    return model


# ── Training ──────────────────────────────────────────────────────────────────

def train_model(
    X_train: np.ndarray,  # (N, T, H, W, F)
    y_train: np.ndarray,  # (N, H, W, 1)
    X_val:   np.ndarray,
    y_val:   np.ndarray,
    cfg: Dict = CONVLSTM_CONFIG,
    model_path: Path = MODEL_PATH,
) -> Tuple[Any, Dict]:
    """
    Train the ConvLSTM model with early stopping.

    Returns (trained_model, history_dict).
    """
    import tensorflow as tf

    _, seq_len, H, W, F = X_train.shape
    model = build_model(H, W, F, seq_len, cfg)

    logger.info(
        "Training ConvLSTM: input %s → output (%s, %d, %d, 1)",
        X_train.shape, X_train.shape[0], H, W,
    )
    model.summary(print_fn=logger.info)

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_auc",
            mode="max",
            patience=10,
            restore_best_weights=True,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_auc",
            mode="max",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
        ),
    ]

    # Compute per-sample spatial weight maps to handle severe class imbalance.
    # class_weight doesn't work with 4D outputs in Keras; use sample_weight instead.
    y_flat  = y_train.reshape(-1)
    n_pos   = float((y_flat > 0.5).sum())
    n_neg   = float((y_flat <= 0.5).sum())
    n_total = n_pos + n_neg
    w_pos   = n_total / (2.0 * max(n_pos, 1))
    w_neg   = n_total / (2.0 * max(n_neg, 1))
    logger.info(
        "Sample weights — negative: %.3f  positive: %.3f  (imbalance %.1f:1)",
        w_neg, w_pos, n_neg / max(n_pos, 1),
    )
    # sample_weight shape must match output: (N, H, W) — one weight per cell
    sample_weight = np.where(y_train[:, :, :, 0] > 0.5, w_pos, w_neg).astype(np.float32)

    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=cfg["epochs"],
        batch_size=cfg["batch_size"],
        sample_weight=sample_weight,
        callbacks=callbacks,
        verbose=1,
    )

    model.save(model_path)
    logger.info("Model saved → %s", model_path)

    hist_dict = {k: np.array(v) for k, v in history.history.items()}
    np.savez_compressed(HISTORY_PATH, **hist_dict)

    return model, hist_dict


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_model(
    model: Any,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> Dict[str, float]:
    """
    Evaluate on test set.

    IMPORTANT: Test set uses SYNTHETIC labels — metrics reflect the model's
    ability to learn the synthetic rule, NOT real-world outbreak prediction.
    """
    from sklearn.metrics import (
        precision_score, recall_score, f1_score, roc_auc_score
    )

    y_pred_prob = model.predict(X_test, verbose=0)   # (N, H, W, 1)
    y_pred_flat = y_pred_prob.reshape(-1)
    y_true_flat = y_test.reshape(-1)

    y_pred_bin  = (y_pred_flat > 0.5).astype(int)
    y_true_bin  = (y_true_flat > 0.5).astype(int)

    metrics = {
        "precision":   float(precision_score(y_true_bin, y_pred_bin, zero_division=0)),
        "recall":      float(recall_score(y_true_bin, y_pred_bin, zero_division=0)),
        "f1":          float(f1_score(y_true_bin, y_pred_bin, zero_division=0)),
        "roc_auc":     float(roc_auc_score(y_true_bin, y_pred_flat)),
        "data_source": "SYNTHETIC — not real-world validation",
    }
    logger.info("Evaluation (SYNTHETIC labels): %s", metrics)
    return metrics


# ── Inference ─────────────────────────────────────────────────────────────────

def load_model(model_path: Path = MODEL_PATH) -> Optional[Any]:
    """Load a saved Keras model. Returns None if not found."""
    if not model_path.exists():
        logger.warning("Model file not found: %s", model_path)
        return None
    import tensorflow as tf
    model = tf.keras.models.load_model(model_path)
    logger.info("Model loaded from %s", model_path)
    return model


def predict_risk(
    model: Any,
    feature_sequence: np.ndarray,  # (1, T, H, W, F) or (T, H, W, F)
) -> np.ndarray:
    """
    Run inference. Returns (H, W) float32 risk probability map.
    """
    if feature_sequence.ndim == 4:
        feature_sequence = feature_sequence[np.newaxis]  # add batch dim

    pred = model.predict(feature_sequence, verbose=0)  # (1, H, W, 1)
    return pred[0, :, :, 0].astype(np.float32)


def predict_multi_step_risk(
    model: Any,
    last_sequence: np.ndarray,  # (T, H, W, F)
    n_steps: int = 7,
    mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Autoregressive multi-step forecast.

    For each future step:
    1. Predict risk from current sequence window.
    2. Substitute the NDVI channel of the *oldest* step with the new
       risk map (as a proxy for "expected future vegetation state").
    3. Roll the window forward by 1.

    This is an approximation — future weather / crop stage are kept as
    the last known values.  The method is explicitly documented as an
    approximation; true multi-step forecasting would require forecast
    weather data per future step (available from Open-Meteo forecasts).

    Returns (n_steps, H, W) forecast risk tensor.
    """
    seq = last_sequence.copy()   # (T, H, W, F)
    T, H, W, F = seq.shape
    forecasts = np.zeros((n_steps, H, W), dtype=np.float32)

    for step in range(n_steps):
        risk = predict_risk(model, seq)      # (H, W)
        if mask is not None:
            risk = np.where(mask, risk, 0.0)
        forecasts[step] = risk

        # Roll window: drop oldest, append a synthetic "next" step
        new_step = seq[-1].copy()            # copy last step as base
        new_step[:, :, 0] = risk             # channel 0 = NDVI proxy
        seq = np.concatenate([seq[1:], new_step[np.newaxis]], axis=0)

    return forecasts
