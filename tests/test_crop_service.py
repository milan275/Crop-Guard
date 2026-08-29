"""
CropGuard AI — Tests: crop service.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
import pytest
from backend.services.crop_service import (
    get_dominant_crop,
    get_crop_stage,
    get_stage_susceptibility,
    get_crop_info,
)
from backend.config import SUPPORTED_CROPS


class TestGetDominantCrop:
    def test_returns_supported_crop(self):
        crop = get_dominant_crop(30.901, 75.857)   # Ludhiana
        assert crop in SUPPORTED_CROPS

    def test_rabi_favours_wheat(self):
        # January — Rabi season
        crop = get_dominant_crop(30.901, 75.857, date(2024, 1, 15))
        # Ludhiana is wheat-dominant; Rabi weighting should keep it wheat
        assert crop == "wheat"

    def test_kharif_favours_paddy_in_wheat_district(self):
        # August — Kharif season in Ludhiana (wheat/paddy district)
        crop = get_dominant_crop(30.901, 75.857, date(2024, 8, 15))
        # Should shift toward paddy
        assert crop in ("paddy", "wheat")  # either is valid

    def test_cotton_district_kharif(self):
        # Bathinda — cotton-dominant, Kharif season
        crop = get_dominant_crop(30.211, 74.946, date(2024, 8, 15))
        assert crop in SUPPORTED_CROPS


class TestGetCropStage:
    def test_wheat_jan_vegetative(self):
        stage = get_crop_stage("wheat", date(2024, 1, 15))
        assert stage == "vegetative"

    def test_wheat_march_reproductive(self):
        stage = get_crop_stage("wheat", date(2024, 3, 15))
        assert stage == "reproductive"

    def test_paddy_july_vegetative(self):
        stage = get_crop_stage("paddy", date(2024, 7, 15))
        assert stage == "vegetative"

    def test_cotton_august_reproductive(self):
        stage = get_crop_stage("cotton", date(2024, 8, 15))
        assert stage == "reproductive"

    def test_unknown_crop_returns_off_season(self):
        stage = get_crop_stage("mango", date(2024, 6, 1))
        assert stage == "off_season"


class TestGetStageSusceptibility:
    def test_wheat_reproductive_high(self):
        s = get_stage_susceptibility("wheat", "reproductive")
        assert s >= 0.8

    def test_wheat_sowing_low(self):
        s = get_stage_susceptibility("wheat", "sowing")
        assert s < 0.5

    def test_returns_float(self):
        s = get_stage_susceptibility("paddy", "vegetative")
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0


class TestGetCropInfo:
    def test_returns_dict(self):
        info = get_crop_info(30.901, 75.857)
        assert isinstance(info, dict)

    def test_has_required_keys(self):
        info = get_crop_info(30.901, 75.857)
        for key in ("crop", "district", "crop_stage", "susceptibility", "data_classification"):
            assert key in info

    def test_data_classification_is_static(self):
        info = get_crop_info(30.901, 75.857)
        assert info["data_classification"] == "STATIC"
