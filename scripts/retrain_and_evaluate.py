"""
CropGuard AI — retrain with imbalance fix and print accuracy.
Run from project root:  py scripts/retrain_and_evaluate.py
"""
import warnings, os, sys
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from backend.models.convlstm_forecaster import train_model, evaluate_model, MODEL_PATH
from backend.config import CONVLSTM_CONFIG

# ── Load dataset ──────────────────────────────────────────────────────────────
d = np.load("backend/data/processed/dataset.npz")
X_train, y_train = d["X_train"], d["y_train"]
X_val,   y_val   = d["X_val"],   d["y_val"]
X_test,  y_test  = d["X_test"],  d["y_test"]

print("=" * 55)
print("Dataset summary")
print("=" * 55)
print(f"  Train : {len(X_train):3d} samples  shape={X_train.shape[1:]}")
print(f"  Val   : {len(X_val):3d} samples")
print(f"  Test  : {len(X_test):3d} samples")

for name, y in [("train", y_train), ("val", y_val), ("test", y_test)]:
    flat = y.reshape(-1)
    pos  = int((flat > 0.5).sum())
    pct  = 100.0 * pos / len(flat)
    print(f"  {name:5s} outbreak rate: {pct:.1f}%  ({pos:,} / {len(flat):,} cells)")

print()

# ── Force retrain ─────────────────────────────────────────────────────────────
if MODEL_PATH.exists():
    MODEL_PATH.unlink()
    print("Old model removed. Training from scratch.")

print("Starting training (this will take several minutes)...")
print()

model, history = train_model(X_train, y_train, X_val, y_val)

# ── Training history ──────────────────────────────────────────────────────────
print()
print("=" * 55)
print("Training history (per-epoch summary)")
print("=" * 55)
epochs_run = len(list(history.values())[0])
print(f"  Epochs completed : {epochs_run}")
print()
print(f"  {'Metric':<28} {'Epoch 1':>8}  {'Final':>8}  {'Best':>8}")
print("  " + "-" * 52)
for k in sorted(history.keys()):
    if k == "learning_rate":
        continue
    arr = np.array(history[k])
    best = float(arr.min()) if "loss" in k else float(arr.max())
    label = "(min)" if "loss" in k else "(max)"
    print(f"  {k:<28} {float(arr[0]):8.4f}  {float(arr[-1]):8.4f}  {best:8.4f} {label}")

# ── Test evaluation ───────────────────────────────────────────────────────────
print()
print("=" * 55)
print("Test set evaluation  [SYNTHETIC labels — see note]")
print("=" * 55)
metrics = evaluate_model(model, X_test, y_test)
for k, v in metrics.items():
    if isinstance(v, float):
        print(f"  {k:<20} : {v:.4f}")
    else:
        print(f"  {k:<20} : {v}")

print()
print("NOTE: All metrics are on SYNTHETIC labels.")
print("They measure how well the model learned the simulation rule,")
print("NOT how well it predicts real pest outbreaks.")
print()
print("Model saved to:", MODEL_PATH)
