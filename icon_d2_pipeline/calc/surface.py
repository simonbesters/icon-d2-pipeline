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

    Ratio of actual incoming SW to theoretical clear-sky max (0-100%).

    Matches DrJack's calc_sfcsunpct_ + radconst_ Fortran:
    - Spencer (1971) Fourier expansion for solar declination + Earth-Sun
      eccentricity correction E0 (±3.4% over the year).
    - Lacis & Hansen (1974) parameterization for water vapor absorption,
      with constants 141.5, 0.635, 2.9, 5.925 extracted from .rodata of
      ncl_jack_fortran.so.
    - Solar constant 1370 W/m^2.

    Returns sunshine percentage (0-100), -999 where sun is below horizon.
    """
    if lat.ndim == 1 and lon.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    else:
        lat2d, lon2d = lat, lon

    # Spencer 1971 day-angle in radians
    gamma = 2.0 * np.pi * (jday - 1) / 365.0

    # Spencer 1971 solar declination (radians)
    decl_rad = (0.006918
                - 0.399912 * np.cos(gamma)
                + 0.070257 * np.sin(gamma)
                - 0.006758 * np.cos(2.0 * gamma)
                + 0.000907 * np.sin(2.0 * gamma)
                - 0.002697 * np.cos(3.0 * gamma)
                + 0.001480 * np.sin(3.0 * gamma))

    # Spencer 1971 Earth-Sun distance correction E0 = (r0/r)^2
    # Constants 0.034221, 1.000110, 0.001280, 0.000719, 0.000077 from .rodata
    e0 = (1.000110
          + 0.034221 * np.cos(gamma)
          + 0.001280 * np.sin(gamma)
          + 0.000719 * np.cos(2.0 * gamma)
          + 0.000077 * np.sin(2.0 * gamma))

    # Hour angle (15°/hr from solar noon)
    solar_hour = gmthr + lon2d / 15.0
    hour_angle = np.radians(15.0 * (solar_hour - 12.0))

    lat_rad = np.radians(lat2d)
    cos_zenith = (np.sin(lat_rad) * np.sin(decl_rad) +
                  np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_angle))

    sun_up = cos_zenith > 1e-9
    cos_z = np.maximum(cos_zenith, 1e-9)
    airmass = np.minimum(1.0 / cos_z, 40.0)

    # Precipitable water (kg/m^2 ~ mm) from qv column
    if qvapor is not None and pmb is not None and z is not None:
        nz_3d = qvapor.shape[0]
        pw = np.zeros_like(ter)
        for k in range(1, nz_3d):
            dp = np.abs(pmb[k - 1] - pmb[k]) * 100.0  # hPa -> Pa
            qv_avg = 0.5 * (qvapor[k - 1] + qvapor[k])
            pw += qv_avg * dp / 9.81
    else:
        pw = np.full_like(ter, 15.0)

    # Lacis & Hansen 1974 water vapor absorption.
    # x = scaled PW (cm) along the sun path. Convert PW kg/m^2 -> cm.
    pw_cm = pw / 10.0
    x = pw_cm * airmass
    aw = (2.9 * x) / ((1.0 + 141.5 * x) ** 0.635 + 5.925 * x)
    transmittance = np.maximum(1.0 - aw, 0.0)

    # Clear-sky direct beam on horizontal: TOA flux * E0 * cos_zenith * transmittance
    solar_constant = 1370.0
    clear_sky = solar_constant * e0 * cos_z * transmittance

    result = np.where(
        ~sun_up, -999.0,
        np.where(clear_sky > 10.0,
                 np.clip(100.0 * swdown / clear_sky, 0.0, 100.0),
                 50.0))

    return result.astype(np.float32)
