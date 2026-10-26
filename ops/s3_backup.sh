#!/bin/bash
# Daily backup of the OpenClaw workspace and the sentinel folder to S3, in the same
# layout as before: s3://<bucket>/backups/<UTC timestamp>/{workspace,sentinel}/
# The venv and the repo clone are left out; bootstrap rebuilds both.
#
# Usage: s3_backup.sh [--dry-run]   (--dry-run lists the uploads, writes nothing)
set -euo pipefail

BUCKET="${OPENCLAW_S3_BUCKET:-openclaw-files}"
REGION="${AWS_REGION:-us-east-1}"
AGENT_HOME="${AGENT_HOME:-/home/ubuntu}"
# A real run prints only errors, so the automation's run summary stays two lines long;
# a dry run keeps its listing.
OUTPUT=(--only-show-errors)
if [[ "${1:-}" == "--dry-run" ]]; then
  OUTPUT=(--dryrun)
fi

TIMESTAMP="$(date -u +%Y-%m-%d_%H-%M_UTC)"
DEST="s3://${BUCKET}/backups/${TIMESTAMP}"
echo "Starting backup to ${DEST}/"

aws s3 cp "${AGENT_HOME}/.openclaw/workspace/" "${DEST}/workspace/" --recursive \
  --region "${REGION}" "${OUTPUT[@]}"
aws s3 cp "${AGENT_HOME}/sentinel/" "${DEST}/sentinel/" --recursive \
  --exclude "venv/*" --exclude "src/*" --region "${REGION}" "${OUTPUT[@]}"

echo "Backup complete."
