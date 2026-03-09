"""Pressure-level interpolation for wind and vertical velocity."""

import numpy as np

from ..config import PRESSURE_LEVELS


def interpolate_to_pressure(field_3d: np.ndarray, pmb: np.ndarray,
                            target_p: float) -> np.ndarray:
    """Interpolate a 3D field to a pressure surface.

    Args:
        field_3d: 3D field (level, lat, lon), bottom-up.
        pmb: Pressure in hPa (level, lat, lon), bottom-up.
        target_p: Target pressure level in hPa.

    Returns:
        Interpolated field (lat, lon). NaN where below ground.
    """
    nz, ny, nx = field_3d.shape
    result = np.full((ny, nx), np.nan, dtype=np.float32)
    found = np.zeros((ny, nx), dtype=bool)

    # Pressure decreases with height (bottom-up), so search upward
    for k in range(nz - 1):
        # Find where target pressure is between this level and next
        bracket = (~found) & (pmb[k] >= target_p) & (pmb[k + 1] < target_p)

        # Linear interpolation in log-pressure
        log_p_k = np.log(np.maximum(pmb[k], 0.01))
        log_p_k1 = np.log(np.maximum(pmb[k + 1], 0.01))
        log_p_target = np.log(target_p)

        denom = log_p_k - log_p_k1
        frac = np.where(bracket & (np.abs(denom) > 1e-10),
                        (log_p_k - log_p_target) / denom, 0.0)
        frac = np.clip(frac, 0.0, 1.0)

        interp_val = field_3d[k] + frac * (field_3d[k + 1] - field_3d[k])
        result = np.where(bracket, interp_val, result)
        found = found | bracket

    return result


def calc_pressure_level_winds(ua: np.ndarray, va: np.ndarray,
                              wa: np.ndarray, pmb: np.ndarray,
                              target_p: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Interpolate wind components and vertical velocity to a pressure level.

    Returns:
        (u, v, w) at the target pressure level, each (lat, lon).
    """
    u = interpolate_to_pressure(ua, pmb, target_p)
    v = interpolate_to_pressure(va, pmb, target_p)
    w = interpolate_to_pressure(wa, pmb, target_p)
    return u, v, w
