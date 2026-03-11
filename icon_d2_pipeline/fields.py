"""Read GRIB fields and derive atmospheric variables from ICON-D2 output."""

import logging
from pathlib import Path

import eccodes
import numpy as np

from .config import GRAVITY, P_REF, RDCP, T0

logger = logging.getLogger(__name__)


def read_grib_field(filepath: Path) -> tuple[np.ndarray, dict]:
    """Read a single GRIB2 file and return the data array and metadata.

    Returns:
        (data_array, metadata_dict) where metadata includes keys like
        'Ni', 'Nj', 'latitudeOfFirstGridPointInDegrees', etc.
    """
    with open(filepath, "rb") as f:
        msgid = eccodes.codes_grib_new_from_file(f)
        if msgid is None:
            raise ValueError(f"No GRIB message in {filepath}")

        try:
            ni = eccodes.codes_get(msgid, "Ni")
            nj = eccodes.codes_get(msgid, "Nj")
            values = eccodes.codes_get_values(msgid)
            data = values.reshape(nj, ni)

            meta = {
                "Ni": ni,
                "Nj": nj,
                "shortName": eccodes.codes_get(msgid, "shortName"),
                "latitudeOfFirstGridPointInDegrees": eccodes.codes_get(
                    msgid, "latitudeOfFirstGridPointInDegrees"),
                "latitudeOfLastGridPointInDegrees": eccodes.codes_get(
                    msgid, "latitudeOfLastGridPointInDegrees"),
                "longitudeOfFirstGridPointInDegrees": eccodes.codes_get(
                    msgid, "longitudeOfFirstGridPointInDegrees"),
                "longitudeOfLastGridPointInDegrees": eccodes.codes_get(
                    msgid, "longitudeOfLastGridPointInDegrees"),
                "iDirectionIncrementInDegrees": eccodes.codes_get(
                    msgid, "iDirectionIncrementInDegrees"),
                "jDirectionIncrementInDegrees": eccodes.codes_get(
                    msgid, "jDirectionIncrementInDegrees"),
            }
            return data, meta

        finally:
            eccodes.codes_release(msgid)


def read_grib_multi(filepath: Path) -> list[tuple[np.ndarray, dict]]:
    """Read all GRIB messages from a file (e.g. multi-level HHL)."""
    results = []
    with open(filepath, "rb") as f:
        while True:
            msgid = eccodes.codes_grib_new_from_file(f)
            if msgid is None:
                break
            try:
                ni = eccodes.codes_get(msgid, "Ni")
                nj = eccodes.codes_get(msgid, "Nj")
                values = eccodes.codes_get_values(msgid)
                data = values.reshape(nj, ni)
                level = eccodes.codes_get(msgid, "level", default=0)
                results.append((data, {"level": level}))
            finally:
                eccodes.codes_release(msgid)
    return results


def get_lat_lon_from_meta(meta: dict) -> tuple[np.ndarray, np.ndarray]:
    """Construct 1D lat/lon arrays from GRIB metadata."""
    lat_first = meta["latitudeOfFirstGridPointInDegrees"]
    lat_last = meta["latitudeOfLastGridPointInDegrees"]
    lon_first = meta["longitudeOfFirstGridPointInDegrees"]
    lon_last = meta["longitudeOfLastGridPointInDegrees"]
    nj = meta["Nj"]
    ni = meta["Ni"]

    # Normalize longitudes: ICON-D2 uses 356.06..20.34 (wrapping through 0)
    # Convert to continuous range for linspace
    if lon_first > lon_last and lon_first > 180:
        lon_first -= 360  # e.g., 356.06 -> -3.94

    lat = np.linspace(lat_first, lat_last, nj)
    lon = np.linspace(lon_first, lon_last, ni)
    return lat, lon


def read_grib_ico_field(filepath: Path) -> np.ndarray:
    """Read a single GRIB2 file with icosahedral (unstructured) grid.

    Returns 1D array of values on the native icosahedral grid.
    """
    with open(filepath, "rb") as f:
        msgid = eccodes.codes_grib_new_from_file(f)
        if msgid is None:
            raise ValueError(f"No GRIB message in {filepath}")
        try:
            values = eccodes.codes_get_values(msgid)
            return values
        finally:
            eccodes.codes_release(msgid)


