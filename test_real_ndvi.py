"""
End-to-end test: download real Sentinel-2 NDVI for Punjab and save to disk.
Run once to verify real data ingestion works before training.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s — %(message)s")

from backend.utils.satellite_ingestor import SatelliteIngestor

print("=== Real Sentinel-2 NDVI Download for Punjab ===\n")

ingestor = SatelliteIngestor()

# Fetch 3 dates from a known clear-sky period over Punjab
ts = ingestor.fetch_ndvi_timeseries(
    start_date="2024-01-01",
    end_date="2024-03-31",
    max_cloud=15,
    max_scenes=3,
)

print(f"\nResults:")
for date, ndvi in sorted(ts.items()):
    print(f"  {date}  shape={ndvi.shape}  mean={ndvi.mean():.4f}  "
          f"min={ndvi.min():.4f}  max={ndvi.max():.4f}")

print(f"\nSaved to: backend/data/geotiff/ndvi_timeseries/")
import os
files = sorted(os.listdir("backend/data/geotiff/ndvi_timeseries/"))
print(f"Files on disk: {files}")
