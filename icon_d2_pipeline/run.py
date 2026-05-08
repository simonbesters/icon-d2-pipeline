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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ICON_D2_MAX_LEAD_HOURS, ICON_D2_VALID_INIT_HOURS
from .download import required_max_forecast_hour, select_init_hour
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

    offset_hour_env = os.environ.get("OFFSET_HOUR")
    requested_init_hour: int | None = None
    if offset_hour_env is not None and offset_hour_env != "":
        requested_init_hour = int(offset_hour_env)
        if requested_init_hour not in ICON_D2_VALID_INIT_HOURS:
            logger.error(
                f"OFFSET_HOUR must be a valid init hour {ICON_D2_VALID_INIT_HOURS}, "
                f"got {requested_init_hour}"
            )
            sys.exit(1)

    auto_init = os.environ.get("AUTO_INIT", "1") not in ("0", "false", "False", "")
    allow_partial = os.environ.get("ALLOW_PARTIAL", "0") not in ("0", "false", "False", "")
    publication_delay = float(os.environ.get("PUBLICATION_DELAY_HOURS", "3.0"))

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

    # Use today's date for the model run, or RUN_DATE override (YYYYMMDD)
    # for backfills / reruns of older inits.
    run_date_str = os.environ.get("RUN_DATE", "")
    if run_date_str:
        try:
            run_date = datetime.strptime(run_date_str, "%Y%m%d")
        except ValueError:
            logger.error(f"RUN_DATE must be YYYYMMDD, got '{run_date_str}'")
            sys.exit(1)
    else:
        run_date = datetime.now(timezone.utc).replace(tzinfo=None)

    if auto_init:
        try:
            init_hour, day_offset = select_init_hour(
                start_day=start_day,
                tz_offset=tz_offset,
                requested_init_hour=requested_init_hour,
                publication_delay_hours=publication_delay,
                allow_partial=allow_partial,
            )
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
        if requested_init_hour is not None and (init_hour != requested_init_hour or day_offset != 0):
            req_max = ICON_D2_MAX_LEAD_HOURS[requested_init_hour]
            need = required_max_forecast_hour(start_day, tz_offset) - requested_init_hour
            logger.warning(
                f"Requested OFFSET_HOUR={requested_init_hour}Z covers only +{req_max}h, "
                f"but need +{need}h for START_DAY={start_day}. "
                f"Falling back to {init_hour:02d}Z (day offset {day_offset})."
            )
        # Shift run_date back if we picked a previous-day init; bump start_day so
        # forecast_dt = run_date + start_day still points at the original target day.
        run_date = run_date + timedelta(days=day_offset)
        start_day = start_day - day_offset
    else:
        if requested_init_hour is None:
            logger.error("AUTO_INIT=0 requires OFFSET_HOUR to be set explicitly")
            sys.exit(1)
        init_hour = requested_init_hour
        need = required_max_forecast_hour(start_day, tz_offset) - init_hour
        if need > ICON_D2_MAX_LEAD_HOURS[init_hour]:
            logger.error(
                f"OFFSET_HOUR={init_hour}Z covers only +{ICON_D2_MAX_LEAD_HOURS[init_hour]}h, "
                f"but START_DAY={start_day} needs +{need}h. Set AUTO_INIT=1 to auto-pick."
            )
            sys.exit(1)

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

    # Write a marker so run.sh can find the effective run_id.
    if success:
        run_id = f"{run_date.strftime('%Y%m%d')}T{init_hour:02d}Z"
        try:
            (results_dir / "icon-d2").mkdir(parents=True, exist_ok=True)
            (results_dir / "icon-d2" / ".last_run_id").write_text(run_id + "\n")
        except OSError as e:
            logger.warning(f"Could not write .last_run_id marker: {e}")

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
