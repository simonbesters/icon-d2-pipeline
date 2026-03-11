"""Download ICON-D2 GRIB files from DWD open data server."""

import asyncio
import bz2
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp

from .config import (
    GRIB_2D_VARS,
    GRIB_3D_VARS,
    GRIB_INVARIANT_VARS,
    GRIB_PRESSURE_LEVEL_VARS,
    ICON_D2_BASE_URL,
    ICON_D2_NUM_LEVELS,
    ICON_D2_NUM_HALF_LEVELS,
    ICON_D2_PRESSURE_LEVELS_HPA,
)

logger = logging.getLogger(__name__)

# Mapping from our variable names to DWD directory/file naming
# Format: {var_name: (level_type, dwd_dir_name)}
# level_type: "model_level" for 3D icosahedral, "single_level" for 2D regular-lat-lon,
#             "time_invariant" for static, "pressure_level" for 3D regular-lat-lon
VAR_INFO = {
    # 3D model-level (icosahedral grid only!)
    "T": ("model_level", "t"),
    "QV": ("model_level", "qv"),
    "QC": ("model_level", "qc"),
    "P": ("model_level", "p"),
    "U": ("model_level", "u"),
    "V": ("model_level", "v"),
    "W": ("model_level", "w"),
    # 3D pressure-level (regular-lat-lon, limited variables)
    "FI": ("pressure_level", "fi"),
    "RELHUM": ("pressure_level", "relhum"),
    "OMEGA": ("pressure_level", "omega"),
    # 2D single-level (regular-lat-lon)
    "T_2M": ("single_level", "t_2m"),
    "TD_2M": ("single_level", "td_2m"),
    "U_10M": ("single_level", "u_10m"),
    "V_10M": ("single_level", "v_10m"),
    "PS": ("single_level", "ps"),
    "PMSL": ("single_level", "pmsl"),
    "ASWDIR_S": ("single_level", "aswdir_s"),
    "ASWDIFD_S": ("single_level", "aswdifd_s"),
    "TOT_PREC": ("single_level", "tot_prec"),
    "ASHFL_S": ("single_level", "ashfl_s"),
    "ALHFL_S": ("single_level", "alhfl_s"),
    "MH": ("single_level", "mh"),          # Mixing layer height (replaces HPBL)
    "CAPE_ML": ("single_level", "cape_ml"), # CAPE (directly available)
    "CLCL": ("single_level", "clcl"),       # Low cloud cover (directly available)
    "CLCM": ("single_level", "clcm"),       # Mid cloud cover
    "CLCH": ("single_level", "clch"),       # High cloud cover
    # Time-invariant (regular-lat-lon)
    "HSURF": ("time_invariant", "hsurf"),
    "HHL": ("time_invariant", "hhl"),
    "FR_LAND": ("time_invariant", "fr_land"),
    # Time-invariant (icosahedral — grid coordinates for remapping)
    "CLAT": ("time_invariant_ico", "clat"),
    "CLON": ("time_invariant_ico", "clon"),
}


def build_urls(run_date: datetime, init_hour: int, forecast_hours: list[int],
               variables: list[str]) -> list[tuple[str, str]]:
    """Build list of (url, local_path) tuples for all required GRIB files.

    Args:
        run_date: The model run date.
        init_hour: The initialization hour (0, 3, 6, 9, 12, 15, 18, 21).
        forecast_hours: List of forecast hours to download.
        variables: List of variable names to download.

    Returns:
        List of (url, local_path) tuples.
    """
    date_str = run_date.strftime("%Y%m%d")
    init_str = f"{init_hour:02d}"
    urls = []

    for var in variables:
        if var not in VAR_INFO:
            logger.warning(f"Unknown variable {var}, skipping")
            continue

        level_type, dwd_name = VAR_INFO[var]

        if level_type == "model_level":
            # 3D variables on icosahedral grid: one file per level per forecast hour
            num_levels = ICON_D2_NUM_HALF_LEVELS if var == "W" else ICON_D2_NUM_LEVELS
            for fh in forecast_hours:
                for level in range(1, num_levels + 1):
                    url = _build_model_level_url(
                        date_str, init_str, dwd_name, level, fh)
                    local = f"icon-d2_{date_str}{init_str}_{fh:03d}_{dwd_name}_ml{level:03d}.grib2"
                    urls.append((url, local))

        elif level_type == "pressure_level":
            # 3D variables on regular-lat-lon pressure levels
            for fh in forecast_hours:
                for plev in ICON_D2_PRESSURE_LEVELS_HPA:
                    url = _build_pressure_level_url(
                        date_str, init_str, dwd_name, plev, fh)
                    local = f"icon-d2_{date_str}{init_str}_{fh:03d}_{dwd_name}_pl{plev}.grib2"
                    urls.append((url, local))

        elif level_type == "single_level":
            for fh in forecast_hours:
                url = _build_single_level_url(
                    date_str, init_str, dwd_name, fh)
                local = f"icon-d2_{date_str}{init_str}_{fh:03d}_{dwd_name}_sl.grib2"
                urls.append((url, local))

        elif level_type == "time_invariant":
            # Only need forecast hour 0
            if var == "HHL":
                # HHL has one file per half-level (1-66)
                for level in range(1, ICON_D2_NUM_HALF_LEVELS + 1):
                    url = _build_time_invariant_url(
                        date_str, init_str, dwd_name, level)
                    local = f"icon-d2_{date_str}{init_str}_000_{dwd_name}_inv{level:03d}.grib2"
                    urls.append((url, local))
            else:
                url = _build_time_invariant_url(
                    date_str, init_str, dwd_name, 0)
                local = f"icon-d2_{date_str}{init_str}_000_{dwd_name}_inv.grib2"
                urls.append((url, local))

        elif level_type == "time_invariant_ico":
            # Icosahedral time-invariant (clat, clon for grid coordinates)
            url = _build_time_invariant_ico_url(
                date_str, init_str, dwd_name, 0)
            local = f"icon-d2_{date_str}{init_str}_000_{dwd_name}_ico.grib2"
            urls.append((url, local))

    return urls


