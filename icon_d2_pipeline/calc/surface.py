"""Surface parameter calculations."""

import numpy as np


def calc_sfctemp(t2m: np.ndarray) -> np.ndarray:
    """Surface temperature in Celsius from 2m temperature (already in C)."""
    return t2m.astype(np.float32)


def calc_sfcdewpt(td2m: np.ndarray) -> np.ndarray:
    """Surface dewpoint in Celsius from 2m dewpoint (already in C)."""
    return td2m.astype(np.float32)


def calc_sfcsunpct(swdown: np.ndarray, jday: int, gmthr: float,
                   lat: np.ndarray, lon: np.ndarray,
                   ter: np.ndarray, z: np.ndarray,
                   pmb: np.ndarray, tc: np.ndarray,
                   qvapor: np.ndarray) -> np.ndarray:
    """Calculate normalized surface solar radiation percentage.

    Computes the ratio of actual incoming solar radiation to the
    theoretical clear-sky maximum. This gives a sunshine percentage.

    The Fortran implementation uses a complex clear-sky radiation model.
    We use a simplified version based on the solar zenith angle and a
    clear-sky transmittance model.

    Args:
        swdown: Actual downward shortwave radiation (W/m^2), 2D.
        jday: Julian day of year.
        gmthr: GMT hour (decimal).
        lat: Latitude array (1D or 2D).
        lon: Longitude array (1D or 2D).
        ter: Terrain height (lat, lon).
        z: Heights MSL (level, lat, lon).
        pmb: Pressure (level, lat, lon) in hPa.
        tc: Temperature (level, lat, lon) in Celsius.
        qvapor: Water vapor mixing ratio (level, lat, lon).

    Returns:
        Sunshine percentage (0-100), same shape as swdown.
        -999 where sun is below horizon.
    """
    # Make 2D lat/lon if needed
    if lat.ndim == 1 and lon.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    else:
        lat2d, lon2d = lat, lon

    # Solar declination angle
    declination = 23.45 * np.sin(np.radians((284 + jday) * 360.0 / 365.0))
    decl_rad = np.radians(declination)

    # Hour angle
    solar_hour = gmthr + lon2d / 15.0  # Local solar time
    hour_angle = np.radians(15.0 * (solar_hour - 12.0))

    # Solar zenith angle
    lat_rad = np.radians(lat2d)
    cos_zenith = (np.sin(lat_rad) * np.sin(decl_rad) +
                  np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_angle))
    cos_zenith = np.maximum(cos_zenith, 0.0)  # Sun above horizon

    # Clear-sky radiation using Kasten (1980) formula with water vapor correction
    solar_constant = 1361.0  # W/m^2
    airmass = np.where(cos_zenith > 0.01, 1.0 / cos_zenith, 40.0)
    airmass = np.minimum(airmass, 40.0)

    # Compute precipitable water (PW) from qvapor column if available
    if qvapor is not None and pmb is not None and z is not None:
        nz_3d = qvapor.shape[0]
        # Integrate qvapor through atmosphere: PW = (1/g) * sum(qv * dp)
        pw = np.zeros_like(ter)
        for k in range(1, nz_3d):
            dp = np.abs(pmb[k - 1] - pmb[k]) * 100.0  # hPa -> Pa
            qv_avg = 0.5 * (qvapor[k - 1] + qvapor[k])
            pw += qv_avg * dp / 9.81
        # pw is in kg/m^2 ~ mm
    else:
        pw = np.full_like(ter, 15.0)  # Typical mid-latitude PW in mm

    # Kasten clear-sky transmittance with water vapor correction
    # transmittance = exp(-0.09 * airmass^0.75 * (1 + 0.012 * pw))
    transmittance = np.exp(-0.09 * airmass ** 0.75 * (1.0 + 0.012 * pw))

    clear_sky = solar_constant * cos_zenith * transmittance

    # Sunshine percentage = 100 * swdown / clear_sky
    # -999 where sun is below horizon (DrJack convention: missing value)
    result = np.where(
        ~sun_up, -999.0,
        np.where(clear_sky > 10.0,
                 np.clip(100.0 * swdown / clear_sky, 0.0, 100.0),
                 50.0))

    return result.astype(np.float32)
