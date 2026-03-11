#!/bin/bash
# Run ICON-D2 pipeline and optionally upload results.
#
# Usage:
#   ./run.sh                    # Run for today, init 0Z
#   ./run.sh 0 6                # Run for today, init 6Z
#   START_DAY=1 ./run.sh        # Run for tomorrow
#
# Set UPLOAD_TARGET to auto-upload after run.

set -euo pipefail

START_DAY="${START_DAY:-0}"
OFFSET_HOUR="${1:-0}"
TZ_OFFSET="${TZ_OFFSET:-1}"
RESULTS_DIR="${RESULTS_DIR:-/tmp/results}"
GRIB_DIR="${GRIB_DIR:-/tmp/icon_d2_grib}"

echo "=== ICON-D2 Pipeline ==="
echo "  Init hour: ${OFFSET_HOUR}Z"
echo "  Start day: $START_DAY"
echo "  TZ offset: $TZ_OFFSET"

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

# Find the most recent run directory
RUN_DIR=$(ls -td "$RESULTS_DIR"/*_NL2KMICOND2_* 2>/dev/null | head -1)

if [ -z "$RUN_DIR" ]; then
    echo "ERROR: No output directory found"
    exit 1
fi

echo "Output: $RUN_DIR"
echo "Files: $(find "$RUN_DIR/OUT" -type f | wc -l)"

# Upload if configured
if [ -n "${UPLOAD_TARGET:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    "$SCRIPT_DIR/upload.sh" "$RUN_DIR"
fi
