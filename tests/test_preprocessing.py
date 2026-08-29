"""
CropGuard AI — Tests: feature engineering and preprocessing.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from backend.models.preprocessing import (
    build_feature_tensor,
    impute_nan,
    ChannelScaler,
    build_sequences,
    chronological_split,
    N_FEATURES,
    FEATURE_NAMES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

T, H, W = 12, 10, 8

@pytest.fixture
def dummy_ndvi():
    arr = np.random.rand(T, H, W).astype(np.float32) * 0.8
    arr[2, 3, 4] = np.nan   # introduce some NaN
    return arr

@pytest.fixture
def dummy_weather():
    from backend.config import WEATHER_VARIABLES
    return {v: np.random.rand(T, H, W).astype(np.float32) * 10 for v in WEATHER_VARIABLES}

@pytest.fixture
def dummy_crop():
    return np.zeros((H, W), dtype=np.int8)

@pytest.fixture
def dummy_stage():
    return np.ones((H, W), dtype=np.int8)

@pytest.fixture
def dummy_susceptibility():
    return np.full((H, W), 0.5, dtype=np.float32)

@pytest.fixture
def dummy_labels():
    return (np.random.rand(T, H, W) > 0.7).astype(np.float32)


# ── Feature tensor ────────────────────────────────────────────────────────────

class TestBuildFeatureTensor:
    def test_shape(self, dummy_ndvi, dummy_weather, dummy_crop,
                   dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        )
        assert tensor.shape == (T, H, W, N_FEATURES)

    def test_ndvi_channel(self, dummy_ndvi, dummy_weather, dummy_crop,
                          dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        )
        # Channel 0 is NDVI; non-NaN values should match
        mask = ~np.isnan(dummy_ndvi)
        np.testing.assert_allclose(tensor[:, :, :, 0][mask], dummy_ndvi[mask])

    def test_correct_feature_count(self):
        assert len(FEATURE_NAMES) == N_FEATURES


# ── NaN imputation ────────────────────────────────────────────────────────────

class TestImputation:
    def test_no_nan_after_impute(self, dummy_ndvi, dummy_weather, dummy_crop,
                                  dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        )
        clean = impute_nan(tensor)
        assert not np.isnan(clean).any()

    def test_shape_preserved(self, dummy_ndvi, dummy_weather, dummy_crop,
                              dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        )
        clean = impute_nan(tensor)
        assert clean.shape == tensor.shape


# ── Scaler ────────────────────────────────────────────────────────────────────

class TestChannelScaler:
    def test_fit_transform_shape(self, dummy_ndvi, dummy_weather, dummy_crop,
                                  dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = impute_nan(build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        ))
        scaler = ChannelScaler()
        scaler.fit(tensor)
        norm = scaler.transform(tensor)
        assert norm.shape == tensor.shape

    def test_normalised_mean_near_zero(self, dummy_ndvi, dummy_weather, dummy_crop,
                                        dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = impute_nan(build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        ))
        scaler = ChannelScaler().fit(tensor)
        norm = scaler.transform(tensor)
        channel_means = norm.reshape(-1, N_FEATURES).mean(axis=0)
        assert np.all(np.abs(channel_means) < 0.5)  # roughly zero-centred


# ── Sequence building ─────────────────────────────────────────────────────────

class TestSequenceBuilding:
    def test_output_shape(self, dummy_ndvi, dummy_weather, dummy_crop,
                          dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = impute_nan(build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        ))
        scaler = ChannelScaler().fit(tensor)
        norm = scaler.transform(tensor)
        X, y, actual_seq = build_sequences(norm, dummy_labels, seq_len=4)
        assert X.shape == (T - 4, 4, H, W, N_FEATURES)
        assert y.shape == (T - 4, H, W, 1)
        assert actual_seq == 4

    def test_seq_len_auto_reduced_when_tensor_too_short(self):
        """If T == seq_len the function should auto-reduce to T-1 and not crash."""
        T_short = 5
        norm   = np.random.rand(T_short, H, W, N_FEATURES).astype(np.float32)
        labels = np.random.rand(T_short, H, W).astype(np.float32)
        # Request seq_len equal to T — should auto-reduce to T-1=4
        X, y, actual_seq = build_sequences(norm, labels, seq_len=T_short)
        assert actual_seq == T_short - 1
        assert X.shape[0] == 1   # exactly one sample
        assert X.shape[1] == actual_seq

    def test_chronological_split_no_leakage(self, dummy_ndvi, dummy_weather, dummy_crop,
                                              dummy_stage, dummy_susceptibility, dummy_labels):
        tensor = impute_nan(build_feature_tensor(
            dummy_ndvi, None, dummy_weather,
            dummy_crop, dummy_stage, dummy_susceptibility, dummy_labels,
        ))
        scaler = ChannelScaler().fit(tensor)
        norm = scaler.transform(tensor)
        X, y, _ = build_sequences(norm, dummy_labels, seq_len=4)
        X_tr, y_tr, X_v, y_v, X_te, y_te = chronological_split(X, y)
        assert len(X_tr) + len(X_v) + len(X_te) == len(X)
        assert len(X_tr) > 0
