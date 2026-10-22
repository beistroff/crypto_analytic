#!/bin/bash
# Daily backup of the OpenClaw workspace and the sentinel folder to S3, in the same
# layout as before: s3://<bucket>/backups/<UTC timestamp>/{workspace,sentinel}/
# The venv and the repo clone are left out; bootstrap rebuilds both. The real DynamoDB
# table (trades, positions, starting cash) is exported as JSON into the same folder,
# under dynamodb/.
#
# Usage: s3_backup.sh [--dry-run]   (--dry-run lists the uploads, writes nothing)
set -euo pipefail

BUCKET="${OPENCLAW_S3_BUCKET:-openclaw-files}"
REGION="${AWS_REGION:-us-east-1}"
AGENT_HOME="${AGENT_HOME:-/home/ubuntu}"
DRY_RUN=()
EXPORT_DRY_RUN=()
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=(--dryrun)
  EXPORT_DRY_RUN=(--dry-run)
fi

TIMESTAMP="$(date -u +%Y-%m-%d_%H-%M_UTC)"
DEST="s3://${BUCKET}/backups/${TIMESTAMP}"
echo "Starting backup to ${DEST}/"

aws s3 cp "${AGENT_HOME}/.openclaw/workspace/" "${DEST}/workspace/" --recursive \
  --region "${REGION}" "${DRY_RUN[@]}"
aws s3 cp "${AGENT_HOME}/sentinel/" "${DEST}/sentinel/" --recursive \
  --exclude "venv/*" --exclude "src/*" --region "${REGION}" "${DRY_RUN[@]}"
"${AGENT_HOME}/sentinel/venv/bin/sentinel" backup export --stamp "${TIMESTAMP}" \
  --format telegram "${EXPORT_DRY_RUN[@]}"

echo "Backup complete."
