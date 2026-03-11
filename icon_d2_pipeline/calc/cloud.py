"""Cloud-related soaring parameter calculations.

Reimplements Dr. Jack's cloud base, LCL, and cloud percentage calculations.
All functions expect bottom-up level ordering (index 0 = surface).
"""

import numpy as np

from ..config import CWBASE_CRITERIA, MAX_CWBASE_M
from .boundary_layer import calc_blavg


def calc_blcloudbase(qcloud: np.ndarray, z: np.ndarray,
                     ter: np.ndarray, pblh: np.ndarray,
                     cwbase_criteria: float = CWBASE_CRITERIA) -> np.ndarray:
    """Calculate cloud base height AGL within the boundary layer.

    Scans upward from surface to find the lowest level where cloud water
    exceeds the threshold criterion within the BL.

    Args:
        qcloud: Cloud water mixing ratio (level, lat, lon), kg/kg.
        z: Heights MSL (level, lat, lon).
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).
        cwbase_criteria: Cloud water threshold.

    Returns:
        Cloud base height AGL (m). -999 where no cloud in BL.
    """
    nz, ny, nx = qcloud.shape
    bl_top = ter + pblh
    result = np.full((ny, nx), -999.0, dtype=np.float32)

    for k in range(nz):
        in_bl = z[k] <= bl_top
        has_cloud = qcloud[k] >= cwbase_criteria
        not_found = result < 0  # -999 means not yet found

        update = in_bl & has_cloud & not_found
        cloud_agl = z[k] - ter
        cloud_agl = np.minimum(cloud_agl, MAX_CWBASE_M)
        result = np.where(update, cloud_agl, result)

    return result


def calc_sfclcl_height(pmb: np.ndarray, tc: np.ndarray, td: np.ndarray,
                       z: np.ndarray, ter: np.ndarray,
                       pblh: np.ndarray) -> np.ndarray:
    """Calculate surface-based Lifting Condensation Level (LCL) height MSL.

    Lifts a surface parcel dry-adiabatically and conserves mixing ratio
    to find the height where T_parcel = Td_parcel (condensation level).
    Falls back to Espy formula where no condensation is found in the profile.

    Args:
        pmb: Pressure (level, lat, lon) in hPa.
        tc: Temperature (level, lat, lon) in Celsius.
        td: Dewpoint (level, lat, lon) in Celsius.
        z: Heights MSL (level, lat, lon).
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).

    Returns:
        LCL height MSL (m).
    """
    nz = pmb.shape[0]

    # Surface values (bottom level)
    t_sfc_k = tc[0] + 273.15
    td_sfc = td[0]
    p_sfc = pmb[0]

    # Mixing ratio at surface (conserved during dry ascent)
    e_sfc = 6.112 * np.exp(17.67 * td_sfc / (td_sfc + 243.5))
    w_sfc = 0.622 * e_sfc / np.maximum(p_sfc - e_sfc, 0.1)

    result = np.full_like(ter, -999.0, dtype=np.float32)
    found = np.zeros_like(ter, dtype=bool)

    for k in range(1, nz):
        # Parcel T at this level (dry adiabat): T_parcel = T_sfc * (p/p_sfc)^0.286
        t_parcel = t_sfc_k * (pmb[k] / np.maximum(p_sfc, 0.1)) ** 0.286
        # Parcel dewpoint from conserved mixing ratio at this pressure
        e_parcel = w_sfc * pmb[k] / (0.622 + w_sfc)
        e_parcel = np.maximum(e_parcel, 0.001)
        log_e = np.log(e_parcel / 6.112)
        td_parcel = 243.5 * log_e / (17.67 - log_e)
        t_parcel_c = t_parcel - 273.15

        condensed = (~found) & (t_parcel_c <= td_parcel)
        result = np.where(condensed, z[k], result)
        found = found | condensed

    # Where no condensation found in profile, fall back to Espy formula
    espy_lcl = ter + 125.0 * (tc[0] - td[0])
    espy_lcl = np.maximum(espy_lcl, ter)
    result = np.where(found, result, espy_lcl)

    return result.astype(np.float32)


