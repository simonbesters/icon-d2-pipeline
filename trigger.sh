#!/bin/bash
# Automatically trigger ICON-D2 pipeline runs when DWD data becomes available.
#
# Polls DWD open data server for a sentinel file. When it returns HTTP 200,
# the pipeline run is launched for that init hour.
#
# Usage:
#   ./trigger.sh                  # Run as daemon, auto-detect init hours
#   ./trigger.sh --once 6         # Single check for 06Z, exit after run
#
# Designed to run via cron (every 5 min) or as a long-running process.
#
# Environment:
#   INIT_HOURS       Init hours to watch (default: "0 3 6 9 12 15 18 21")
#   START_DAYS       Forecast days to run per init (default: "0 1")
#   POLL_INTERVAL    Seconds between checks (default: 300 = 5 min)
#   DWD_BASE_URL     DWD open data base URL
#   LOCK_DIR         Where to store run-complete markers (default: /tmp/icond2-triggers)
#   TRIGGER_LOG      Log file path (default: /var/log/icond2-trigger.log)

set -euo pipefail

DWD_BASE_URL="${DWD_BASE_URL:-https://opendata.dwd.de/weather/nwp/icon-d2/grib}"
INIT_HOURS="${INIT_HOURS:-0 3 6 9 12 15 18 21}"
START_DAYS="${START_DAYS:-0 1}"
POLL_INTERVAL="${POLL_INTERVAL:-300}"
LOCK_DIR="${LOCK_DIR:-/tmp/icond2-triggers}"
TRIGGER_LOG="${TRIGGER_LOG:-/var/log/icond2-trigger.log}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$LOCK_DIR"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$TRIGGER_LOG"
}

# Build a sentinel URL: T_2M at forecast hour 18 (last hour we need).
# If this file exists, all earlier hours should be available too.
sentinel_url() {
    local date_str="$1"
    local init_str="$2"
    echo "${DWD_BASE_URL}/${init_str}/t_2m/icon-d2_germany_regular-lat-lon_single-level_${date_str}${init_str}_018_2d_t_2m.grib2.bz2"
}

# Check if DWD has data for a given date + init hour
check_available() {
    local url="$1"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 --max-time 15 "$url")
    [ "$http_code" = "200" ]
}

# Lock file prevents re-running the same init hour on the same day
lock_file() {
    local date_str="$1"
    local init_hour="$2"
    echo "${LOCK_DIR}/done_${date_str}_${init_hour}z"
}

# Clean up lock files older than 2 days
cleanup_locks() {
    find "$LOCK_DIR" -name "done_*" -mtime +2 -delete 2>/dev/null || true
}

# Run the pipeline for a given init hour and all configured start days
run_pipeline() {
    local init_hour="$1"
    log "Launching pipeline for init ${init_hour}Z"

    for start_day in $START_DAYS; do
        log "  START_DAY=${start_day} OFFSET_HOUR=${init_hour}"
        START_DAY="$start_day" "$SCRIPT_DIR/run.sh" "$init_hour" 2>&1 | tee -a "$TRIGGER_LOG" || {
            log "ERROR: Pipeline failed for init ${init_hour}Z day ${start_day}"
        }
    done
}

# Process one check cycle: look at all configured init hours
check_cycle() {
    local today
    today=$(date -u +%Y%m%d)

    cleanup_locks

    for init_hour in $INIT_HOURS; do
        local init_str
        init_str=$(printf "%02d" "$init_hour")
        local lf
        lf=$(lock_file "$today" "$init_str")

        # Skip if already ran today for this init
        if [ -f "$lf" ]; then
            continue
        fi

        # Don't check init hours that are in the future
        local current_hour
        current_hour=$(date -u +%H)
        # Data is typically available ~2h after init — don't bother checking too early
        local earliest_check=$(( init_hour + 1 ))
        if [ "$current_hour" -lt "$earliest_check" ]; then
            continue
        fi

        local url
        url=$(sentinel_url "$today" "$init_str")

        if check_available "$url"; then
            log "Data available: ${today} ${init_str}Z"
            touch "$lf"
            run_pipeline "$init_hour"
        fi
    done
}

# --- Main ---

# Single-shot mode: ./trigger.sh --once 6
if [ "${1:-}" = "--once" ]; then
    init_hour="${2:?Usage: $0 --once <init_hour>}"
    init_str=$(printf "%02d" "$init_hour")
    today=$(date -u +%Y%m%d)
    url=$(sentinel_url "$today" "$init_str")

    log "Single check: ${today} ${init_str}Z"
    if check_available "$url"; then
        log "Data available — launching"
        run_pipeline "$init_hour"
    else
        log "Data not yet available"
        exit 1
    fi
    exit 0
fi

# Daemon mode: loop forever
log "ICON-D2 trigger daemon started"
log "  Init hours: $INIT_HOURS"
log "  Start days: $START_DAYS"
log "  Poll interval: ${POLL_INTERVAL}s"

while true; do
    check_cycle
    sleep "$POLL_INTERVAL"
done
