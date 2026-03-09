"""Derived soaring parameters that combine multiple calculations."""

import numpy as np

from ..config import CDBL


def calc_bsratio(blavg_windspeed: np.ndarray,
                 wstar: np.ndarray) -> np.ndarray:
    """Calculate buoyancy/shear ratio.

    bsratio = wstar / sqrt(cdbl * windspeed^2)
    Higher = better for thermal soaring. Truncated at 10.

    Both wstar and windspeed should be in m/s.

    Args:
        blavg_windspeed: BL-averaged wind speed (m/s).
        wstar: Convective velocity scale (m/s).

    Returns:
        Buoyancy/shear ratio (dimensionless), truncated at 10.
    """
    denominator = np.sqrt(CDBL * np.maximum(blavg_windspeed, 0.1) ** 2)
    bsratio = wstar / denominator
    return np.minimum(bsratio, 10.0).astype(np.float32)


def calc_hglider(hcrit: np.ndarray, zsfclcl: np.ndarray,
                 zblcl: np.ndarray) -> np.ndarray:
    """Calculate practical thermalling height (minimum of hcrit, zsfclcl, zblcl).

    From calc_funcs.ncl hglider(): takes minimum of hcrit with cloud bases,
    but only where the cloud base values are valid (positive).

    Args:
        hcrit: Critical updraft height MSL (m).
        zsfclcl: Surface LCL height MSL (m).
        zblcl: BL cloud height MSL (m).

    Returns:
        Practical thermalling height MSL (m).
    """
    result = np.copy(hcrit)

    # Only apply cloud base limits where they are valid (> 0)
    valid_sfclcl = zsfclcl > 0
    result = np.where(valid_sfclcl, np.minimum(result, zsfclcl), result)

    valid_zblcl = zblcl > 0
    result = np.where(valid_zblcl, np.minimum(result, zblcl), result)

    return result.astype(np.float32)


def calc_hbl(pblh: np.ndarray, ter: np.ndarray) -> np.ndarray:
    """Calculate height of BL top MSL.

    Args:
        pblh: PBL height AGL (m).
        ter: Terrain height MSL (m).

    Returns:
        BL top height MSL (m).
    """
    return (pblh + ter).astype(np.float32)


def calc_zsfclcldif(ter: np.ndarray, pblh: np.ndarray,
                    zsfclcl: np.ndarray) -> np.ndarray:
    """Calculate Cu potential = BL top MSL - surface LCL MSL.

    Positive values indicate cumulus cloud development likely.

    Args:
        ter: Terrain height MSL (m).
        pblh: PBL height AGL (m).
        zsfclcl: Surface LCL height MSL (m).

    Returns:
        Cu potential in meters.
    """
    return (pblh + ter - zsfclcl).astype(np.float32)


def calc_zblcldif(ter: np.ndarray, pblh: np.ndarray,
                  zblcl: np.ndarray) -> np.ndarray:
    """Calculate overdevelopment potential = BL top MSL - BL cloud height MSL.

    Positive values indicate overdevelopment (overcast) likely.
    """
    return (pblh + ter - zblcl).astype(np.float32)


def calc_zsfclclmask(zsfclcl: np.ndarray,
                     zsfclcldif: np.ndarray) -> np.ndarray:
    """Cu cloudbase where Cu potential > 0.

    Returns zsfclcl where zsfclcldif >= 0, otherwise -999999 (no data).
    """
    result = np.where(zsfclcldif >= 0, zsfclcl, -999999.0)
    return result.astype(np.float32)


def calc_zblclmask(zblcl: np.ndarray,
                   zblcldif: np.ndarray) -> np.ndarray:
    """OD cloudbase where OD potential > 0.

    Returns zblcl where zblcldif >= 0, otherwise -999999 (no data).
    """
    result = np.where(zblcldif >= 0, zblcl, -999999.0)
    return result.astype(np.float32)


def calc_rain1(tot_prec_current: np.ndarray,
               tot_prec_previous: np.ndarray) -> np.ndarray:
    """Calculate 1-hour accumulated rain.

    Args:
        tot_prec_current: Total precipitation at current time (mm).
        tot_prec_previous: Total precipitation 1 hour earlier (mm).

    Returns:
        1-hour precipitation (mm).
    """
    rain = np.maximum(tot_prec_current - tot_prec_previous, 0.0)
    return rain.astype(np.float32)


def calc_cfrac(clc_3d: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate low/mid/high cloud fraction from 3D cloud cover.

    Low: surface to 2000m AGL (or ~800 hPa)
    Mid: 2000m to 6000m (or ~800 to ~450 hPa)
    High: above 6000m (or ~450 hPa)

    If no 3D cloud fraction is available from ICON-D2, this returns zeros.

    Args:
        clc_3d: Cloud cover fraction (0-1) (level, lat, lon), bottom-up.
        z: Heights MSL (level, lat, lon), bottom-up.

    Returns:
        (cfracl, cfracm, cfrach) each in percent (lat, lon).
    """
    nz, ny, nx = clc_3d.shape

    # Use maximum overlap assumption per layer category
    cfracl = np.zeros((ny, nx), dtype=np.float32)
    cfracm = np.zeros((ny, nx), dtype=np.float32)
    cfrach = np.zeros((ny, nx), dtype=np.float32)

    # Define boundaries by height MSL
    # Low: below 2000m, Mid: 2000-6000m, High: above 6000m
    for k in range(nz):
        low = z[k] < 2000.0
        mid = (z[k] >= 2000.0) & (z[k] < 6000.0)
        high = z[k] >= 6000.0

        clc_pct = clc_3d[k] * 100.0
        cfracl = np.where(low, np.maximum(cfracl, clc_pct), cfracl)
        cfracm = np.where(mid, np.maximum(cfracm, clc_pct), cfracm)
        cfrach = np.where(high, np.maximum(cfrach, clc_pct), cfrach)

    return cfracl, cfracm, cfrach
