#!/bin/bash
# Upload ICON-D2 pipeline output to remote server.
#
# Usage:
#   ./upload.sh /tmp/results/icon-d2/20260313T03Z
#
# Required env vars:
#   UPLOAD_TARGET  - SCP target, e.g. user@host:/var/www/images
#   SSH_KEY        - Path to SSH private key (optional, uses default if unset)

set -euo pipefail

RUN_DIR="${1:?Usage: $0 /tmp/results/icon-d2/RUN_ID}"

# Derive model and run_id from path
RUN_ID=$(basename "$RUN_DIR")
MODEL=$(basename "$(dirname "$RUN_DIR")")

UPLOAD_TARGET="${UPLOAD_TARGET:?Set UPLOAD_TARGET env var (e.g. user@host:/var/www/images)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o BatchMode=yes"

# Extract user@host and path from UPLOAD_TARGET
target_host="${UPLOAD_TARGET%%:*}"
target_path="${UPLOAD_TARGET#*:}"

echo "Uploading: $MODEL/$RUN_ID"

# Upload each forecast_date subdirectory
for FDIR in "$RUN_DIR"/[0-9]*/; do
    [ -d "$FDIR" ] || continue
    FORECAST_DATE=$(basename "$FDIR")
    REMOTE_DIR="${target_path}/${MODEL}/${RUN_ID}/${FORECAST_DATE}"
    FCOUNT=$(find "$FDIR" -type f | wc -l)

    echo "  $FORECAST_DATE: $FCOUNT files -> $REMOTE_DIR"
    ssh $SSH_OPTS "$target_host" "mkdir -p '$REMOTE_DIR'"
    scp $SSH_OPTS -r "$FDIR"* "${UPLOAD_TARGET}/${MODEL}/${RUN_ID}/${FORECAST_DATE}/"
done

# Signal completion at run_id level
ssh $SSH_OPTS "$target_host" "echo 'upload complete $(date -u +%Y-%m-%dT%H:%M:%SZ)' > '${target_path}/${MODEL}/${RUN_ID}/xfer.log'"

echo "Upload complete."

# Optional: clean up local results
if [ "${CLEANUP:-0}" = "1" ]; then
    echo "Cleaning up $RUN_DIR..."
    rm -rf "$RUN_DIR"
fi