def load_3d_field_ico(grib_dir: Path, date_init: str, forecast_hour: int,
                      var_name: str, num_levels: int) -> np.ndarray:
    """Load a 3D model-level field from icosahedral GRIB files.

    Returns 2D array (level, n_cells) on the native icosahedral grid.
    Use IconRemapper to convert to regular lat-lon grid.
    """
    levels_data = []
    for level in range(1, num_levels + 1):
        filename = f"icon-d2_{date_init}_{forecast_hour:03d}_{var_name}_ml{level:03d}.grib2"
        filepath = grib_dir / filename
        levels_data.append(read_grib_ico_field(filepath))

    return np.stack(levels_data, axis=0)


def load_3d_field(grib_dir: Path, date_init: str, forecast_hour: int,
                  var_name: str, num_levels: int,
                  lat_slice: slice, lon_slice: slice) -> np.ndarray:
    """Load a 3D model-level field from individual per-level GRIB files.

    Note: This function is for regular-lat-lon grids only. For icosahedral
    model-level data, use load_3d_field_ico() + IconRemapper.

    Args:
        grib_dir: Directory containing downloaded GRIB files.
        date_init: Date+init string like "2026030900".
        forecast_hour: Forecast hour.
        var_name: Variable name (lowercase, e.g., "t", "qv").
        num_levels: Number of model levels.
        lat_slice, lon_slice: Domain subset slices.

    Returns:
        3D array (level, lat, lon) with level 0 = TOA (ICON convention).
    """
    levels_data = []
    for level in range(1, num_levels + 1):
        filename = f"icon-d2_{date_init}_{forecast_hour:03d}_{var_name}_ml{level:03d}.grib2"
        filepath = grib_dir / filename
        data, _ = read_grib_field(filepath)
        levels_data.append(data[lat_slice, lon_slice])

    return np.stack(levels_data, axis=0)


def load_2d_field(grib_dir: Path, date_init: str, forecast_hour: int,
                  var_name: str, lat_slice: slice, lon_slice: slice) -> np.ndarray:
    """Load a 2D single-level field from a GRIB file."""
    filename = f"icon-d2_{date_init}_{forecast_hour:03d}_{var_name}_sl.grib2"
    filepath = grib_dir / filename
    data, _ = read_grib_field(filepath)
    return data[lat_slice, lon_slice]


def load_invariant_field(grib_dir: Path, date_init: str, var_name: str,
                         lat_slice: slice, lon_slice: slice) -> np.ndarray:
    """Load a time-invariant field."""
    filename = f"icon-d2_{date_init}_000_{var_name}_inv.grib2"
    filepath = grib_dir / filename
    data, _ = read_grib_field(filepath)
    return data[lat_slice, lon_slice]


def compute_model_heights(hhl: np.ndarray) -> np.ndarray:
    """Compute full-level (mass-point) heights from half-level heights.

    ICON-D2 has 66 half-levels (HHL) and 65 full levels.
    Full-level height = average of surrounding half-levels.

    Args:
        hhl: Half-level heights, shape (66, lat, lon), level 0 = TOA.

    Returns:
        Full-level heights, shape (65, lat, lon), level 0 = TOA.
    """
    return 0.5 * (hhl[:-1] + hhl[1:])


def flip_to_bottom_up(field_3d: np.ndarray) -> np.ndarray:
    """Flip 3D field from ICON top-down to bottom-up convention.

    After flipping, index 0 = surface (lowest model level).

    Args:
        field_3d: Array with shape (levels, lat, lon), level 0 = TOA.

    Returns:
        Flipped array with level 0 = surface.
    """
    return field_3d[::-1].copy()


