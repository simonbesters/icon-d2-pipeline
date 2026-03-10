# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ICON-D2 soaring weather forecast pipeline for [blipmaps.nl](https://blipmaps.nl). Downloads GRIB meteorological data from Germany's DWD open data server, computes 37 soaring/gliding weather parameters across 22 half-hourly timesteps (7:30–18:00 local), and outputs RASP .data files, GeoTIFF, and JSON metadata.

## Running

```bash
# Via Docker (production)
./run.sh [OFFSET_HOUR] [START_DAY]    # e.g. ./run.sh 0 6

# Direct CLI
python -m icon_d2_pipeline            # or: python -m icon_d2_pipeline.run

# Upload results
./upload.sh /tmp/results/RUN_DIR      # requires UPLOAD_TARGET env var
```

**Environment variables:** `START_DAY` (forecast day offset, default 0), `OFFSET_HOUR` (model init UTC hour, default 0), `TZ_OFFSET` (UTC offset, auto-detected), `RESULTS_DIR` (/tmp/results), `GRIB_DIR` (/tmp/icon_d2_grib), `LOG_LEVEL` (INFO), `REGION` (NL2KMICOND2).

## Testing

```bash
python -m pytest test_pipeline_e2e.py -v
```

The e2e test downloads real ICON-D2 data and runs a single timestep through the full pipeline (download → remap → calculate → output).

## Build

```bash
docker build -t icon-d2-pipeline .
```

Requires system-level GDAL and eccodes libraries (handled by Dockerfile). Python deps in `requirements.txt`.

## Architecture

### Pipeline flow (pipeline.py:run_pipeline)

1. **Download** — Async HTTP (aiohttp) parallel download of GRIB files from DWD. Requires 80% success rate. Variables include 3D model-level (T, QV, QC, P, U, V, W on icosahedral grid), pressure-level (FI, RELHUM, OMEGA on regular grid), and 2D single-level fields.
2. **Load & Prepare** — Load terrain/heights/grid coords, initialize `IconRemapper` (scipy cKDTree, K=4 IDW interpolation) for icosahedral→regular lat-lon conversion, subset to domain bounding box.
3. **Process timesteps** — For each of 22 timesteps: load/interpolate GRIB data, compute all parameters via `calc/` modules, write output files. Cache eviction keeps max 2 hourly datasets in memory.
4. **PFD** — After all timesteps, compute Potential Flight Distance by reading back .data files.

### Key modules

- **pipeline.py** — Main orchestrator (run_pipeline, process_timestep, load/interpolate logic)
- **config.py** — Domain bbox (49–54.5°N, 2–12°E), model level counts (65 full, 66 half), glider polars (LS-4, ASG-29E), output parameter definitions with units/scales
- **download.py** — Async GRIB download with URL construction for DWD server
- **fields.py** — GRIB reading via eccodes, field indexing
- **grid.py** — Domain subsetting, bounding box operations
- **remap.py** — Icosahedral-to-regular grid remapping (level-by-level to avoid OOM)
- **calc/** — Scientific computations: thermal.py (w*, hcrit), boundary_layer.py (BL wind/variability), cloud.py (cloud base/coverage), derived.py (hbl, bsratio), surface.py, wind.py, pressure.py, cape.py, pfd.py
- **output/** — Writers: data_file.py (RASP .data format), geotiff.py, json_meta.py, meteogram.py

### Data formats

- **RASP .data**: 4-line text header + space-separated integer grid. Values multiplied by unit factors (e.g., ×100 for wstar in cm/s). Filename pattern: `{param}.curr.{HHMM}lst.d2.data`
- **GeoTIFF**: Georeferenced raster
- **JSON metadata**: Parameter info, color scales, valid times

### Memory considerations

The pipeline processes large 3D atmospheric grids. Key OOM mitigations:
- Level-by-level icosahedral remapping (not all levels at once)
- Cache eviction after processing each timestep (keeps max 2 hours)
- Half-level W field interpolation to full levels