def calc_blcl_height(pmb: np.ndarray, tc: np.ndarray,
                     qvapor_blavg: np.ndarray, z: np.ndarray,
                     ter: np.ndarray, pblh: np.ndarray) -> np.ndarray:
    """Calculate BL cloud condensation height MSL.

    Uses BL-averaged humidity to find where a parcel lifted from the surface
    with BL-average moisture would reach saturation.

    Args:
        pmb: Pressure (level, lat, lon) in hPa.
        tc: Temperature (level, lat, lon) in Celsius.
        qvapor_blavg: BL-averaged water vapor mixing ratio (lat, lon).
        z: Heights MSL (level, lat, lon).
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).

    Returns:
        BL cloud height MSL (m).
    """
    nz, ny, nx = tc.shape

    # Compute dewpoint from BL-average mixing ratio at each level's pressure
    # td = 243.5 * ln(e/6.112) / (17.67 - ln(e/6.112))
    # where e = qv * p / (0.622 + qv)

    result = np.full((ny, nx), -999.0, dtype=np.float32)
    found = np.zeros((ny, nx), dtype=bool)

    for k in range(nz):
        # Compute dewpoint using BL-avg qv at this level's pressure
        e = qvapor_blavg * pmb[k] / (0.622 + qvapor_blavg)
        e = np.maximum(e, 0.001)
        log_e = np.log(e / 6.112)
        td_bl = 243.5 * log_e / (17.67 - log_e)

        # Where environmental temp drops below this dewpoint = condensation
        condenses = (tc[k] <= td_bl) & (~found)
        result = np.where(condenses, z[k], result)
        found = found | condenses

    # Where no condensation found, set to BL top
    result = np.where(found, result, ter + pblh)
    return result


def calc_blcloudpct(qvapor: np.ndarray, qcloud: np.ndarray,
                    tc: np.ndarray, pmb: np.ndarray, z: np.ndarray,
                    ter: np.ndarray, pblh: np.ndarray,
                    cwbase_criteria: float = CWBASE_CRITERIA) -> np.ndarray:
    """Calculate BL cloud cover percentage.

    Uses DrJack's GrADS subgrid method (calc_subgrid_blcloudpct_grads_):
    per-level cloud fraction from a linear RH mapping, taking the maximum
    over all BL levels.

    Reconstructed from libncl_drjack.so — constants from .rodata:
      cloud_frac = clamp(400 * RH - 300, 0, 95)
    This gives 0% at RH=75% and linearly increases to 95% cap.

    Args:
        qvapor: Water vapor mixing ratio (level, lat, lon).
        qcloud: Cloud water mixing ratio (level, lat, lon).
        tc: Temperature in Celsius (level, lat, lon).
        pmb: Pressure in hPa (level, lat, lon).
        z: Heights MSL (level, lat, lon).
        ter: Terrain height MSL (lat, lon).
        pblh: PBL height AGL (lat, lon).
        cwbase_criteria: Cloud water threshold.

    Returns:
        Cloud cover percentage (0-95), (lat, lon).
    """
    nz, ny, nx = tc.shape
    bl_top = ter + pblh

    cloud_max = np.zeros((ny, nx), dtype=np.float32)

    for k in range(nz):
        in_bl = z[k] <= bl_top

        # Magnus formula for saturation vapor pressure (DrJack constants)
        # Fortran form: es = 6.112 * exp(17.67 * (T_K - 273.15) / (T_K - 29.65))
        # Equivalent Celsius form: es = 6.112 * exp(17.67 * tc / (tc + 243.5))
        tc_k = tc[k]
        es = 6.112 * np.exp(17.67 * tc_k / (tc_k + 243.5))

        # Saturation mixing ratio: qs = 0.622 * es / (p - 0.378 * es)
        qs = 0.622 * es / np.maximum(pmb[k] - 0.378 * es, 0.1)

        # Relative humidity (fractional)
        rh = np.clip(qvapor[k] / np.maximum(qs, 1e-10), 0.0, 1.0)

        # DrJack linear RH→cloud mapping: cloud% = clamp(400*RH - 300, 0, 95)
        cf_layer = np.clip(400.0 * rh - 300.0, 0.0, 95.0)

        # Take maximum over all BL levels
        cloud_max = np.where(in_bl, np.maximum(cloud_max, cf_layer), cloud_max)

    return cloud_max
