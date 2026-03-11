#!/bin/bash
# Upload ICON-D2 pipeline output to remote server.
# Standalone replacement for blipmaps.nl callback system.
#
# Usage:
#   ./upload.sh /tmp/results/20260309_0700_NL2KMICOND2_0
#
# Required env vars:
#   UPLOAD_TARGET  - SCP target, e.g. user@host:/var/www/images
#   SSH_KEY        - Path to SSH private key (optional, uses default if unset)

set -euo pipefail

RESULTS_DIR="${1:?Usage: $0 /tmp/results/RUN_DIR}"

if [ ! -d "$RESULTS_DIR/OUT" ]; then
    echo "ERROR: $RESULTS_DIR/OUT not found"
    exit 1
fi

# Parse directory name: YYYYMMDD_HHMM_REGION_STARTDAY
dirname=$(basename "$RESULTS_DIR")
startDate=$(echo "$dirname" | cut -d_ -f1)
region=$(echo "$dirname" | cut -d_ -f3)
START_DAY=$(echo "$dirname" | cut -d_ -f4)

UPLOAD_TARGET="${UPLOAD_TARGET:?Set UPLOAD_TARGET env var (e.g. user@host:/var/www/images)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"

REMOTE_DIR="${UPLOAD_TARGET}/${region}/NL+${START_DAY}/"

echo "Uploading to: $REMOTE_DIR"
echo "  Region: $region"
echo "  Date: $startDate"
echo "  Day offset: $START_DAY"
echo "  Files: $(ls "$RESULTS_DIR/OUT/" | wc -l)"

# Create remote directory and upload
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o BatchMode=yes"

# Extract user@host and path from UPLOAD_TARGET
target_host="${UPLOAD_TARGET%%:*}"
target_path="${UPLOAD_TARGET#*:}"

ssh $SSH_OPTS "$target_host" "mkdir -p '${target_path}/${region}/NL+${START_DAY}'"
scp $SSH_OPTS -r "$RESULTS_DIR/OUT/"* "${REMOTE_DIR}"

# Signal completion
ssh $SSH_OPTS "$target_host" "echo 'upload complete' > '${target_path}/${region}/NL+${START_DAY}/xfer.log'"

echo "Upload complete."

# Optional: clean up local results
if [ "${CLEANUP:-0}" = "1" ]; then
    echo "Cleaning up $RESULTS_DIR..."
    rm -rf "$RESULTS_DIR"
fi
