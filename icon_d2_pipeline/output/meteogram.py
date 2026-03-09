"""Meteogram PNG generation for soaring sites.

Generates vertical time-series plots showing:
- wstar, BL height, cloud base
- Wind barbs
- Temperature/dewpoint
- PFD

This is the most complex output and can be deferred for initial deployment.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MeteogramData:
    """Time series data for a single site."""
    site_name: str
    times: list[str]  # HHMM local
    wstar: np.ndarray  # m/s
    hbl: np.ndarray  # m MSL
    sfctemp: np.ndarray  # C
    sfcdewpt: np.ndarray  # C
    cloud_base: np.ndarray  # m MSL (zsfclcl)
    wind_u: np.ndarray  # m/s at various heights
    wind_v: np.ndarray  # m/s at various heights
    wind_heights: np.ndarray  # heights for wind profiles


def generate_meteogram(data: MeteogramData, output_path: Path,
                       valid_date: datetime) -> None:
    """Generate a meteogram PNG for a single site.

    Args:
        data: MeteogramData with time series.
        output_path: Path for the output PNG file.
        valid_date: Date for the title.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping meteogram generation")
        return

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    fig.suptitle(f"{data.site_name} - {valid_date.strftime('%Y-%m-%d')}",
                 fontsize=14, fontweight="bold")

    ntimes = len(data.times)
    x = np.arange(ntimes)
    labels = data.times

    # Panel 1: Heights (BL, cloud base)
    ax1 = axes[0]
    ax1.fill_between(x, 0, data.hbl, alpha=0.3, color="skyblue", label="BL Height")
    valid_cb = data.cloud_base > 0
    if np.any(valid_cb):
        ax1.scatter(x[valid_cb], data.cloud_base[valid_cb],
                    marker="_", s=100, color="gray", label="Cloud Base", zorder=5)
    ax1.set_ylabel("Height MSL (m)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.set_ylim(bottom=0)

    # Panel 2: wstar
    ax2 = axes[1]
    wstar_cms = data.wstar * 100  # Convert to cm/s for display
    ax2.bar(x, wstar_cms, color="orange", alpha=0.7, label="W*")
    ax2.set_ylabel("W* (cm/s)")
    ax2.axhline(y=89, color="red", linestyle="--", linewidth=0.5, label="175 fpm")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.set_ylim(bottom=0)

    # Panel 3: Temperature
    ax3 = axes[2]
    ax3.plot(x, data.sfctemp, "r-", label="Temp", linewidth=1.5)
    ax3.plot(x, data.sfcdewpt, "g--", label="Dewpoint", linewidth=1.5)
    ax3.set_ylabel("Temperature (C)")
    ax3.legend(loc="upper left", fontsize=8)

    ax3.set_xticks(x)
    ax3.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax3.set_xlabel("Local Time")

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=100, bbox_inches="tight")
    plt.close(fig)
    logger.debug(f"Wrote meteogram: {output_path.name}")
