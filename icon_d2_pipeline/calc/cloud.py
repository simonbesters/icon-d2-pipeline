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

    Estimates cloud fraction within the BL based on how close the BL air
    is to saturation and whether cloud water exists.

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
        Cloud cover percentage (0-100), (lat, lon).
    """
    nz, ny, nx = tc.shape
    bl_top = ter + pblh

    # RH-based sub-grid cloud fraction estimate per layer
    # cf_layer = max(0, (RH - RH_crit) / (1 - RH_crit))^2
    # where RH_crit = 0.80 — standard approach in NWP sub-grid cloud schemes
    RH_CRIT = 0.80

    cloud_frac_sum = np.zeros((ny, nx), dtype=np.float32)
    total_layers = np.zeros((ny, nx), dtype=np.float32)

    for k in range(nz):
        in_bl = z[k] <= bl_top

        # Compute RH (fractional, 0-1)
        es = 6.112 * np.exp(17.67 * tc[k] / (tc[k] + 243.5))
        e = qvapor[k] * pmb[k] / (0.622 + qvapor[k])
        rh = np.clip(e / np.maximum(es, 0.01), 0.0, 1.0)

        # Sub-grid cloud fraction: quadratic ramp above RH_crit
        cf_layer = np.maximum((rh - RH_CRIT) / (1.0 - RH_CRIT), 0.0) ** 2

        # Also count explicit cloud water
        has_cloud = qcloud[k] >= cwbase_criteria
        cf_layer = np.maximum(cf_layer, np.where(has_cloud, 1.0, 0.0))

        cloud_frac_sum += np.where(in_bl, cf_layer, 0.0)
        total_layers += np.where(in_bl, 1.0, 0.0)

    valid = total_layers > 0
    result = np.zeros((ny, nx), dtype=np.float32)
    result[valid] = 100.0 * cloud_frac_sum[valid] / total_layers[valid]
    return result
