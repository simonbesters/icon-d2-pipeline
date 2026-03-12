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
    theoretical clear-sky maximum, giving a sunshine percentage (0-100).

    Solar geometry matches DrJack's radconst_ routine (solar constant 1370,
    axial tilt 23.5°, equinox offset day 80). Clear-sky transmittance uses
    Kasten (1980) with precipitable water correction — DrJack's Fortran uses
    a column extinction model which is not fully reconstructed.

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

    # Solar declination — DrJack radconst_ constants:
    # axial tilt = 23.5°, equinox offset = 80 days
    day_angle = 2.0 * np.pi * (jday - 80) / 365.0
    declination = 23.5 * np.sin(day_angle)
    decl_rad = np.radians(declination)

    # Hour angle (DrJack: 15°/hr from solar noon)
    solar_hour = gmthr + lon2d / 15.0
    hour_angle = np.radians(15.0 * (solar_hour - 12.0))

    # Solar zenith angle
    lat_rad = np.radians(lat2d)
    cos_zenith = (np.sin(lat_rad) * np.sin(decl_rad) +
                  np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_angle))

    # DrJack uses 1e-9 as minimum cosine threshold
    sun_up = cos_zenith > 1e-9

    # Clear-sky radiation — DrJack solar constant = 1370 W/m²
    solar_constant = 1370.0
    cos_z = np.maximum(cos_zenith, 1e-9)
    airmass = np.where(sun_up, 1.0 / cos_z, 40.0)
    airmass = np.minimum(airmass, 40.0)

    # Compute precipitable water (PW) from qvapor column
    if qvapor is not None and pmb is not None and z is not None:
        nz_3d = qvapor.shape[0]
        pw = np.zeros_like(ter)
        for k in range(1, nz_3d):
            dp = np.abs(pmb[k - 1] - pmb[k]) * 100.0  # hPa -> Pa
            qv_avg = 0.5 * (qvapor[k - 1] + qvapor[k])
            pw += qv_avg * dp / 9.81
    else:
        pw = np.full_like(ter, 15.0)

    # Kasten clear-sky transmittance with water vapor correction
    transmittance = np.exp(-0.09 * airmass ** 0.75 * (1.0 + 0.012 * pw))

    clear_sky = solar_constant * cos_z * transmittance

    # Sunshine percentage = 100 * swdown / clear_sky
    # -999 where sun is below horizon (DrJack convention: missing value)
    result = np.where(
        ~sun_up, -999.0,
        np.where(clear_sky > 10.0,
                 np.clip(100.0 * swdown / clear_sky, 0.0, 100.0),
                 50.0))

    return result.astype(np.float32)
