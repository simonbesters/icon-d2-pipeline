"""Potential Flight Distance (PFD) calculations.

Runs AFTER all other parameters are written as .data files for all timesteps.
Reads .data files, applies glider polar and weather corrections, sums distances.

Three variants:
- pfd_tot:  Simple LS-4, wstar only
- pfd_tot2: Enhanced LS-4 + weather corrections
- pfd_tot3: Same as pfd_tot2 but ASG-29E polar
"""

import glob
import logging
from pathlib import Path

import numpy as np

from ..config import (
    GLIDER_POLARS,
    PFD_BLUE_THERMAL_MIN_AGL,
    PFD_CU_CLOUDBASE_MIN_AGL,
    PFD_SIMPLE_A,
    PFD_SIMPLE_B,
    PFD_SIMPLE_C,
    PFD_SIMPLE_SRIT,
)

logger = logging.getLogger(__name__)


def _compute_polar_coefficients(polar: dict) -> tuple[float, float, float]:
    """Compute speed polar coefficients a, b, c from three-point specification.

    The polar is: sink_rate = a*v^2 + b*v + c  (v in km/h, sink in m/s)

    Then adjusted for wing loading: aw = a/A, bw = b, cw = A*c
    where A = sqrt((MDG + pilot + water) / (MDG + pilot))
    """
    v1, w1 = polar["v1"], polar["w1"]
    v2, w2 = polar["v2"], polar["w2"]
    v3, w3 = polar["v3"], polar["w3"]

    a = ((v2 - v3) * (w1 - w3) + (v3 - v1) * (w2 - w3)) / \
        (v1**2 * (v2 - v3) + v2**2 * (v3 - v1) + v3**2 * (v1 - v2))
    b = (w2 - w3 - a * (v2**2 - v3**2)) / (v2 - v3)
    c = w3 - a * v3**2 - b * v3

    # Wing loading adjustment
    scale = np.sqrt((polar["mdg"] + polar["pilot_weight"] + polar["water_ballast"]) /
                    (polar["mdg"] + polar["pilot_weight"]))
    aw = a / scale
    bw = b
    cw = scale * c

    return aw, bw, cw


def _read_data_file(filepath: Path) -> np.ndarray | None:
    """Read integer grid data from a .data file (skip 4-line header)."""
    if not filepath.exists():
        return None
    try:
        return np.loadtxt(filepath, dtype=int, skiprows=4)
    except Exception as e:
        logger.warning(f"Could not read {filepath}: {e}")
        return None


def _read_data_file_float(filepath: Path) -> np.ndarray | None:
    """Read float grid data from a .data file (skip 4-line header)."""
    if not filepath.exists():
        return None
    try:
        return np.loadtxt(filepath, skiprows=4)
    except Exception as e:
        logger.warning(f"Could not read {filepath}: {e}")
        return None


def compute_pfd_tot(out_dir: Path) -> np.ndarray | None:
    """Compute simple PFD using hardcoded NCL polar coefficients and wstar only.

    Matches the pfd() function in calc_funcs.ncl exactly:
    - Uses hardcoded polar coefficients (not derived from glider spec)
    - Uses sink rate = 1.15 m/s (not from glider polar)
    - No wing-loading adjustment
    - Closed-form speed-to-fly formula
    """
    a = PFD_SIMPLE_A
    b = PFD_SIMPLE_B
    c = PFD_SIMPLE_C

    # Find all wstar data files, sorted by time
    wstar_files = sorted(glob.glob(str(out_dir / "wstar.curr.*lst.d2.data")))
    if not wstar_files:
        logger.error("No wstar data files found for PFD calculation")
        return None

    # Check for half-hour data
    half_hour_files = sorted(glob.glob(str(out_dir / "wstar.curr.*30lst.d2.data")))
    divisor = 2 if half_hour_files else 1

    # Read first file to get dimensions
    first = _read_data_file(Path(wstar_files[0]))
    if first is None:
        return None
    ny, nx = first.shape

    pfdtot = np.zeros((ny, nx), dtype=np.float64)

    # Process all files except the last (last time step excluded, as in NCL code)
    for filepath in wstar_files[:-1]:
        wstar = _read_data_file(Path(filepath))
        if wstar is None:
            continue

        # wstar is in cm/s (metric), convert to m/s and subtract sink rate
        wssel = wstar / 100.0 - PFD_SIMPLE_SRIT
        wssel = np.maximum(wssel, 0.0)

        # NCL closed-form: dist = (wssel * sqrt((c - wssel) / a)) /
        #                         (2*wssel - 2*c - b*sqrt((c-wssel)/a)) / divisor
        sqrt_term = np.sqrt(np.maximum((c - wssel) / a, 0.0))
        denom = 2.0 * wssel - 2.0 * c - b * sqrt_term

        v_avg = np.zeros_like(wssel)
        valid = (wssel > 0.0) & (np.abs(denom) > 0.01)
        v_avg[valid] = (wssel[valid] * sqrt_term[valid] /
                        denom[valid]) / divisor

        pfdtot += v_avg
        pfdtot = pfdtot.astype(int).astype(np.float64)  # Truncate as in NCL

    return pfdtot.astype(np.float32)


