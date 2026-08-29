@echo off
REM CropGuard AI — staged dependency installer (Windows batch fallback)
REM Activate your venv first, then run this script.

echo.
echo === Step 1: Bootstrap setuptools + wheel ===
pip install --upgrade setuptools wheel pip
if errorlevel 1 goto :error

echo.
echo === Step 2: NumPy + SciPy ===
pip install --upgrade numpy scipy
if errorlevel 1 goto :error

echo.
echo === Step 3: Geospatial (pre-built wheels only) ===
pip install --upgrade shapely --only-binary :all:
if errorlevel 1 goto :error
pip install --upgrade pyproj --only-binary :all:
if errorlevel 1 goto :error
pip install --upgrade fiona --only-binary :all:
if errorlevel 1 goto :error
pip install --upgrade rasterio --only-binary :all:
if errorlevel 1 goto :error
pip install --upgrade geopandas
if errorlevel 1 goto :error

echo.
echo === Step 4: ML stack ===
pip install --upgrade scikit-learn
if errorlevel 1 goto :error
pip install --upgrade tensorflow-cpu
if errorlevel 1 goto :error

echo.
echo === Step 5: Web + Database ===
pip install --upgrade fastapi "uvicorn[standard]" python-multipart python-dotenv pydantic pydantic-settings email-validator
if errorlevel 1 goto :error
pip install --upgrade sqlalchemy aiosqlite
if errorlevel 1 goto :error

echo.
echo === Step 6: Satellite + HTTP ===
pip install --upgrade pystac-client planetary-computer stackstac httpx requests
if errorlevel 1 goto :error

echo.
echo === Step 7: Data + Visualisation ===
pip install --upgrade xarray "dask[array]" netCDF4 pandas matplotlib pillow
if errorlevel 1 goto :error

echo.
echo === Step 8: Utilities ===
pip install --upgrade tqdm python-dateutil pytz joblib
if errorlevel 1 goto :error

echo.
echo === Step 9: Testing ===
pip install --upgrade pytest pytest-asyncio anyio
if errorlevel 1 goto :error

echo.
echo === All dependencies installed successfully ===
echo Run: python run_complete_pipeline.py
goto :end

:error
echo.
echo INSTALLATION FAILED at the step above.
echo See error message for details.
exit /b 1

:end
