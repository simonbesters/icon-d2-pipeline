"""Thermal and convection parameter calculations.

Reimplements Dr. Jack's calc_wstar, calc_hcrit, calc_hlift from the
proprietary Fortran library, based on well-known atmospheric formulas.
"""

import numpy as np

from ..config import GRAVITY


def calc_wstar(vhf: np.ndarray, pblh: np.ndarray,
               t_avg: np.ndarray | float = 300.0) -> np.ndarray:
    """Calculate convective velocity scale w* (Deardorff).

    w* = (g/T_avg * pblh * vhf)^(1/3)

    where vhf is the virtual heat flux (sensible + moisture contribution).

    Args:
        vhf: Virtual heat flux (W/m^2), 2D array.
        pblh: PBL height (m), 2D array.
        t_avg: BL-averaged temperature in K. Can be a 2D array or scalar
               (default 300.0 for backward compatibility).

    Returns:
        w* in m/s, 2D array. Negative or zero vhf yields 0.
    """
    # Only compute where vhf > 0 (upward flux = convection)
    # Convert energy flux (W/m²) to kinematic flux (K·m/s): divide by ρ·cp
    RHO_CP = 1200.0  # ρ·cp ≈ 1.2 kg/m³ × 1004 J/(kg·K)
    arg = (GRAVITY / t_avg) * pblh * (vhf / RHO_CP)
    wstar = np.where(vhf > 0.0, np.cbrt(np.maximum(arg, 0.0)), 0.0)
    return wstar.astype(np.float32)


def calc_hcrit(wstar: np.ndarray, ter: np.ndarray,
               pblh: np.ndarray) -> np.ndarray:
    """Calculate height MSL where thermal updraft strength = 225 fpm (critical).

    The thermal profile is modeled as decreasing linearly from surface to BL top.
    At height z above terrain, updraft = wstar * (1 - (z-ter)/(pblh)).
    The "critical" updraft is 225 fpm = 1.143 m/s (Dr. Jack's Fortran uses 225).
    Solving: z_crit = ter + pblh * (1 - 1.143/wstar)

    Args:
        wstar: Convective velocity scale (m/s).
        ter: Terrain height MSL (m).
        pblh: PBL height AGL (m).

    Returns:
        Height MSL (m) where updraft drops below 175 fpm.
        Set to terrain height where wstar is too weak.
    """
    critical_ms = 225.0 * 0.00508  # 225 fpm to m/s = 1.143 m/s

    hcrit = np.full_like(wstar, fill_value=-999.0)
    valid = wstar > critical_ms
    hcrit[valid] = ter[valid] + pblh[valid] * (1.0 - critical_ms / wstar[valid])
    hcrit[~valid] = ter[~valid]

    return hcrit


def calc_hlift(criteria_fpm: float, wstar: np.ndarray, ter: np.ndarray,
               pblh: np.ndarray) -> np.ndarray:
    """Calculate height MSL where thermal updraft = criteria_fpm.

    Same as hcrit but with an adjustable criteria value.
    This is "experimental1" when criteria_fpm = 175.

    Args:
        criteria_fpm: Updraft criteria in fpm (e.g., 175).
        wstar: Convective velocity scale (m/s).
        ter: Terrain height MSL (m).
        pblh: PBL height AGL (m).

    Returns:
        Height MSL (m).
    """
    criteria_ms = criteria_fpm * 0.00508  # fpm to m/s

    hlift = np.full_like(wstar, fill_value=-999.0)
    valid = wstar > criteria_ms
    hlift[valid] = ter[valid] + pblh[valid] * (1.0 - criteria_ms / wstar[valid])
    hlift[~valid] = ter[~valid]

    return hlift
