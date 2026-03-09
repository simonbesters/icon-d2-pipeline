"""GeoTIFF writer for RASP output.

Simpler than the WRF version (rasp2geotiff.py) because ICON-D2 is already
on a regular lat-lon grid, so no LCC intermediate projection is needed.

Output format:
- Source: EPSG:4326 (regular lat-lon)
- Target: EPSG:3857 (Web Mercator) via gdal.Warp
- Data type: Int32
- NoData: -999999
- Compression: DEFLATE with PREDICTOR=2
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False
    logger.warning("GDAL not available — GeoTIFF output disabled")


def write_geotiff(filepath: Path, data: np.ndarray,
                  lat: np.ndarray, lon: np.ndarray) -> None:
    """Write a GeoTIFF file from a 2D array on a regular lat-lon grid.

    Args:
        filepath: Output .tiff file path.
        data: 2D numpy array (lat, lon). Will be rounded to integers.
        lat: 1D latitude array.
        lon: 1D longitude array.
    """
    if not HAS_GDAL:
        logger.debug(f"Skipping GeoTIFF (no GDAL): {filepath.name}")
        return

    ny, nx = data.shape
    assert ny == len(lat), f"lat mismatch: {ny} != {len(lat)}"
    assert nx == len(lon), f"lon mismatch: {nx} != {len(lon)}"

    # Handle NaN/inf
    clean_data = np.where(np.isfinite(data), np.round(data), -999999).astype(np.int32)

    # Build GeoTransform for source (EPSG:4326)
    dlon = float(lon[1] - lon[0])
    dlat = float(lat[1] - lat[0])  # Negative if lat is N->S (decreasing)

    # GeoTransform: (x_min - dx/2, dx, 0, y_max + dy/2, 0, -dy)
    # If lat is decreasing (N->S), first lat is the top
    x_origin = float(lon[0]) - dlon / 2.0
    y_origin = float(lat[0]) - dlat / 2.0

    gt = (x_origin, dlon, 0.0, y_origin, 0.0, dlat)

    # Create in-memory raster
    mem_driver = gdal.GetDriverByName("MEM")
    src_ds = mem_driver.Create("", nx, ny, 1, gdal.GDT_Int32)
    src_ds.SetGeoTransform(gt)

    # Set source SRS to EPSG:4326
    src_srs = osr.SpatialReference()
    src_srs.ImportFromEPSG(4326)
    src_ds.SetProjection(src_srs.ExportToWkt())

    band = src_ds.GetRasterBand(1)
    band.WriteArray(clean_data)
    band.SetNoDataValue(-999999)

    # Warp to EPSG:3857 (Web Mercator)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    gdal.Warp(
        str(filepath),
        src_ds,
        dstSRS="EPSG:3857",
        format="GTiff",
        resampleAlg="cubicspline",
        xRes=abs(dlon),
        yRes=abs(dlat),
        creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=2"],
    )

    src_ds = None
    logger.debug(f"Wrote {filepath.name}")


def convert_data_files_to_geotiff(out_dir: Path, lat: np.ndarray,
                                  lon: np.ndarray) -> None:
    """Convert all .data files in a directory to GeoTIFF.

    This is a batch operation similar to rasp2geotiff.py.

    Args:
        out_dir: Directory containing .data files.
        lat: 1D latitude array for the domain.
        lon: 1D longitude array for the domain.
    """
    data_files = sorted(out_dir.glob("*.data"))
    for data_file in data_files:
        tiff_file = data_file.with_suffix(".data.tiff")
        if tiff_file.exists():
            continue

        try:
            # Read data file (skip 4-line header)
            raw = np.loadtxt(data_file, skiprows=4)
            if raw.ndim != 2:
                logger.warning(f"Skipping {data_file.name}: not 2D data")
                continue

            write_geotiff(tiff_file, raw, lat, lon)
        except Exception as e:
            logger.warning(f"Could not convert {data_file.name}: {e}")