def compute_derived_2d(raw: dict) -> dict:
    """Compute derived 2D fields from raw ICON-D2 output.

    Args:
        raw: Dict of 2D arrays with keys like 'T_2M', 'TD_2M', etc.

    Returns:
        Dict with added derived fields.
    """
    derived = dict(raw)

    # Surface temperature in Celsius
    if "T_2M" in raw:
        derived["sfctemp"] = raw["T_2M"] - T0

    # Surface dewpoint in Celsius
    if "TD_2M" in raw:
        derived["sfcdewpt"] = raw["TD_2M"] - T0

    # Virtual heat flux (from getvars.ncl:56)
    # NCL: vhf = hfx + 0.000245268 * (tc(0,:,:) + 273.16) * LH
    # where tc(0,:,:) is the lowest model level temperature in Celsius.
    # We use T_2M (already in Kelvin from ICON-D2) as an equivalent proxy.
    # The NCL converts Celsius to Kelvin via +273.16; T_2M is already K.
    # Difference between T_2M and lowest model level T is typically ~0.5-2K
    # which produces a ~0.1-0.5% change in VHF — acceptable approximation.
    if "ASHFL_S" in raw and "ALHFL_S" in raw and "T_2M" in raw:
        # ICON convention: positive = downward; negate to get positive = upward
        hfx = -raw["ASHFL_S"]
        lh = np.maximum(-raw["ALHFL_S"], 0.0)
        derived["vhf"] = hfx + 0.000245268 * raw["T_2M"] * lh

    # Total incoming solar radiation
    if "ASWDIR_S" in raw and "ASWDIFD_S" in raw:
        derived["swdown"] = raw["ASWDIR_S"] + raw["ASWDIFD_S"]

    return derived


def compute_derived_3d(raw_3d: dict, raw_2d: dict) -> dict:
    """Compute derived 3D fields from raw ICON-D2 output.

    All 3D fields should already be bottom-up (level 0 = surface).

    Args:
        raw_3d: Dict of 3D arrays with keys like 'T', 'QV', 'P', etc.
        raw_2d: Dict of 2D arrays.

    Returns:
        Dict with added derived 3D fields.
    """
    derived = dict(raw_3d)

    # Temperature in Celsius
    if "T" in raw_3d:
        derived["tc"] = raw_3d["T"] - T0

    # Pressure in hPa
    if "P" in raw_3d:
        derived["pmb"] = raw_3d["P"] / 100.0

    # Potential temperature (theta = T * (P0/P)^(R/cp))
    if "T" in raw_3d and "P" in raw_3d:
        derived["theta"] = raw_3d["T"] * (P_REF / raw_3d["P"]) ** RDCP

    # Dew point temperature from QV and P
    if "QV" in raw_3d and "P" in raw_3d:
        derived["td"] = _dewpoint_from_qv(raw_3d["QV"], raw_3d["P"])

    # Relative humidity
    if "T" in raw_3d and "QV" in raw_3d and "P" in raw_3d:
        derived["rh"] = _relative_humidity(raw_3d["T"], raw_3d["QV"], raw_3d["P"])

    return derived


def _dewpoint_from_qv(qv: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Compute dew point temperature (Celsius) from mixing ratio and pressure.

    Uses the Magnus formula.
    """
    # Vapor pressure from mixing ratio: e = qv * p / (0.622 + qv)
    # But qv is specific humidity in ICON, approximate: e ~ qv * p / 0.622
    e = np.maximum(qv, 1e-10) * p / (0.622 + qv)
    e_hpa = e / 100.0  # Convert to hPa

    # Magnus formula: Td = (243.5 * ln(e/6.112)) / (17.67 - ln(e/6.112))
    log_e = np.log(np.maximum(e_hpa, 0.001) / 6.112)
    td = 243.5 * log_e / (17.67 - log_e)
    return td


def _relative_humidity(t: np.ndarray, qv: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Compute relative humidity (%) from temperature, specific humidity and pressure."""
    tc = t - T0
    # Saturation vapor pressure (Magnus): es = 6.112 * exp(17.67 * tc / (tc + 243.5))
    es = 6.112 * np.exp(17.67 * tc / (tc + 243.5))  # hPa
    # Actual vapor pressure
    e = qv * (p / 100.0) / (0.622 + qv)
    rh = 100.0 * e / es
    return np.clip(rh, 0.0, 100.0)


def interpolate_half_hour(fields_h0: dict, fields_h1: dict,
                          weight: float) -> dict:
    """Linearly interpolate between two hourly field sets for half-hour times.

    Args:
        fields_h0: Fields at hour H.
        fields_h1: Fields at hour H+1.
        weight: Interpolation weight (0.0 = h0, 1.0 = h1, 0.5 = midpoint).

    Returns:
        Interpolated fields dict.
    """
    result = {}
    for key in fields_h0:
        if key in fields_h1:
            result[key] = (1.0 - weight) * fields_h0[key] + weight * fields_h1[key]
        else:
            result[key] = fields_h0[key]

    # Include any keys only in h1
    for key in fields_h1:
        if key not in result:
            result[key] = fields_h1[key]

    return result
