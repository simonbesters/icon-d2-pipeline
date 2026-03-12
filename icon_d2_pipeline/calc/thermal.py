"""Thermal and convection parameter calculations.

Reimplements Dr. Jack's calc_wstar, calc_hcrit, calc_hlift from the
proprietary Fortran library (ncl_jack_fortran.so), reconstructed via
reverse engineering of the compiled binary.
"""

import numpy as np

from ..config import GRAVITY

# DrJack's empirical thermal penetration model coefficients
# (from .rodata section of libncl_drjack.avx512.nocuda.so)
_MS_TO_FPM = 196.85       # m/s to ft/min conversion
_HCRIT_THRESHOLD = 225.0   # ft/min threshold for hcrit
_ALPHA1 = 0.463            # ratio scaling coefficient
_ALPHA2 = 0.4549           # linear offset
_ALPHA3 = 1.3674           # quadratic scaling
_ALPHA4 = 0.01267          # sqrt argument offset
_ALPHA5 = 0.1126           # base height fraction offset


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


def _drjack_height_frac(threshold_fpm: float, wstar_fpm: np.ndarray) -> np.ndarray:
    """DrJack's empirical nonlinear thermal penetration model.

    Reconstructed from calc_hcrit_/calc_hlift_ in libncl_drjack.so.
    Returns the fraction of BL depth that thermals can usefully penetrate.

    The model:
        ratio = threshold / wstar_fpm
        height_frac = sqrt(α₃ * (α₂ - α₁ * ratio) + α₄) + α₅

    This gives a nonlinear (square-root) relationship between thermal
    strength and usable height, unlike a simple linear profile.
    """
    ratio = threshold_fpm / wstar_fpm
    inner = _ALPHA3 * (_ALPHA2 - _ALPHA1 * ratio) + _ALPHA4
    # Clamp inner to >= 0 to avoid sqrt of negative
    height_frac = np.sqrt(np.maximum(inner, 0.0)) + _ALPHA5
    return height_frac


def calc_hcrit(wstar: np.ndarray, ter: np.ndarray,
               pblh: np.ndarray) -> np.ndarray:
    """Calculate critical height MSL where thermal updraft = 225 fpm.

    Uses DrJack's empirical nonlinear thermal penetration model
    (reconstructed from Fortran binary).

    Args:
        wstar: Convective velocity scale (m/s).
        ter: Terrain height MSL (m).
        pblh: PBL height AGL (m).

    Returns:
        Height MSL (m). Set to terrain height where wstar is too weak.
    """
    wstar_fpm = wstar * _MS_TO_FPM

    valid = wstar_fpm > _HCRIT_THRESHOLD
    height_frac = np.where(valid, _drjack_height_frac(_HCRIT_THRESHOLD, wstar_fpm), 0.0)

    result = np.where(valid,
                      ter + height_frac * pblh,
                      ter)
    return np.maximum(result, 0.0).astype(np.float32)


def calc_hlift(criteria_fpm: float, wstar: np.ndarray, ter: np.ndarray,
               pblh: np.ndarray) -> np.ndarray:
    """Calculate height MSL where thermal updraft = criteria_fpm.

    Same model as hcrit but with a variable threshold.
    This is "experimental1" when criteria_fpm = 175.

    Args:
        criteria_fpm: Updraft criteria in fpm (e.g., 175).
        wstar: Convective velocity scale (m/s).
        ter: Terrain height MSL (m).
        pblh: PBL height AGL (m).

    Returns:
        Height MSL (m).
    """
    wstar_fpm = wstar * _MS_TO_FPM

    valid = wstar_fpm > criteria_fpm
    height_frac = np.where(valid, _drjack_height_frac(criteria_fpm, wstar_fpm), 0.0)

    result = np.where(valid,
                      ter + height_frac * pblh,
                      ter)
    return np.maximum(result, 0.0).astype(np.float32)
