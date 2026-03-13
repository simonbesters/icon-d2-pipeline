#!/bin/bash
# Auto-trigger ICON-D2 pipeline when new DWD data becomes available.
# Cron: */10 * * * * /opt/icon-d2-pipeline/check_and_run.sh
set -euo pipefail

PIPELINE_DIR="/opt/icon-d2-pipeline"
STATE_DIR="/opt/icon-d2/state"
mkdir -p "$STATE_DIR"

# Runs to monitor (03Z=45h range, 06Z/09Z/12Z=27h range)
RUNS="03 06 09 12"

DATESTR=$(date -u +%Y%m%d)

for RUN in $RUNS; do
    MARKER="$STATE_DIR/.done-${DATESTR}-${RUN}z"
    [ -f "$MARKER" ] && continue

    # Last forecast step: 03Z=045, others=027
    LAST_STEP="027"
    [ "$RUN" = "03" ] && LAST_STEP="045"

    # Check if DWD has finished uploading this run
    URL="https://opendata.dwd.de/weather/nwp/icon-d2/grib/$(printf '%02d' "$RUN")/t_2m/icon-d2_germany_regular-lat-lon_single-level_${DATESTR}$(printf '%02d' "$RUN")_${LAST_STEP}_2d_t_2m.grib2.bz2"

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --head --max-time 10 "$URL" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        touch "$MARKER"
        logger -t icon-d2 "Run ${RUN}Z ${DATESTR} available, starting pipeline"
        cd "$PIPELINE_DIR"
        OFFSET_HOUR="$RUN" ./run.sh >> /var/log/icon-d2/pipeline-${DATESTR}-${RUN}z.log 2>&1 &
    fi
done

# Cleanup old markers (>3 days)
find "$STATE_DIR" -name ".done-*" -mtime +3 -delete