def _build_model_level_url(date_str, init_str, var_name, level, fh):
    """Build URL for a model-level GRIB file (icosahedral grid)."""
    filename = (f"icon-d2_germany_icosahedral_model-level_"
                f"{date_str}{init_str}_{fh:03d}_{level}_{var_name}.grib2.bz2")
    return f"{ICON_D2_BASE_URL}{init_str}/{var_name}/{filename}"


def _build_pressure_level_url(date_str, init_str, var_name, plev, fh):
    """Build URL for a pressure-level GRIB file (regular-lat-lon grid)."""
    filename = (f"icon-d2_germany_regular-lat-lon_pressure-level_"
                f"{date_str}{init_str}_{fh:03d}_{plev}_{var_name}.grib2.bz2")
    return f"{ICON_D2_BASE_URL}{init_str}/{var_name}/{filename}"


def _build_single_level_url(date_str, init_str, var_name, fh):
    """Build URL for a single-level GRIB file (regular-lat-lon grid)."""
    filename = (f"icon-d2_germany_regular-lat-lon_single-level_"
                f"{date_str}{init_str}_{fh:03d}_2d_{var_name}.grib2.bz2")
    return f"{ICON_D2_BASE_URL}{init_str}/{var_name}/{filename}"


def _build_time_invariant_url(date_str, init_str, var_name, level=0):
    """Build URL for a time-invariant GRIB file (regular-lat-lon grid)."""
    filename = (f"icon-d2_germany_regular-lat-lon_time-invariant_"
                f"{date_str}{init_str}_000_{level}_{var_name}.grib2.bz2")
    return f"{ICON_D2_BASE_URL}{init_str}/{var_name}/{filename}"


def _build_time_invariant_ico_url(date_str, init_str, var_name, level=0):
    """Build URL for a time-invariant GRIB file (icosahedral grid)."""
    filename = (f"icon-d2_germany_icosahedral_time-invariant_"
                f"{date_str}{init_str}_000_{level}_{var_name}.grib2.bz2")
    return f"{ICON_D2_BASE_URL}{init_str}/{var_name}/{filename}"


async def _download_one(session: aiohttp.ClientSession, url: str,
                        local_path: Path, retries: int = 3) -> bool:
    """Download and decompress a single bz2-compressed GRIB file."""
    if local_path.exists():
        logger.debug(f"Already exists: {local_path.name}")
        return True

    for attempt in range(retries):
        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    logger.warning(f"Not found (404): {url}")
                    return False
                resp.raise_for_status()
                compressed = await resp.read()

            # Decompress bz2 inline
            decompressed = bz2.decompress(compressed)
            local_path.write_bytes(decompressed)
            logger.debug(f"Downloaded: {local_path.name}")
            return True

        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(f"Retry {attempt+1}/{retries} for {local_path.name}: {e}")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Failed after {retries} attempts: {local_path.name}: {e}")
                return False


async def download_all(urls: list[tuple[str, str]], output_dir: Path,
                       max_concurrent: int = 20) -> list[Path]:
    """Download all GRIB files in parallel with concurrency limit.

    Args:
        urls: List of (url, local_filename) tuples.
        output_dir: Directory to save files to.
        max_concurrent: Maximum number of concurrent downloads.

    Returns:
        List of successfully downloaded file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)
    downloaded = []

    async def _bounded_download(session, url, local_name):
        async with semaphore:
            local_path = output_dir / local_name
            success = await _download_one(session, url, local_path)
            if success:
                downloaded.append(local_path)

    import ssl
    ssl_ctx = ssl.create_default_context()
    try:
        import certifi
        ssl_ctx.load_verify_locations(certifi.where())
    except ImportError:
        raise ImportError(
            "certifi is required for SSL verification. Install it: pip install certifi"
        )
    connector = aiohttp.TCPConnector(limit=max_concurrent, ssl=ssl_ctx)
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [_bounded_download(session, url, local_name)
                 for url, local_name in urls]
        await asyncio.gather(*tasks)

    logger.info(f"Downloaded {len(downloaded)}/{len(urls)} files")
    return downloaded


def get_forecast_hours(init_hour: int, start_day: int, tz_offset: int = 1) -> list[int]:
    """Calculate forecast hours needed for the 07:30-18:00 local time window.

    Args:
        init_hour: Model initialization hour (UTC).
        start_day: Forecast day offset (0=today, 1=tomorrow, etc.).
        tz_offset: Local time offset from UTC (1 for CET, 2 for CEST).

    Returns:
        List of integer forecast hours needed.
    """
    # Local hours we need: 7 to 18 (half-hours handled by interpolation)
    local_start = 7
    local_end = 18

    # Convert to UTC hours
    utc_start = local_start - tz_offset + 24 * start_day
    utc_end = local_end - tz_offset + 24 * start_day

    # Forecast hours relative to init
    fh_start = utc_start - init_hour
    fh_end = utc_end - init_hour

    # We need one extra hour on each side for interpolation
    return list(range(max(0, fh_start), fh_end + 2))
