import os
import sys
import numpy as np
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

sys.path.append('backend')
from models.plant_disease_detector import PlantDiseaseDetector
from models.convlstm_forecaster import PestSpreadForecaster
from models.risk_model import PestRiskModel

print("--- EVALUATING CURRENT MODELS ---")

# Evaluate ResNet (Disease Detector)
try:
    print("\n1. Evaluating ResNet (Plant Disease Detector)...")
    detector = PlantDiseaseDetector()
    detector.create_synthetic_training_data(num_samples=100) # smaller for quick test
    
    # Load model weights if exists
    if os.path.exists("backend/data/models/disease_detector.keras"):
        detector.build_resnet_model()
        detector.model.load_weights("backend/data/models/disease_detector.keras")
        loss, accuracy = detector.model.evaluate(detector.val_generator, verbose=0)
        print(f"Current Accuracy: {accuracy*100:.2f}%")
    else:
        print("Model file not found. Could not evaluate.")
except Exception as e:
    print(f"Error evaluating ResNet: {e}")

# Evaluate ConvLSTM (Risk Model)
try:
    print("\n2. Evaluating ConvLSTM (Pest Spread Forecaster)...")
    forecaster = PestSpreadForecaster()
    X_test, y_test = forecaster.create_synthetic_pest_spread_data(
        num_sequences=100, sequence_length=10, grid_size=64
    )
    
    risk_model = PestRiskModel()
    if risk_model.load("backend/data/models/risk_model.keras"):
        results = risk_model.model.evaluate([X_test, y_test[..., 0:31]], y_test[..., -1:], verbose=0)
        # Results metrics order depends on compile config. Generally: loss, auc, precision, recall
        # We just grab the first metric after loss which is auc here.
        if len(results) > 1:
            auc = results[1]
            print(f"Current AUC Score: {auc:.4f} (equivalent to ~{auc*100:.1f}% ROC accuracy)")
        else:
            print(f"Evaluation Loss: {results[0]:.4f}")
    else:
        print("Risk model not found.")
except Exception as e:
    print(f"Error evaluating ConvLSTM: {e}")
