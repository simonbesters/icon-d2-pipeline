"""Remap ICON-D2 icosahedral grid data to regular lat-lon grid.

ICON-D2 model-level 3D data (T, U, V, W, QV, QC, P) is only available on the
native icosahedral (triangular) grid. This module handles interpolation to the
regular lat-lon grid used by single-level and time-invariant fields.

Strategy:
1. Read grid coordinates from one icosahedral GRIB message (cell centers)
2. Build interpolation weights once (scipy cKDTree for efficiency)
3. Apply weights to all fields (fast matrix operation)
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class IconRemapper:
    """Remaps ICON-D2 icosahedral data to a regular lat-lon grid.

    Builds interpolation weights once, then reuses them for all fields.
    Uses inverse-distance weighting with the nearest K icosahedral cells.
    """

    def __init__(self, target_lats, target_lons, k_neighbors=4):
        """Initialize with target regular grid coordinates.

        Args:
            target_lats: 1D array of target latitude values (ascending).
            target_lons: 1D array of target longitude values (ascending).
            k_neighbors: Number of nearest neighbors for IDW interpolation.
        """
        self.target_lats = target_lats
        self.target_lons = target_lons
        self.k = k_neighbors
        self._weights = None
        self._indices = None
        self._target_shape = (len(target_lats), len(target_lons))

    def build_weights(self, ico_lats, ico_lons):
        """Build interpolation weights from icosahedral grid coordinates.

        Args:
            ico_lats: 1D array of icosahedral cell center latitudes (degrees).
            ico_lons: 1D array of icosahedral cell center longitudes (degrees).
        """
        from scipy.spatial import cKDTree

        # Normalize longitudes to [-180, 180]
        ico_lons = np.where(ico_lons > 180, ico_lons - 360, ico_lons)

        # Build target meshgrid
        tlon, tlat = np.meshgrid(self.target_lons, self.target_lats)
        target_points = np.column_stack([tlat.ravel(), tlon.ravel()])

        # Convert to approximate Cartesian for distance calculation
        # (good enough for small domains — avoids full geodesic computation)
        mean_lat = np.mean(self.target_lats)
        cos_lat = np.cos(np.radians(mean_lat))

        ico_xy = np.column_stack([ico_lats, ico_lons * cos_lat])
        target_xy = np.column_stack([target_points[:, 0],
                                      target_points[:, 1] * cos_lat])

        tree = cKDTree(ico_xy)
        distances, indices = tree.query(target_xy, k=self.k)

        # Compute IDW weights (1/d^2, normalized)
        # Handle exact matches (distance = 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            inv_dist = 1.0 / distances ** 2
        # If any distance is 0, set weight to 1 for that point, 0 for others
        exact = distances == 0
        if np.any(exact):
            row_has_exact = np.any(exact, axis=1)
            inv_dist[row_has_exact] = 0.0
            inv_dist[exact] = 1.0

        weight_sum = inv_dist.sum(axis=1, keepdims=True)
        weights = inv_dist / weight_sum

        self._indices = indices  # (n_target, k)
        self._weights = weights  # (n_target, k)

        logger.info(f"Built remap weights: {len(ico_lats)} ico cells -> "
                     f"{self._target_shape[0]}x{self._target_shape[1]} regular grid")

    def remap(self, ico_field):
        """Remap a 1D icosahedral field to 2D regular grid.

        Args:
            ico_field: 1D array of values on icosahedral grid cells.

        Returns:
            2D array (ny, nx) on the regular lat-lon grid.
        """
        if self._weights is None:
            raise RuntimeError("Must call build_weights() first")

        # Gather neighbor values and apply weights
        neighbor_vals = ico_field[self._indices]  # (n_target, k)
        result = np.sum(neighbor_vals * self._weights, axis=1)
        return result.reshape(self._target_shape)

    def remap_3d(self, ico_field_3d):
        """Remap a 2D (n_levels, n_cells) icosahedral field to 3D regular grid.

        Args:
            ico_field_3d: 2D array (n_levels, n_cells) on icosahedral grid.

        Returns:
            3D array (n_levels, ny, nx) on the regular lat-lon grid.
        """
        n_levels = ico_field_3d.shape[0]
        result = np.empty((n_levels, *self._target_shape), dtype=ico_field_3d.dtype)
        for lev in range(n_levels):
            result[lev] = self.remap(ico_field_3d[lev])
        return result


def read_ico_grid_coords(clat_path, clon_path):
    """Read icosahedral grid coordinates from clat/clon GRIB files.

    ICON-D2 icosahedral GRIB files don't embed coordinates —
    they reference a grid number. The actual cell center coordinates
    are in separate clat/clon time-invariant files from DWD.

    Args:
        clat_path: Path to the clat (cell latitude) GRIB file.
        clon_path: Path to the clon (cell longitude) GRIB file.

    Returns:
        Tuple of (lats, lons) as 1D arrays in degrees.
    """
    import eccodes

    def _read_values(path):
        with open(path, 'rb') as f:
            msgid = eccodes.codes_grib_new_from_file(f)
            vals = eccodes.codes_get_values(msgid)
            eccodes.codes_release(msgid)
        return vals

    lats = _read_values(clat_path)  # Already in degrees
    lons = _read_values(clon_path)  # Already in degrees
    return lats, lons


def build_target_grid(lat_min, lat_max, lon_min, lon_max, dlat=0.02, dlon=0.02):
    """Build target regular lat-lon grid arrays.

    Args:
        lat_min, lat_max: Latitude bounds.
        lon_min, lon_max: Longitude bounds.
        dlat, dlon: Grid spacing in degrees.

    Returns:
        Tuple of (lats_1d, lons_1d) as 1D arrays.
    """
    lats = np.arange(lat_min, lat_max + dlat / 2, dlat)
    lons = np.arange(lon_min, lon_max + dlon / 2, dlon)
    return lats, lons
