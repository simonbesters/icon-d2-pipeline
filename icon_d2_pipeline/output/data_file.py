"""Write .data files in the RASP format (4-line header + integer grid).

File format:
    Line 1: Title string (parameter description)
    Line 2: Grid metadata (model, region, grid, resolution, indices)
    Line 3: Projection info: "Proj= LatLon {dlat} {dlon} {lat_min} {lat_max} {lon_min} {lon_max}"
    Line 4: Date/time info + parameter metadata
    Lines 5+: Integer grid data (space-separated, one row per lat line)

Filename pattern: {param}.curr.{HHMM}lst.d2.data
"""

import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from ..config import PARAM_UNITS, REGION

logger = logging.getLogger(__name__)


def write_data_file(filepath: Path, param_name: str, data: np.ndarray,
                    grid_info: dict, valid_time: datetime,
                    forecast_time: str, init_hour: int,
                    timezone_id: str = "CET",
                    ldatafmt: int = 0,
                    tz_offset: int = 1) -> None:
    """Write a .data file in RASP format.

    Args:
        filepath: Output file path.
        param_name: Parameter name (e.g., "wstar", "hbl").
        data: 2D numpy array of values. Will be multiplied by unit mult
              and converted to integers.
        grid_info: Dict from grid.get_grid_info() with dlat, dlon, lat/lon bounds, nx, ny.
        valid_time: Valid time as datetime object (local time).
        forecast_time: Forecast period string.
        init_hour: Model initialization hour.
        timezone_id: Timezone identifier (e.g., "CET", "CEST").
        ldatafmt: Data format flag (0 = integer, 2 = float with 1 decimal).
        tz_offset: UTC offset (1 for CET, 2 for CEST).
    """
    # Get unit info
    unit_info = PARAM_UNITS.get(param_name, {"unit": "", "mult": 1.0})
    unit = unit_info["unit"]
    mult = unit_info["mult"]

    # Apply multiplier and convert
    scaled = data * mult

    # Handle NaN and missing values
    scaled = np.where(np.isnan(scaled), -999999, scaled)
    scaled = np.where(np.isinf(scaled), -999999, scaled)

    # Title line
    title = f"{_get_param_title(param_name)} [{unit}] ICON-D2 {REGION}"

    # Grid info line
    grid_line = (
        f"Model= RASP Region= {REGION}"
        f" Grid= d2 Reskm= 2.2"
        f" Indexs= 1 {grid_info['nx']} 1 {grid_info['ny']}"
        f" Proj= LatLon {grid_info['dlat']:.4f} {grid_info['dlon']:.4f}"
        f" {grid_info['lat_min']:.4f} {grid_info['lat_max']:.4f}"
        f" {grid_info['lon_min']:.4f} {grid_info['lon_max']:.4f}"
    )

    # Date/time line
    from datetime import timedelta
    weekday = valid_time.strftime("%a")
    utc_time = valid_time - timedelta(hours=tz_offset)
    date_time_line = (
        f"Day= {valid_time.year} {valid_time.month} {valid_time.day} {weekday}"
        f" ValidLST= {valid_time.strftime('%H%M')} {timezone_id}"
        f" ValidZ= {utc_time.strftime('%H%M')}z"
        f" Fcst= {forecast_time} Init= {init_hour}"
        f" Param= {param_name} Unit= {unit} Mult= 1"
    )

    # Write file
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w") as f:
        f.write(title + "\n")
        f.write(grid_line + "\n")
        f.write(grid_line + "\n")  # Line 3 is the projection line (same as grid for LatLon)
        f.write(date_time_line + "\n")

        if ldatafmt == 2:
            # Float format (for rain)
            np.savetxt(f, scaled, fmt="%.1f", delimiter=" ")
        else:
            # Integer format (default)
            int_data = np.round(scaled).astype(np.int32)
            np.savetxt(f, int_data, fmt="%d", delimiter=" ")

    logger.debug(f"Wrote {filepath.name}")


def get_data_filename(param_name: str, valid_local_hhmm: str) -> str:
    """Generate the .data filename for a parameter and timestep.

    Pattern: {param}.curr.{HHMM}lst.d2.data

    Args:
        param_name: Parameter name.
        valid_local_hhmm: Local valid time as HHMM string.

    Returns:
        Filename string.
    """
    return f"{param_name}.curr.{valid_local_hhmm}lst.d2.data"


def _get_param_title(param_name: str) -> str:
    """Get human-readable title for a parameter."""
    titles = {
        "wstar": "Thermal Updraft Velocity (W*)",
        "wstar175": "Thermal Updraft Velocity (W*)",
        "hbl": "Height of BL Top",
        "experimental1": "H_lift for 175fpm sinkrate",
        "hglider": "Thermalling Height",
        "bltopvariab": "BL Top Uncertainty/Variability (for +1degC)",
        "bsratio": "Buoyancy/Shear Ratio",
        "sfcwind0": "Wind at Surface",
        "blwind": "BL Avg Wind",
        "bltopwind": "Wind at BL Top",
        "blwindshear": "BL Vertical Wind Shear",
        "wblmaxmin": "BL Max. Up/Down Motion",
        "zwblmaxmin": "MSL Height of maxmin Wbl",
        "zsfclcl": "Cu Cloudbase (Sfc. LCL)",
        "zsfclcldif": "Cu Potential",
        "zsfclclmask": "Cu Cloudbase where Cu Potential > 0",
        "zblcl": "OvercastDevelopment Cloudbase (BL CL)",
        "zblcldif": "OvercastDevelopment Potential",
        "zblclmask": "OD Cloudbase where OD Potential > 0",
        "sfctemp": "Surface Temperature (2m AGL)",
        "sfcdewpt": "Surface Dew Point Temperature (2m AGL)",
        "sfcsunpct": "Normalized Sfc. Solar Radiation",
        "cape": "Convective Available Potential Energy (CAPE)",
        "rain1": "1Hr Accumulated Rain",
        "cfracl": "Cloud Fraction - Low",
        "cfracm": "Cloud Fraction - Mid",
        "cfrach": "Cloud Fraction - High",
        "blcloudpct": "BL Cloud Cover",
        "wrf=slp": "Mean Sea Level Pressure",
        "wrf=HGT": "Terrain Height",
        "pfd_tot": "Potential Flight Distance (LS-4 simple)",
        "pfd_tot2": "Potential Flight Distance (LS-4 enhanced)",
        "pfd_tot3": "Potential Flight Distance (ASG-29E enhanced)",
    }
    if param_name.startswith("press"):
        plev = param_name.replace("press", "")
        return f"Wind at {plev} hPa"
    return titles.get(param_name, param_name)
