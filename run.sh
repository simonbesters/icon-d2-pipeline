#!/bin/bash
# Run ICON-D2 pipeline and promote results to /data/rasp/latest/.
#
# Usage:
#   ./run.sh                    # Run for today, init 0Z
#   ./run.sh 6                  # Run for today, init 6Z
#   START_DAY=1 ./run.sh        # Run for tomorrow
#
# Set UPLOAD_TARGET to auto-upload after run (for remote setups).

set -euo pipefail

START_DAY="${START_DAY:-0}"
OFFSET_HOUR="${1:-0}"
TZ_OFFSET="${TZ_OFFSET:-1}"
RESULTS_DIR="${RESULTS_DIR:-/data/rasp}"
GRIB_DIR="${GRIB_DIR:-/tmp/icon_d2_grib}"

# Compute deterministic run_id from model init time.
# RUN_DATE can be overridden (YYYYMMDD) for backfills / older inits.
RUN_DATE="${RUN_DATE:-$(date -u +%Y%m%d)}"
RUN_ID="${RUN_DATE}T$(printf %02d "$OFFSET_HOUR")Z"
RUN_DIR="$RESULTS_DIR/icon-d2/$RUN_ID"

echo "=== ICON-D2 Pipeline ==="
echo "  Run ID:     $RUN_ID"
echo "  Init hour:  ${OFFSET_HOUR}Z"
echo "  Start day:  $START_DAY"
echo "  TZ offset:  $TZ_OFFSET"
echo "  Output dir: $RUN_DIR"

# Clean up GRIB files from previous runs (keep only current run)
CURRENT_PREFIX="icon-d2_${RUN_DATE}$(printf %02d "$OFFSET_HOUR")"
if [ -d "$GRIB_DIR" ]; then
    OLD_COUNT=$(find "$GRIB_DIR" -name "icon-d2_*.grib2" \! -name "${CURRENT_PREFIX}_*" 2>/dev/null | wc -l)
    if [ "$OLD_COUNT" -gt 0 ]; then
        echo "  Cleaning $OLD_COUNT old GRIB files from $GRIB_DIR..."
        find "$GRIB_DIR" -name "icon-d2_*.grib2" \! -name "${CURRENT_PREFIX}_*" -delete
    fi
fi

set +e
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$RESULTS_DIR":"$RESULTS_DIR" \
    -v "$GRIB_DIR":"$GRIB_DIR" \
    -v /root/icon-d2-pipeline/icon_d2_pipeline:/app/icon_d2_pipeline \
    -e START_DAY="$START_DAY" \
    -e OFFSET_HOUR="$OFFSET_HOUR" \
    -e TZ_OFFSET="$TZ_OFFSET" \
    -e RESULTS_DIR="$RESULTS_DIR" \
    -e GRIB_DIR="$GRIB_DIR" \
    -e RUN_DATE="$RUN_DATE" \
    icond2-pipeline:latest
DOCKER_EXIT=$?
set -e

# Treat SIGSEGV (139) during interpreter shutdown as success if output exists.
# Some C extensions (eccodes/GDAL/scipy) segfault on cleanup after the pipeline
# has already finished writing all outputs. RUN_DIR existence is the real check.
if [ "$DOCKER_EXIT" -ne 0 ] && [ "$DOCKER_EXIT" -ne 139 ]; then
    echo "ERROR: Pipeline container exited with code $DOCKER_EXIT"
    exit "$DOCKER_EXIT"
fi
if [ "$DOCKER_EXIT" -eq 139 ]; then
    echo "Note: container exited 139 (SIGSEGV during shutdown); output verified below"
fi

# Verify output
if [ ! -d "$RUN_DIR" ]; then
    echo "ERROR: Output directory not found: $RUN_DIR"
    exit 1
fi

echo ""
echo "Output: $RUN_DIR"
for FDIR in "$RUN_DIR"/[0-9]*/; do
    [ -d "$FDIR" ] || continue
    FDATE=$(basename "$FDIR")
    FCOUNT=$(find "$FDIR" -type f | wc -l)
    echo "  $FDATE: $FCOUNT files"
done

# Promote to /data/rasp/latest/ and update manifest.
# A later init hour (e.g. 15Z) cannot retro-forecast morning timesteps for
# "today", so its forecast_date dir for today contains only stub files.
# Don't downgrade an earlier complete run with a later partial one — only
# overwrite the latest symlink if the new run has at least as many files.
LATEST_DIR="$RESULTS_DIR/latest/icon-d2"
mkdir -p "$LATEST_DIR"

promoted=0
skipped=0
for FORECAST_DIR in "$RUN_DIR"/[0-9]*/; do
    [ -d "$FORECAST_DIR" ] || continue
    FORECAST_DATE=$(basename "$FORECAST_DIR")
    [[ "$FORECAST_DATE" =~ ^[0-9]{8}$ ]] || continue

    LATEST_LINK="$LATEST_DIR/$FORECAST_DATE"
    NEW_FILES=$(find "$FORECAST_DIR" -type f 2>/dev/null | wc -l)

    if [ -L "$LATEST_LINK" ]; then
        CURRENT_TARGET=$(readlink -f "$LATEST_LINK")
        if [ -d "$CURRENT_TARGET" ]; then
            CUR_FILES=$(find "$CURRENT_TARGET" -type f 2>/dev/null | wc -l)
            if [ "$NEW_FILES" -lt "$CUR_FILES" ]; then
                echo "  Skip $FORECAST_DATE: new run has $NEW_FILES files, current latest has $CUR_FILES"
                skipped=$((skipped + 1))
                continue
            fi
        fi
    fi

    ln -sfn "../../icon-d2/$RUN_ID/$FORECAST_DATE" "${LATEST_LINK}.tmp"
    mv -Tf "${LATEST_LINK}.tmp" "$LATEST_LINK"
    echo "  Promoted $FORECAST_DATE -> $RUN_ID ($NEW_FILES files)"
    promoted=$((promoted + 1))
done

echo "Promoted $promoted forecast dates ($skipped skipped)"

# Refresh manifest.json (used by the viewer to discover available dates/runs)
if [ -x "$RESULTS_DIR/scripts/update_manifest.sh" ]; then
    "$RESULTS_DIR/scripts/update_manifest.sh"
fi

# Upload if configured (for remote setups)
if [ -n "${UPLOAD_TARGET:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    "$SCRIPT_DIR/upload.sh" "$RUN_DIR"
fi