def compute_pfd_tot2(out_dir: Path) -> np.ndarray | None:
    """Compute enhanced PFD using LS-4 polar with weather corrections.

    Matches the pfd2() function in calc_funcs.ncl.
    Weather corrections:
    - Zero wstar if cu cloudbase AGL < 600m
    - Zero wstar if blue thermal AGL < 800m
    - Zero wstar if rain > 0
    - Scale by sunshine: linear 100% at sunpct=50% down to 0% at sunpct=0%
    """
    return _compute_pfd_enhanced(out_dir, "LS-4")


def compute_pfd_tot3(out_dir: Path) -> np.ndarray | None:
    """Compute enhanced PFD using ASG-29E polar with weather corrections.

    Same as pfd_tot2 but with ASG-29E glider polar.
    Matches the pfd3() function in calc_funcs.ncl.
    """
    return _compute_pfd_enhanced(out_dir, "ASG-29E")


def _compute_pfd_enhanced(out_dir: Path, glider_name: str) -> np.ndarray | None:
    """Compute PFD with weather corrections for a given glider polar."""
    polar = GLIDER_POLARS[glider_name]
    aw, bw, cw = _compute_polar_coefficients(polar)
    srit = polar["sink_rate_turn"]

    # Find all required data files
    wstar_files = sorted(glob.glob(str(out_dir / "wstar.curr.*lst.d2.data")))
    if not wstar_files:
        logger.error("No wstar data files found for PFD calculation")
        return None

    # Check for half-hour data
    half_hour_files = sorted(glob.glob(str(out_dir / "wstar.curr.*30lst.d2.data")))
    divisor = 2 if half_hour_files else 1

    # Read first file to get dimensions
    first = _read_data_file(Path(wstar_files[0]))
    if first is None:
        return None
    ny, nx = first.shape

    pfdtot = np.zeros((ny, nx), dtype=np.float64)

    # Process all files except the last
    for filepath in wstar_files[:-1]:
        filepath = Path(filepath)
        # Extract the time suffix pattern from the wstar filename
        # e.g., "wstar.curr.1200lst.d2.data" -> ".curr.1200lst.d2.data"
        tail = str(filepath.name).replace("wstar", "")

        wstar = _read_data_file(filepath)
        if wstar is None:
            continue

        # Load weather correction data
        zmask = _read_data_file(out_dir / f"zsfclclmask{tail}")
        hgt = _read_data_file(out_dir / f"wrf=HGT{tail}")
        exper = _read_data_file(out_dir / f"experimental1{tail}")
        zdif = _read_data_file(out_dir / f"zsfclcldif{tail}")
        sunpct = _read_data_file(out_dir / f"sfcsunpct{tail}")
        rainmm = _read_data_file_float(out_dir / f"rain1{tail}")

        # Apply weather corrections to wstar
        if zdif is not None and zmask is not None and hgt is not None and exper is not None:
            # Where cumulus exists (zdif > 0): zero wstar if cloudbase AGL < 600m
            # Where blue (zdif <= 0): zero wstar if thermal height AGL < 800m
            cu_present = zdif > 0
            cu_low = (zmask - hgt) < PFD_CU_CLOUDBASE_MIN_AGL
            blue_low = (exper - hgt) < PFD_BLUE_THERMAL_MIN_AGL

            wstar = np.where(cu_present & cu_low, 0, wstar)
            wstar = np.where((~cu_present) & blue_low, 0, wstar)

        if rainmm is not None:
            wstar = np.where(rainmm > 0, 0, wstar)

        # Convert wstar from cm/s to m/s and subtract sink rate
        cl = wstar / 100.0 - srit
        cl = np.maximum(cl, 0.0)

        # Speed-to-fly calculation
        valid = cl > 0.0
        v_cruise = np.zeros_like(cl, dtype=np.float64)
        v_cruise[valid] = np.sqrt(np.maximum((cw - cl[valid]) / aw, 0.0))

        sink_cruise = aw * v_cruise**2 + bw * v_cruise + cw

        denom = cl - sink_cruise
        v_avg = np.zeros_like(cl, dtype=np.float64)
        nonzero_denom = valid & (np.abs(denom) > 0.01)
        v_avg[nonzero_denom] = (v_cruise[nonzero_denom] * cl[nonzero_denom] /
                                denom[nonzero_denom]) / divisor

        # Sunshine adjustment: scale linearly from 100% at sunpct=50% to 0% at sunpct=0%
        if sunpct is not None:
            # Replace missing values (-999999) with 50
            sunpct_clean = np.where(sunpct <= -999000, 50, sunpct)
            adj = np.where(sunpct_clean <= 50, sunpct_clean / 50.0, 1.0)
            v_avg = v_avg * adj

        pfdtot += v_avg
        pfdtot = pfdtot.astype(int).astype(np.float64)  # Truncate as in NCL

    return pfdtot.astype(np.float32)
