# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ICON-D2 Soaring Weather Pipeline — downloads ICON-D2 NWP model data from DWD (German Weather Service), computes 30+ soaring/gliding meteorological parameters, and outputs RASP-format files for blipmaps.nl. Targets the Netherlands region (49°–54.5°N, 2°–12°E).

## Commands

### Run
```bash
# Via Docker (production)
./run.sh              # Today, 0Z init
./run.sh 6            # Today, 6Z init
START_DAY=1 ./run.sh  # Tomorrow

# Via Python directly
python -m icon_d2_pipeline
```

### Build
```bash
docker build -t icond2-pipeline:latest .
```

### Test
```bash
python test_pipeline_e2e.py   # E2E test (downloads real GRIB data)
```

### Upload results
```bash
./upload.sh /tmp/results/<run_dir>
```

## Environment Variables

`START_DAY` (default 0), `OFFSET_HOUR` (init hour UTC, default 0), `TZ_OFFSET` (auto-detected), `GRIB_DIR` (default /tmp/icon_d2_grib), `RESULTS_DIR` (default /tmp/results), `LOG_LEVEL` (default INFO), `UPLOAD_TARGET` (scp target), `SSH_KEY`.

## Architecture

**Data flow:** `run.py` → `pipeline.run_pipeline()` → download → load grid/invariants → process timesteps → write output

### Pipeline stages (pipeline.py)
1. **Download** (`download.py`): Async aiohttp fetches of GRIB2 files from DWD, bz2 decompression. Three data types: 3D model-level (icosahedral), 3D pressure-level (regular), 2D single-level (regular), plus time-invariant fields.
2. **Grid setup** (`grid.py`, `remap.py`): Extracts regular lat-lon grid, builds scipy cKDTree remapper (4-neighbor IDW) for icosahedral→regular grid conversion.
3. **Timestep loop**: 22 half-hourly steps (07:30–18:00 local). Hourly GRIB data is cached (max 2 hours in memory); half-hour values are linearly interpolated. 3D icosahedral remapping is parallelized via ProcessPoolExecutor.
4. **Calculations** (`calc/`): thermal.py, boundary_layer.py, cloud.py, cape.py, pfd.py, surface.py, pressure.py, derived.py, wind.py.
5. **Output** (`output/`): RASP .data files (data_file.py), GeoTIFF (geotiff.py), JSON metadata (json_meta.py), meteograms (meteogram.py).

### Key design decisions
- **ProcessPoolExecutor** for 3D GRIB loading/remapping to bypass GIL — created once before the timestep loop, remapper weights shared via process initializer, paths passed as strings (not Path objects) to avoid pickle issues. Heights (`z_full`) are pre-flipped to bottom-up once before the loop.
- **Icosahedral remapping** uses scipy cKDTree with inverse-distance weighting (4 neighbors).
- **RASP .data format** is a legacy integer-grid format for XCSoar compatibility (4-line header + scaled integer values). Written via `np.savetxt`.
- **GeoTIFF output** warps from EPSG:4326 to EPSG:3857 via `gdal.Warp` — resolution is auto-computed from the source grid (not specified explicitly, since target CRS uses meters).
- **PFD calculations**: `pfd_tot` uses hardcoded NCL polar coefficients (`PFD_SIMPLE_A/B/C/SRIT` in config.py), NOT glider polar-derived values. `pfd_tot2`/`pfd_tot3` use glider polars with wing-loading.
- **Missing data** defaults to NaN (not zero) so it maps to -999999 in output files.
- **Clear-sky model** (`sfcsunpct`) uses Kasten (1980) formula with precipitable water from the qvapor column.
- **LCL** (`zsfclcl`) computed via parcel lifting with conserved mixing ratio; Espy formula as fallback.
- **BL cloud cover** (`blcloudpct`) uses RH-based sub-grid cloud fraction scheme (`cf = max(0, (RH - 0.80)/0.20)^2`).
- **wstar** uses BL-averaged temperature from the 3D T field (falls back to 300K if unavailable).
- All configuration constants (domain bbox, model levels, glider polars, parameter lists) live in `config.py`.

## Dependencies

Python: numpy, eccodes, cfgrib, aiohttp, scipy, matplotlib, certifi. System: libgdal-dev, libeccodes-dev (see Dockerfile for full setup).