"""Parse sitedata.ncl CSV format for soaring site locations."""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Site:
    """A soaring site location."""
    id: int
    name: str
    domain: str
    lon: float
    lat: float


def parse_sitedata(filepath: Path) -> list[Site]:
    """Parse a sitedata.ncl file.

    Format: id,name,domain,lon,lat,
    Lines starting with # are comments.

    Args:
        filepath: Path to sitedata.ncl file.

    Returns:
        List of Site objects.
    """
    sites = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rstrip(",").split(",")
            if len(parts) < 5:
                continue
            try:
                site = Site(
                    id=int(parts[0]),
                    name=parts[1],
                    domain=parts[2],
                    lon=float(parts[3]),
                    lat=float(parts[4]),
                )
                sites.append(site)
            except (ValueError, IndexError) as e:
                logger.debug(f"Skipping line: {line} ({e})")
                continue

    logger.info(f"Loaded {len(sites)} sites from {filepath.name}")
    return sites


def find_nearest_gridpoint(site: Site, lat: 'np.ndarray',
                           lon: 'np.ndarray') -> tuple[int, int]:
    """Find the nearest grid point (j, i) for a site.

    Args:
        site: Site object with lat/lon.
        lat: 1D latitude array.
        lon: 1D longitude array.

    Returns:
        (j_index, i_index) into the 2D grid.
    """
    import numpy as np
    j = int(np.argmin(np.abs(lat - site.lat)))
    i = int(np.argmin(np.abs(lon - site.lon)))
    return j, i
