"""Grid handling and domain subsetting for ICON-D2 regular lat-lon grid."""

import numpy as np

from .config import NL_BBOX


def find_bbox_indices(lat: np.ndarray, lon: np.ndarray,
                      bbox: dict | None = None) -> tuple[slice, slice]:
    """Find array index slices for the NL domain bounding box.

    ICON-D2 regular lat-lon grid has lat decreasing (N->S) and lon increasing (W->E).

    Args:
        lat: 1D latitude array (decreasing).
        lon: 1D longitude array (increasing).
        bbox: Dict with lat_min, lat_max, lon_min, lon_max. Defaults to NL_BBOX.

    Returns:
        (lat_slice, lon_slice) for subsetting arrays.
    """
    if bbox is None:
        bbox = NL_BBOX

    # Normalize longitudes to [-180, 360) range for comparison
    # ICON-D2 uses 356.06 to 20.34 (wrapping through 0)
    lon_norm = np.where(lon > 180, lon - 360, lon)

    # lat is decreasing, so lat_max comes first in array order
    lat_mask = (lat >= bbox["lat_min"]) & (lat <= bbox["lat_max"])
    lon_mask = (lon_norm >= bbox["lon_min"]) & (lon_norm <= bbox["lon_max"])

    lat_indices = np.where(lat_mask)[0]
    lon_indices = np.where(lon_mask)[0]

    if len(lat_indices) == 0 or len(lon_indices) == 0:
        raise ValueError(f"No grid points found within bbox {bbox}")

    lat_slice = slice(lat_indices[0], lat_indices[-1] + 1)
    lon_slice = slice(lon_indices[0], lon_indices[-1] + 1)

    return lat_slice, lon_slice


def subset_domain(data: np.ndarray, lat_slice: slice, lon_slice: slice) -> np.ndarray:
    """Subset a 2D or 3D array to the NL domain.

    Args:
        data: Array with last two dims being (lat, lon).
        lat_slice: Latitude index slice.
        lon_slice: Longitude index slice.

    Returns:
        Subsetted array.
    """
    if data.ndim == 2:
        return data[lat_slice, lon_slice]
    elif data.ndim == 3:
        return data[:, lat_slice, lon_slice]
    else:
        raise ValueError(f"Expected 2D or 3D array, got {data.ndim}D")


def get_geotransform_latlon(lat: np.ndarray, lon: np.ndarray) -> tuple:
    """Compute GDAL GeoTransform for a regular lat-lon grid.

    Args:
        lat: 1D latitude array (can be increasing or decreasing).
        lon: 1D longitude array (increasing).

    Returns:
        GDAL GeoTransform tuple (x_origin, x_res, 0, y_origin, 0, y_res).
    """
    dlon = float(lon[1] - lon[0])
    dlat = float(lat[1] - lat[0])  # negative if lat is decreasing (N->S)

    # GeoTransform: upper-left corner
    x_origin = float(lon[0]) - dlon / 2.0
    y_origin = float(lat[0]) - dlat / 2.0

    return (x_origin, dlon, 0.0, y_origin, 0.0, dlat)


def get_grid_info(lat: np.ndarray, lon: np.ndarray) -> dict:
    """Get grid metadata for .data file headers.

    Args:
        lat: 1D latitude array (subsetted domain).
        lon: 1D longitude array (subsetted domain).

    Returns:
        Dict with grid info: dlat, dlon, lat_min, lat_max, lon_min, lon_max, nx, ny.
    """
    dlat = abs(float(lat[1] - lat[0]))
    dlon = abs(float(lon[1] - lon[0]))

    return {
        "dlat": dlat,
        "dlon": dlon,
        "lat_min": float(np.min(lat)),
        "lat_max": float(np.max(lat)),
        "lon_min": float(np.min(lon)),
        "lon_max": float(np.max(lon)),
        "ny": len(lat),
        "nx": len(lon),
    }
