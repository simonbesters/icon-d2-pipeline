#!/bin/bash
# Run ICON-D2 pipeline and promote results to /data/rasp/latest/.
#
# Usage:
#   ./run.sh                    # Auto-pick most recent init that covers today
#   ./run.sh 6                  # Prefer 6Z init (auto-fallback if it can't cover window)
#   START_DAY=1 ./run.sh        # Run for tomorrow (auto-picks 03Z — only run with +45h)
#   AUTO_INIT=0 ./run.sh 6      # Strict: fail if 6Z can't cover the window
#
# Set UPLOAD_TARGET to auto-upload after run (for remote setups).

set -euo pipefail

START_DAY="${START_DAY:-0}"
OFFSET_HOUR="${1:-${OFFSET_HOUR:-}}"
AUTO_INIT="${AUTO_INIT:-1}"
TZ_OFFSET="${TZ_OFFSET:-1}"
RESULTS_DIR="${RESULTS_DIR:-/data/rasp}"
GRIB_DIR="${GRIB_DIR:-/tmp/icon_d2_grib}"

# RUN_DATE can be overridden (YYYYMMDD) for backfills / older inits.
RUN_DATE="${RUN_DATE:-$(date -u +%Y%m%d)}"

echo "=== ICON-D2 Pipeline ==="
echo "  Requested init: ${OFFSET_HOUR:-auto}"
echo "  Run date:       $RUN_DATE"
echo "  Start day:      $START_DAY"
echo "  TZ offset:      $TZ_OFFSET"
echo "  Auto init:      $AUTO_INIT"

set +e
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$RESULTS_DIR":"$RESULTS_DIR" \
    -v "$GRIB_DIR":"$GRIB_DIR" \
    -v /root/icon-d2-pipeline/icon_d2_pipeline:/app/icon_d2_pipeline \
    -e START_DAY="$START_DAY" \
    -e OFFSET_HOUR="$OFFSET_HOUR" \
    -e AUTO_INIT="$AUTO_INIT" \
    -e TZ_OFFSET="$TZ_OFFSET" \
    -e RESULTS_DIR="$RESULTS_DIR" \
    -e GRIB_DIR="$GRIB_DIR" \
    -e RUN_DATE="$RUN_DATE" \
    -e ALLOW_PARTIAL="${ALLOW_PARTIAL:-}" \
    -e PUBLICATION_DELAY_HOURS="${PUBLICATION_DELAY_HOURS:-}" \
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

# Read effective run_id chosen by pipeline (may differ from requested due to auto-fallback)
MARKER="$RESULTS_DIR/icon-d2/.last_run_id"
if [ ! -f "$MARKER" ]; then
    echo "ERROR: Pipeline did not write $MARKER"
    exit 1
fi
RUN_ID=$(cat "$MARKER")
RUN_DIR="$RESULTS_DIR/icon-d2/$RUN_ID"
echo "  Effective run:  $RUN_ID"

# Verify output
if [ ! -d "$RUN_DIR" ]; then
    echo "ERROR: Output directory not found: $RUN_DIR"
    exit 1
fi

# Clean up GRIB files from previous runs (keep only the effective run's files).
# Doing this AFTER the run lets us use the auto-selected effective run_id;
# for the current run, the prefix matches what we just downloaded so nothing
# we still need is deleted.
CURRENT_PREFIX="icon-d2_${RUN_ID:0:8}${RUN_ID:9:2}"
if [ -d "$GRIB_DIR" ]; then
    OLD_COUNT=$(find "$GRIB_DIR" -name "icon-d2_*.grib2" \! -name "${CURRENT_PREFIX}_*" 2>/dev/null | wc -l)
    if [ "$OLD_COUNT" -gt 0 ]; then
        echo "  Cleaning $OLD_COUNT old GRIB files from $GRIB_DIR..."
        find "$GRIB_DIR" -name "icon-d2_*.grib2" \! -name "${CURRENT_PREFIX}_*" -delete
    fi
fi

echo ""
echo "Output: $RUN_DIR"
for FDIR in "$RUN_DIR"/[0-9]*/; do
    [ -d "$FDIR" ] || continue
    FDATE=$(basename "$FDIR")
    FCOUNT=$(find "$FDIR" -type f | wc -l)
    echo "  $FDATE: $FCOUNT files"
done

# Promote to /data/rasp/latest/icon-d2/$DATE/ via per-file symlinks.
# Iterating runs newest-first, each output file links to the freshest run
# that produced it. Lets a partial late-init run (e.g. 12Z afternoon)
# update the timesteps it produced while older complete runs (e.g. 06Z)
# keep their morning timesteps.
LATEST_DIR="$RESULTS_DIR/latest/icon-d2"
mkdir -p "$LATEST_DIR"

