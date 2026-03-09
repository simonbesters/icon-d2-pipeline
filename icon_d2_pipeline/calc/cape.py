"""CAPE (Convective Available Potential Energy) calculation."""

import numpy as np


def calc_cape(pmb: np.ndarray, tc: np.ndarray,
              td: np.ndarray) -> np.ndarray:
    """Calculate CAPE from surface parcel.

    Lifts a parcel from the surface using the surface temperature and dewpoint.
    Integrates buoyancy from LFC to EL.

    Args:
        pmb: Pressure in hPa (level, lat, lon), bottom-up.
        tc: Temperature in Celsius (level, lat, lon), bottom-up.
        td: Dewpoint in Celsius (level, lat, lon), bottom-up.

    Returns:
        CAPE in J/kg (lat, lon).
    """
    nz, ny, nx = tc.shape

    # Surface parcel properties
    t_sfc = tc[0] + 273.15  # K
    td_sfc = td[0] + 273.15  # K
    p_sfc = pmb[0]  # hPa

    # LCL pressure using Bolton (1980) approximation
    # T_LCL = 1 / (1/(Td-56) + ln(T/Td)/800) + 56
    t_lcl = 1.0 / (1.0 / (td_sfc - 56.0) + np.log(t_sfc / td_sfc) / 800.0) + 56.0
    p_lcl = p_sfc * (t_lcl / t_sfc) ** (1.0 / 0.286)

    # Lift parcel along moist adiabat above LCL
    # Use simplified moist adiabatic lapse rate
    cape = np.zeros((ny, nx), dtype=np.float32)

    # Parcel temperature at each level
    t_parcel = np.copy(t_sfc)  # Start at surface T

    for k in range(1, nz):
        p_k = pmb[k]
        t_env = tc[k] + 273.15

        # Below LCL: dry adiabat
        below_lcl = p_k > p_lcl
        # Dry adiabatic: T_parcel = T_sfc * (p/p_sfc)^0.286
        t_dry = t_sfc * (p_k / p_sfc) ** 0.286

        # Above LCL: moist adiabat (simplified)
        # Use average moist lapse rate of ~6 K/km
        dp = pmb[k - 1] - p_k  # pressure decrease (positive)
        # Approximate height change from pressure: dz ≈ 8.5 * T/p * dp (hypsometric)
        t_avg = 0.5 * (t_parcel + t_env)
        dz = 29.3 * t_avg / np.maximum(p_k, 1.0) * dp
        moist_lapse = 6.0e-3  # K/m
        t_moist = t_parcel - moist_lapse * dz

        t_parcel = np.where(below_lcl, t_dry, t_moist)

        # CAPE contribution where parcel is warmer than environment
        buoyancy = 9.81 * (t_parcel - t_env) / t_env
        positive_buoyancy = np.maximum(buoyancy, 0.0)

        # Only count above LFC (where buoyancy first becomes positive above LCL)
        above_lcl = ~below_lcl
        cape += np.where(above_lcl, positive_buoyancy * np.maximum(dz, 0.0), 0.0)

    return cape
