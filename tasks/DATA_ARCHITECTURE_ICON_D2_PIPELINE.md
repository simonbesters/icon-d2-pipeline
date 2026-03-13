# Data Architecture — icon-d2-pipeline

> This document describes the changes needed in the icon-d2-pipeline to adopt the new directory structure and naming conventions. Read alongside `DATA_ARCHITECTURE_BLIPMAPS_SERVER.md` for the full picture.

---

## Current output

The pipeline currently writes to:

```
/tmp/results/20260313_0102_NL2KMICOND2_0/OUT/
  wstar2.curr.0800lst.d2.body.png
  ...
```

The directory name encodes: date, time completed, grid label, day offset. The day offset (`_0`, `_1`) is relative and creates the same problems as `NL+0`.

## New output structure

```
/tmp/results/icon-d2/{run_id}/{forecast_date}/
```

Where:
- `{run_id}` = `{YYYYMMDD}T{HH}Z` — the DWD model init time, NOT when your pipeline ran
- `{forecast_date}` = `YYYYMMDD` — the calendar date this forecast covers

### Example: 03Z run on 2026-03-13

ICON-D2 03Z has 45-hour range → covers today + tomorrow + part of day after.

```
/tmp/results/icon-d2/20260313T03Z/
  20260313/
    wstar2.curr.0800lst.d2.body.png
    wstar2.curr.0830lst.d2.body.png
    ...
    wstar2.curr.1800lst.d2.body.png
    pfd_tot2.curr.0800lst.d2.body.png
    ...
    meteogram_Terlet.png
    sounding1.curr.1200lst.d2.png
  20260314/
    wstar2.curr.0800lst.d2.body.png
    ...
```

### Example: 06Z run (27-hour range)

```
/tmp/results/icon-d2/20260313T06Z/
  20260313/          ← rest of today (from ~08:00 local onward)
    wstar2.curr.0800lst.d2.body.png
    ...
  20260314/          ← early morning tomorrow (if timesteps reach into next day)
    wstar2.curr.0800lst.d2.body.png
    ...
```

## Code changes needed

### 1. config.py — add run identity

```python
# New: run identity (set by run.py from env vars)
RUN_MODEL = "icon-d2"

# Existing OFFSET_HOUR already captures the init hour
# Existing START_DAY can be used to compute forecast dates

# Output structure
# OLD: RESULTS_DIR / f"{timestamp}_NL2KMICOND2_{day_offset}" / "OUT"
# NEW: RESULTS_DIR / RUN_MODEL / run_id / forecast_date /
```

### 2. run.py — compute run_id and forecast_dates

```python
from datetime import datetime, timedelta

# Determine run identity
run_date = datetime.utcnow().strftime("%Y%m%d")  # or from env
run_hour = f"{int(os.environ.get('OFFSET_HOUR', 0)):02d}"
run_id = f"{run_date}T{run_hour}Z"

# Determine which calendar dates this run covers
max_forecast_hours = 45 if run_hour == "03" else 27
init_dt = datetime.strptime(f"{run_date}{run_hour}", "%Y%m%d%H")

forecast_dates = set()
for step_hour in range(0, max_forecast_hours + 1):
    dt = init_dt + timedelta(hours=step_hour)
    forecast_dates.add(dt.strftime("%Y%m%d"))

forecast_dates = sorted(forecast_dates)
```

### 3. output/ — split timesteps by forecast date

Currently, all timesteps for a run go into one flat directory. Now they need to be split by which calendar date they fall on.

Each timestep has a local time (e.g., `0800lst`). The mapping to forecast_date is:

```python
def timestep_to_forecast_date(timestep_local: str, run_date: str, tz_offset: int) -> str:
    """
    Map a local timestep like '0800' to a calendar date.
    
    For a 03Z run with TZ_OFFSET=1 (CET):
      - 0800lst on day 0 → run_date
      - 0800lst on day 1 → run_date + 1 day
    
    The pipeline already tracks which 'day' each timestep belongs to
    (day 0 = today, day 1 = tomorrow). Use that directly.
    """
    base = datetime.strptime(run_date, "%Y%m%d")
    # day_index is already computed by the pipeline for each timestep
    return (base + timedelta(days=day_index)).strftime("%Y%m%d")
```

In the output writers (`data_file.py`, `geotiff.py`, etc.), change the output path:

```python
# OLD
out_dir = results_dir / f"{timestamp}_NL2KMICOND2_{day_offset}" / "OUT"

# NEW
out_dir = results_dir / "icon-d2" / run_id / forecast_date
os.makedirs(out_dir, exist_ok=True)
```

### 4. Filename convention — drop the resolution suffix ambiguity

Current: `wstar2.curr.0800lst.d2.body.png` (the `2` = 2km)

Keep this unchanged for now. The viewer knows that `icon-d2` = 2km and `icon-eu`/`gfs` = 4km. The resolution suffix in the filename is redundant but harmless.

If you later port ICON-EU to this pipeline, that output would use `wstar4.curr...` (matching the existing viewer convention).

### 5. upload.sh — adapt to new structure

```bash
#!/bin/bash
# Upload a completed run to the production server
# Usage: upload.sh <run_dir>
# Example: upload.sh /tmp/results/icon-d2/20260313T03Z
set -euo pipefail

RUN_DIR="$1"
MODEL=$(basename "$(dirname "$RUN_DIR")")   # icon-d2
RUN_ID=$(basename "$RUN_DIR")               # 20260313T03Z

SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
UPLOAD_TARGET="${UPLOAD_TARGET:-blipmaps@blipmaps.nl:/data/rasp}"

echo "Uploading $MODEL/$RUN_ID..."

# Upload run directory
rsync -az -e "ssh -i $SSH_KEY" \
    "$RUN_DIR/" \
    "$UPLOAD_TARGET/$MODEL/$RUN_ID/"

# Trigger promote on remote
ssh -i "$SSH_KEY" "${UPLOAD_TARGET%%:*}" \
    "/data/rasp/scripts/promote.sh $MODEL $RUN_ID"

echo "Upload and promote complete"
```

### 6. run.sh — pass run_id to Docker

```bash
#!/bin/bash
set -euo pipefail

START_DAY="${START_DAY:-0}"
OFFSET_HOUR="${1:-0}"
TZ_OFFSET="${TZ_OFFSET:-1}"
RESULTS_DIR="${RESULTS_DIR:-/tmp/results}"
GRIB_DIR="${GRIB_DIR:-/tmp/icon_d2_grib}"

# Compute run_id
RUN_DATE=$(date -u +%Y%m%d)
RUN_ID="${RUN_DATE}T$(printf '%02d' "$OFFSET_HOUR")Z"

echo "=== ICON-D2 Pipeline ==="
echo "  Run ID:    $RUN_ID"
echo "  Start day: $START_DAY"
echo "  TZ offset: $TZ_OFFSET"

docker run --rm \
    -v "$RESULTS_DIR":"$RESULTS_DIR" \
    -v "$GRIB_DIR":"$GRIB_DIR" \
    -e START_DAY="$START_DAY" \
    -e OFFSET_HOUR="$OFFSET_HOUR" \
    -e TZ_OFFSET="$TZ_OFFSET" \
    -e RESULTS_DIR="$RESULTS_DIR" \
    -e GRIB_DIR="$GRIB_DIR" \
    -e RUN_ID="$RUN_ID" \
    icond2-pipeline:latest

RUN_DIR="$RESULTS_DIR/icon-d2/$RUN_ID"

echo "Output: $RUN_DIR"
echo "Forecast dates: $(ls "$RUN_DIR" 2>/dev/null | tr '\n' ' ')"
echo "Files: $(find "$RUN_DIR" -type f 2>/dev/null | wc -l)"

# Upload if configured
if [ -n "${UPLOAD_TARGET:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    "$SCRIPT_DIR/upload.sh" "$RUN_DIR"
fi
```

## Auto-trigger: check_and_run.sh

```bash
#!/bin/bash
# Cron: */10 * * * * /opt/icon-d2/check_and_run.sh
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
```

## Summary of changes

| File | Change |
|------|--------|
| `config.py` | Add `RUN_MODEL`, accept `RUN_ID` from env |
| `run.py` | Compute `run_id`, `forecast_dates`; pass to pipeline |
| `pipeline.py` | Pass `forecast_date` per timestep to output functions |
| `output/*.py` | Write to `{results}/{model}/{run_id}/{forecast_date}/` |
| `run.sh` | Compute and pass `RUN_ID` to Docker |
| `upload.sh` | Rsync new structure, call `promote.sh` on remote |
| `CLAUDE.md` | Update architecture docs |
| **New** | `check_and_run.sh` for auto-triggering |