# Collect forecast dates touched by this run + already-promoted ones.
declare -A dates_to_refresh
for FORECAST_DIR in "$RUN_DIR"/[0-9]*/; do
    [ -d "$FORECAST_DIR" ] || continue
    FDATE=$(basename "$FORECAST_DIR")
    [[ "$FDATE" =~ ^[0-9]{8}$ ]] || continue
    dates_to_refresh[$FDATE]=1
done

promoted=0
for FORECAST_DATE in "${!dates_to_refresh[@]}"; do
    LATEST_DATE_DIR="$LATEST_DIR/$FORECAST_DATE"

    # Migrate from old per-day-symlink format to per-file-symlink dir.
    if [ -L "$LATEST_DATE_DIR" ]; then
        rm -f "$LATEST_DATE_DIR"
    fi
    mkdir -p "$LATEST_DATE_DIR"

    # Wipe ALL existing symlinks so the newest-run-wins walk below can re-claim
    # files that were previously claimed by older runs. Without this a newer
    # run finds every target already exists and adds zero new links.
    find "$LATEST_DATE_DIR" -maxdepth 1 -type l -delete 2>/dev/null || true

    # Walk runs newest-first, claim files not yet linked.
    # Only consider runs marked .complete — half-finished runs may contain
    # files for timesteps the pipeline didn't actually compute correctly.
    # Additionally, when the forecast_date equals the run's init day, skip
    # files whose local-time timestep is before the run's init time:
    # those are stale junk from pre-fix pipeline crashes (e.g. 09Z run
    # cannot legitimately produce a 07:30 local timestep).
    file_count=0
    for RUN in $(ls -1 "$RESULTS_DIR/icon-d2" 2>/dev/null | grep -E "^[0-9]{8}T[0-9]{2}Z$" | sort -r); do
        [ -f "$RESULTS_DIR/icon-d2/$RUN/.complete" ] || continue
        SRC="$RESULTS_DIR/icon-d2/$RUN/$FORECAST_DATE"
        [ -d "$SRC" ] || continue
        RUN_DAY="${RUN:0:8}"
        RUN_HOUR=$((10#${RUN:9:2}))
        MIN_LOCAL_HOUR=$((RUN_HOUR + TZ_OFFSET))
        # A run is "partial" for this forecast_date when its init falls AFTER
        # the start of the window (07:00 local). Partial runs compute PFD over
        # only the timesteps they have, so their aggregate (non-lst) outputs
        # would underestimate the daily total. Restrict partial runs to
        # per-timestep files.
        IS_PARTIAL=false
        if [ "$FORECAST_DATE" = "$RUN_DAY" ] && [ "$MIN_LOCAL_HOUR" -gt 7 ]; then
            IS_PARTIAL=true
        fi
        for f in "$SRC"/*; do
            [ -e "$f" ] || continue
            name=$(basename "$f")
            # Same-day pre-init timestep filter (stale junk from old crashes).
            if [ "$FORECAST_DATE" = "$RUN_DAY" ] && [[ "$name" =~ \.([0-9]{2})([0-9]{2})lst\. ]]; then
                ts_hour=$((10#${BASH_REMATCH[1]}))
                if [ "$ts_hour" -lt "$MIN_LOCAL_HOUR" ]; then
                    continue
                fi
            fi
            # Aggregate files (no "lst" in name, e.g. pfd_tot.body.png): only
            # claim from full-window runs.
            if [ "$IS_PARTIAL" = "true" ] && [[ "$name" != *lst* ]]; then
                continue
            fi
            tgt="$LATEST_DATE_DIR/$name"
            if [ ! -e "$tgt" ] && [ ! -L "$tgt" ]; then
                # Three "../" because symlink lives at latest/icon-d2/$DATE/$name
                ln -sfn "../../../icon-d2/$RUN/$FORECAST_DATE/$name" "$tgt"
                file_count=$((file_count + 1))
            fi
        done
    done
    echo "  Refreshed latest/$FORECAST_DATE: $file_count file links"
    promoted=$((promoted + 1))
done

echo "Promoted $promoted forecast dates"

# Refresh manifest.json (used by the viewer to discover available dates/runs)
if [ -x "$RESULTS_DIR/scripts/update_manifest.sh" ]; then
    "$RESULTS_DIR/scripts/update_manifest.sh"
fi

# Upload if configured (for remote setups)
if [ -n "${UPLOAD_TARGET:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    "$SCRIPT_DIR/upload.sh" "$RUN_DIR"
fi
