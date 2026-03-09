"""Write .title.json metadata files for each parameter and timestep.

These JSON files are used by the blipmaps.nl website to display
parameter information, color scales, and valid times.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from ..config import PARAM_UNITS

logger = logging.getLogger(__name__)


def write_title_json(filepath: Path, param_name: str, data: np.ndarray,
                     valid_time: datetime, forecast_time: str,
                     init_hour: int, timezone_id: str = "CET",
                     tz_offset: int = 1) -> None:
    """Write a .title.json metadata file for a parameter.

    Args:
        filepath: Output .title.json file path.
        param_name: Parameter name.
        data: 2D data array (used to compute min/max).
        valid_time: Valid time as datetime (local time).
        forecast_time: Forecast period string.
        init_hour: Model initialization hour.
        timezone_id: Timezone identifier.
        tz_offset: UTC offset (1 for CET, 2 for CEST).
    """
    unit_info = PARAM_UNITS.get(param_name, {"unit": "", "mult": 1.0})

    # Compute data statistics (excluding missing values)
    valid_data = data[np.isfinite(data) & (data > -999000)]
    data_min = float(np.min(valid_data)) if len(valid_data) > 0 else 0.0
    data_max = float(np.max(valid_data)) if len(valid_data) > 0 else 0.0

    # Convert local time to UTC for validZulu
    from datetime import timedelta
    utc_time = valid_time - timedelta(hours=tz_offset)

    meta = {
        "year": valid_time.year,
        "month": valid_time.month,
        "day": valid_time.day,
        "weekday": valid_time.strftime("%a"),
        "validLocal": valid_time.strftime("%H%M"),
        "timezone": timezone_id,
        "validZulu": utc_time.strftime("%H%Mz"),
        "fcstTime": forecast_time,
        "initTime": init_hour,
        "parameter": param_name,
        "unit": unit_info["unit"],
        "mult": unit_info["mult"],
        "min": round(data_min * unit_info["mult"], 2),
        "max": round(data_max * unit_info["mult"], 2),
    }

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(meta, f, indent=2)

    logger.debug(f"Wrote {filepath.name}")


def get_json_filename(param_name: str, valid_local_hhmm: str) -> str:
    """Generate the .title.json filename for a parameter and timestep.

    Args:
        param_name: Parameter name.
        valid_local_hhmm: Local valid time as HHMM string.

    Returns:
        Filename string.
    """
    return f"{param_name}.curr.{valid_local_hhmm}lst.d2.title.json"
