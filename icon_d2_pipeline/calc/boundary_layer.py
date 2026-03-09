"""Boundary layer parameter calculations.

Reimplements Dr. Jack's Fortran BL averaging and max/min functions.
All functions expect bottom-up level ordering (index 0 = surface).
"""

import numpy as np


def calc_blavg(field_3d: np.ndarray, z: np.ndarray,
               ter: np.ndarray, pblh: np.ndarray) -> np.ndarray:
    """Calculate the boundary-layer average of a 3D field.

    Averages the field from the surface to BL top (ter + pblh).
    Uses trapezoidal integration weighted by layer thickness.

    Args:
        field_3d: 3D field (level, lat, lon), bottom-up.
        z: Heights MSL (level, lat, lon), bottom-up.
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).

    Returns:
        BL-averaged field (lat, lon).
    """
    nz, ny, nx = field_3d.shape
    bl_top = ter + pblh
    result = np.zeros((ny, nx), dtype=np.float64)
    total_weight = np.zeros((ny, nx), dtype=np.float64)

    for k in range(nz - 1):
        z_lo = z[k]
        z_hi = z[k + 1]
        f_lo = field_3d[k]
        f_hi = field_3d[k + 1]

        # Only include layers within BL
        in_bl = z_lo < bl_top

        # Effective top of this layer (capped at BL top)
        z_eff_hi = np.minimum(z_hi, bl_top)
        dz = np.maximum(z_eff_hi - z_lo, 0.0)

        # Trapezoidal average of field in this layer
        f_avg = 0.5 * (f_lo + f_hi)

        result += np.where(in_bl, f_avg * dz, 0.0)
        total_weight += np.where(in_bl, dz, 0.0)

    # Avoid division by zero
    valid = total_weight > 0.0
    result[valid] /= total_weight[valid]
    result[~valid] = field_3d[0][~valid]  # fallback to surface value

    return result.astype(np.float32)


def calc_blmax(field_3d: np.ndarray, z: np.ndarray,
               ter: np.ndarray, pblh: np.ndarray) -> np.ndarray:
    """Calculate the maximum value of a 3D field within the BL.

    Args:
        field_3d: 3D field (level, lat, lon), bottom-up.
        z: Heights MSL (level, lat, lon), bottom-up.
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).

    Returns:
        Maximum value within BL (lat, lon).
    """
    nz, ny, nx = field_3d.shape
    bl_top = ter + pblh
    result = np.full((ny, nx), -np.inf, dtype=np.float32)

    for k in range(nz):
        in_bl = z[k] <= bl_top
        result = np.where(in_bl, np.maximum(result, field_3d[k]), result)

    # Replace -inf with surface value where no valid data
    no_data = np.isinf(result)
    result[no_data] = field_3d[0][no_data]
    return result


def calc_blwinddiff(ua: np.ndarray, va: np.ndarray, z: np.ndarray,
                    ter: np.ndarray, pblh: np.ndarray) -> np.ndarray:
    """Calculate BL vertical wind shear (speed difference surface to BL top).

    Args:
        ua: U-wind component (level, lat, lon), bottom-up, m/s.
        va: V-wind component (level, lat, lon), bottom-up, m/s.
        z: Heights MSL (level, lat, lon), bottom-up.
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).

    Returns:
        Wind shear magnitude (m/s), (lat, lon).
    """
    # Surface wind
    u_sfc = ua[0]
    v_sfc = va[0]
    spd_sfc = np.sqrt(u_sfc**2 + v_sfc**2)

    # BL top wind (interpolate to BL top)
    u_top, v_top = _interp_to_height(ua, va, z, ter + pblh)
    spd_top = np.sqrt(u_top**2 + v_top**2)

    return np.abs(spd_top - spd_sfc).astype(np.float32)


