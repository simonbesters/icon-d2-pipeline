#!/bin/bash
# Run ICON-D2 pipeline and optionally upload results.
#
# Usage:
#   ./run.sh                    # Run for today, init 0Z
#   ./run.sh 6                  # Run for today, init 6Z
#   START_DAY=1 ./run.sh        # Run for tomorrow
#
# Set UPLOAD_TARGET to auto-upload after run.

set -euo pipefail

START_DAY="${START_DAY:-0}"
OFFSET_HOUR="${1:-0}"
TZ_OFFSET="${TZ_OFFSET:-1}"
RESULTS_DIR="${RESULTS_DIR:-/tmp/results}"
GRIB_DIR="${GRIB_DIR:-/tmp/icon_d2_grib}"

# Compute deterministic run_id from model init time
RUN_DATE=$(date -u +%Y%m%d)
RUN_ID="${RUN_DATE}T$(printf '%02d' "$OFFSET_HOUR")Z"
RUN_DIR="$RESULTS_DIR/icon-d2/$RUN_ID"

echo "=== ICON-D2 Pipeline ==="
echo "  Run ID:     $RUN_ID"
echo "  Init hour:  ${OFFSET_HOUR}Z"
echo "  Start day:  $START_DAY"
echo "  TZ offset:  $TZ_OFFSET"
echo "  Output dir: $RUN_DIR"

docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$RESULTS_DIR":"$RESULTS_DIR" \
    -v "$GRIB_DIR":"$GRIB_DIR" \
    -e START_DAY="$START_DAY" \
    -e OFFSET_HOUR="$OFFSET_HOUR" \
    -e TZ_OFFSET="$TZ_OFFSET" \
    -e RESULTS_DIR="$RESULTS_DIR" \
    -e GRIB_DIR="$GRIB_DIR" \
    icond2-pipeline:latest

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

# Upload if configured
if [ -n "${UPLOAD_TARGET:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    "$SCRIPT_DIR/upload.sh" "$RUN_DIR"
fi
