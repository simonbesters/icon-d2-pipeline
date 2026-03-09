"""Wind parameter calculations."""

import numpy as np


def calc_sfcwind0(u10m: np.ndarray, v10m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate surface wind speed from 10m wind components.

    Note: The original NCL 'sfcwind0' extracts the lowest model level (level 0),
    but for ICON-D2 we use the 10m diagnostic wind which is more appropriate.

    Returns:
        (u, v, speed) each (lat, lon) in m/s.
    """
    speed = np.sqrt(u10m**2 + v10m**2)
    return u10m.astype(np.float32), v10m.astype(np.float32), speed.astype(np.float32)
