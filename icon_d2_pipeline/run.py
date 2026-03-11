"""CLI entry point for the ICON-D2 soaring weather pipeline.

Reads configuration from environment variables:
    REGION:      Region name (default: NL2KMICOND2)
    START_DAY:   Forecast day offset (default: 0)
    OFFSET_HOUR: Model init hour (default: 0)
    RUN_PREFIX:  Override run prefix (optional)
    GRIB_DIR:    GRIB download directory (default: /tmp/icon_d2_grib)
    RESULTS_DIR: Results base directory (default: /tmp/results)
    TZ_OFFSET:   UTC offset for local time (default: auto-detect)
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .pipeline import run_pipeline


def main():
    """Main entry point."""
    # Configure logging
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("icon_d2_pipeline")

    # Read environment variables
    start_day = int(os.environ.get("START_DAY", "0"))
    if not 0 <= start_day <= 7:
        logger.error(f"START_DAY must be 0-7, got {start_day}")
        sys.exit(1)

    init_hour = int(os.environ.get("OFFSET_HOUR", "0"))
    if init_hour not in (0, 3, 6, 9, 12, 15, 18, 21):
        logger.error(f"OFFSET_HOUR must be a valid init hour (0,3,6,...,21), got {init_hour}")
        sys.exit(1)

    results_dir = Path(os.environ.get("RESULTS_DIR", "/tmp/results"))
    grib_dir_str = os.environ.get("GRIB_DIR", "/tmp/icon_d2_grib")
    grib_dir = Path(grib_dir_str)

    # Auto-detect timezone offset
    tz_offset_str = os.environ.get("TZ_OFFSET", "")
    if tz_offset_str:
        try:
            tz_offset = int(tz_offset_str)
        except ValueError:
            logger.error(f"TZ_OFFSET must be an integer, got '{tz_offset_str}'")
            sys.exit(1)
    else:
        # Auto-detect from system timezone
        tz_offset = _detect_tz_offset()

    # Use today's date for the model run
    run_date = datetime.now(timezone.utc).replace(tzinfo=None)

    logger.info(f"ICON-D2 Pipeline Starting")
    logger.info(f"  Init hour: {init_hour}Z")
    logger.info(f"  Start day: {start_day}")
    logger.info(f"  TZ offset: {tz_offset}")
    logger.info(f"  Run date:  {run_date.strftime('%Y-%m-%d')}")

    success = run_pipeline(
        run_date=run_date,
        init_hour=init_hour,
        start_day=start_day,
        results_dir=results_dir,
        grib_dir=grib_dir,
        tz_offset=tz_offset,
    )

    if success:
        logger.info("Pipeline completed successfully")
        sys.exit(0)
    else:
        logger.error("Pipeline failed")
        sys.exit(1)


def _detect_tz_offset() -> int:
    """Detect UTC offset for CET/CEST."""
    now = datetime.now()
    utcnow = datetime.now(timezone.utc).replace(tzinfo=None)
    diff = round((now - utcnow).total_seconds() / 3600)
    return max(1, min(diff, 2))  # Clamp to 1 (CET) or 2 (CEST)


if __name__ == "__main__":
    main()