def calc_bltopwind(ua: np.ndarray, va: np.ndarray, z: np.ndarray,
                   ter: np.ndarray, pblh: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate wind at BL top.

    Returns:
        (u_top, v_top, speed_top) each (lat, lon) in m/s.
    """
    u_top, v_top = _interp_to_height(ua, va, z, ter + pblh)
    spd_top = np.sqrt(u_top**2 + v_top**2)
    return u_top.astype(np.float32), v_top.astype(np.float32), spd_top.astype(np.float32)


def calc_wblmaxmin(mode: int, wa: np.ndarray, z: np.ndarray,
                   ter: np.ndarray, pblh: np.ndarray) -> np.ndarray:
    """Calculate max vertical velocity or its height within BL.

    The Fortran calc_wblmaxmin returns values in cm/s (mode 0) or meters (mode 1).

    Args:
        mode: 0 = max |W| in cm/s, 1 = height MSL of max |W| in m.
        wa: Vertical velocity (level, lat, lon), bottom-up, m/s.
        z: Heights MSL (level, lat, lon), bottom-up.
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).

    Returns:
        Result array (lat, lon).
    """
    nz, ny, nx = wa.shape
    bl_top = ter + pblh

    max_w = np.zeros((ny, nx), dtype=np.float32)
    z_maxw = np.copy(ter).astype(np.float32)

    for k in range(nz):
        in_bl = z[k] <= bl_top
        abs_w = np.abs(wa[k])
        update = in_bl & (abs_w > np.abs(max_w))

        # Store signed value for mode 0
        max_w = np.where(update, wa[k], max_w)
        z_maxw = np.where(update, z[k], z_maxw)

    if mode == 0:
        return (max_w * 100.0).astype(np.float32)  # Convert m/s to cm/s
    elif mode == 1:
        return z_maxw
    else:
        raise ValueError(f"Unknown mode {mode}")


def calc_bltop_pottemp_variability(theta: np.ndarray, z: np.ndarray,
                                   ter: np.ndarray, pblh: np.ndarray,
                                   criterion: float = 1.0) -> np.ndarray:
    """Calculate BL top uncertainty/variability for overdevelopment potential.

    Measures the depth of the inversion zone at BL top.
    Finds the height range around BL top where theta changes by 'criterion' degC.

    Args:
        theta: Potential temperature (level, lat, lon), bottom-up, K.
        z: Heights MSL (level, lat, lon), bottom-up.
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).
        criterion: Temperature change threshold (K), default 1.0.

    Returns:
        Variability in meters (lat, lon).
    """
    nz, ny, nx = theta.shape
    bl_top = ter + pblh
    result = np.zeros((ny, nx), dtype=np.float32)

    # Find theta at BL top
    theta_bltop = np.zeros((ny, nx), dtype=np.float64)
    for k in range(nz - 1):
        at_bltop = (z[k] <= bl_top) & (z[k + 1] > bl_top)
        # Interpolate theta to BL top
        frac = np.where(at_bltop,
                        np.clip((bl_top - z[k]) / np.maximum(z[k+1] - z[k], 1.0), 0, 1),
                        0.0)
        theta_bltop = np.where(at_bltop,
                               theta[k] + frac * (theta[k+1] - theta[k]),
                               theta_bltop)

    # Find height range where theta is within +/- criterion of BL top theta
    z_low = np.copy(bl_top)
    z_high = np.copy(bl_top)

    for k in range(nz):
        in_range = np.abs(theta[k] - theta_bltop) < criterion
        near_bltop = np.abs(z[k] - bl_top) < pblh  # reasonable search range
        update = in_range & near_bltop

        z_low = np.where(update & (z[k] < z_low), z[k], z_low)
        z_high = np.where(update & (z[k] > z_high), z[k], z_high)

    result = (z_high - z_low).astype(np.float32)
    return result


def calc_blwind(ua: np.ndarray, va: np.ndarray, z: np.ndarray,
                ter: np.ndarray, pblh: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate BL-averaged wind speed and components.

    Returns:
        (u_avg, v_avg, speed_avg) each (lat, lon) in m/s.
    """
    u_avg = calc_blavg(ua, z, ter, pblh)
    v_avg = calc_blavg(va, z, ter, pblh)
    spd_avg = np.sqrt(u_avg**2 + v_avg**2)
    return u_avg, v_avg, spd_avg.astype(np.float32)


def _interp_to_height(ua: np.ndarray, va: np.ndarray, z: np.ndarray,
                      target_z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate wind components to a target height.

    Args:
        ua, va: Wind components (level, lat, lon), bottom-up.
        z: Heights MSL (level, lat, lon), bottom-up.
        target_z: Target height MSL (lat, lon).

    Returns:
        (u_interp, v_interp) at target height.
    """
    nz, ny, nx = ua.shape
    u_result = np.zeros((ny, nx), dtype=np.float64)
    v_result = np.zeros((ny, nx), dtype=np.float64)
    found = np.zeros((ny, nx), dtype=bool)

    for k in range(nz - 1):
        bracket = (~found) & (z[k] <= target_z) & (z[k + 1] > target_z)
        frac = np.where(bracket,
                        np.clip((target_z - z[k]) / np.maximum(z[k+1] - z[k], 1.0), 0, 1),
                        0.0)
        u_result = np.where(bracket, ua[k] + frac * (ua[k+1] - ua[k]), u_result)
        v_result = np.where(bracket, va[k] + frac * (va[k+1] - va[k]), v_result)
        found = found | bracket

    # Fallback: use nearest level if target is above all levels
    if not np.all(found):
        u_result = np.where(found, u_result, ua[-1])
        v_result = np.where(found, v_result, va[-1])

    return u_result.astype(np.float32), v_result.astype(np.float32)
