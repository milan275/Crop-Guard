<#
.SYNOPSIS
    CropGuard AI — staged dependency installer for Windows / Python 3.12+.

.DESCRIPTION
    Installs packages in the correct order to avoid build errors:
      1. Bootstrap setuptools + wheel (fixes "No module named pkg_resources")
      2. Core scientific stack (numpy, scipy) — these must come before geo packages
      3. Geospatial stack (shapely, geopandas, rasterio, pyproj)
         Uses --only-binary :all: to avoid source builds that require C compilers
      4. ML stack (scikit-learn, tensorflow-cpu)
      5. Remaining packages

.USAGE
    # Activate your venv first, then:
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#>

$ErrorActionPreference = "Stop"

function Install($label, $packages, $extra = "") {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    $cmd = "pip install --upgrade $packages $extra"
    Write-Host $cmd -ForegroundColor DarkGray
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $label" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# ── 1. Bootstrap ──────────────────────────────────────────────────────────────
Install "Bootstrap: setuptools + wheel" "setuptools wheel pip"

# ── 2. Core scientific ────────────────────────────────────────────────────────
Install "NumPy + SciPy" "numpy scipy"

# ── 3. Geospatial (pre-built wheels only) ────────────────────────────────────
# shapely, pyproj, fiona, rasterio all publish binary wheels on PyPI.
# --only-binary :all: prevents pip from attempting source builds.
Install "Shapely" "shapely" "--only-binary :all:"
Install "PyProj" "pyproj" "--only-binary :all:"
Install "Fiona" "fiona" "--only-binary :all:"
Install "Rasterio" "rasterio" "--only-binary :all:"
Install "GeoPandas" "geopandas"

# ── 4. ML ─────────────────────────────────────────────────────────────────────
Install "scikit-learn" "scikit-learn"
# tensorflow-cpu avoids CUDA dependency; use 'tensorflow' if you have a GPU
Install "TensorFlow (CPU)" "tensorflow-cpu"

# ── 5. Web + DB ───────────────────────────────────────────────────────────────
Install "FastAPI stack" "fastapi uvicorn[standard] python-multipart python-dotenv pydantic pydantic-settings email-validator"
Install "Database" "sqlalchemy aiosqlite"

# ── 6. Satellite + HTTP ───────────────────────────────────────────────────────
Install "STAC + Planetary Computer" "pystac-client planetary-computer stackstac"
Install "HTTP clients" "httpx requests"

# ── 7. Data + visualisation ───────────────────────────────────────────────────
Install "Data stack" "xarray dask[array] netCDF4 pandas"
Install "Visualisation" "matplotlib pillow"

# ── 8. Utilities ──────────────────────────────────────────────────────────────
Install "Utilities" "tqdm python-dateutil pytz joblib"

# ── 9. Testing ────────────────────────────────────────────────────────────────
Install "Testing" "pytest pytest-asyncio anyio"

Write-Host "`n=== All dependencies installed successfully ===" -ForegroundColor Green
Write-Host "Run the pipeline with:  python run_complete_pipeline.py" -ForegroundColor Yellow
