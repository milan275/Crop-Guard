"""Test whether real data sources are reachable."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import requests

print("=== Testing Real Data Sources ===\n")

# 1. Microsoft Planetary Computer STAC
print("[1] Testing Microsoft Planetary Computer STAC...")
try:
    r = requests.get(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        timeout=10
    )
    print(f"    Status: {r.status_code}")
    if r.status_code == 200:
        print("    REACHABLE ✓")
    else:
        print(f"    FAILED: {r.text[:200]}")
except Exception as e:
    print(f"    UNREACHABLE: {e}")

# 2. PC STAC search for Sentinel-2 over Punjab
print("\n[2] Searching Sentinel-2 scenes for Punjab via Planetary Computer...")
try:
    import pystac_client, planetary_computer
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=[73.8, 29.5, 76.9, 32.6],
        datetime="2024-01-01/2024-03-31",
        query={"eo:cloud_cover": {"lt": 20}},
        max_items=5,
    )
    items = list(search.items())
    print(f"    Found {len(items)} scenes")
    for it in items[:3]:
        print(f"      {it.id}  cloud={it.properties.get('eo:cloud_cover','?')}%  date={it.datetime.date()}")
    if items:
        print("    SENTINEL-2 SEARCH OK ✓")
    else:
        print("    No scenes returned (check date range or bbox)")
except Exception as e:
    print(f"    FAILED: {e}")

# 3. Open-Meteo forecast
print("\n[3] Testing Open-Meteo forecast API...")
try:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": 31.1, "longitude": 75.35,
            "daily": "temperature_2m_max,precipitation_sum",
            "forecast_days": 3, "timezone": "Asia/Kolkata"
        },
        timeout=10
    )
    print(f"    Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        temps = data["daily"]["temperature_2m_max"]
        print(f"    Temps next 3 days: {temps}")
        print("    OPEN-METEO OK ✓")
    else:
        print(f"    FAILED: {r.text[:200]}")
except Exception as e:
    print(f"    UNREACHABLE: {e}")

# 4. Open-Meteo ERA5 historical
print("\n[4] Testing Open-Meteo ERA5 historical API...")
try:
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": 31.1, "longitude": 75.35,
            "start_date": "2023-06-01", "end_date": "2023-06-07",
            "daily": "temperature_2m_max,precipitation_sum",
            "timezone": "Asia/Kolkata"
        },
        timeout=10
    )
    print(f"    Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Temps: {data['daily']['temperature_2m_max']}")
        print("    ERA5 HISTORICAL OK ✓")
    else:
        print(f"    FAILED: {r.text[:200]}")
except Exception as e:
    print(f"    UNREACHABLE: {e}")
