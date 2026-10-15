#!/bin/bash
# Syncs the shareable workspace files (persona, rules, lessons, and USER.md with the name
# lines redacted) to s3://<bucket>/strategy-share/, deleting files no longer shared.
#
# Usage: s3_share_sync.sh [--dry-run]   (--dry-run still refreshes the local
#        shareable/ copy, but writes nothing to S3)
set -euo pipefail

BUCKET="${OPENCLAW_S3_BUCKET:-openclaw-files}"
REGION="${AWS_REGION:-us-east-1}"
AGENT_HOME="${AGENT_HOME:-/home/ubuntu}"
WORKSPACE="${AGENT_HOME}/.openclaw/workspace"
SHARE="${WORKSPACE}/shareable"
DRY_RUN=()
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=(--dryrun)
fi

# 1. Refresh the shareable copies from the live workspace.
mkdir -p "${SHARE}"
cp "${WORKSPACE}/SOUL.md" "${WORKSPACE}/AGENTS.md" "${WORKSPACE}/IDENTITY.md" \
  "${WORKSPACE}/memory/lessons_learned.md" "${WORKSPACE}/USER.md" "${SHARE}/"

# 2. Re-apply the redactions.
sed -i 's/^\(- \*\*Name:\*\*\).*/\1 [REDACTED]/' "${SHARE}/USER.md"
sed -i 's/^\(- \*\*What to call them:\*\*\).*/\1 [REDACTED]/' "${SHARE}/USER.md"

# 3. Sync to S3.
echo "Syncing redacted shareable files to s3://${BUCKET}/strategy-share/"
aws s3 sync "${SHARE}/" "s3://${BUCKET}/strategy-share/" --delete \
  --region "${REGION}" "${DRY_RUN[@]}"

echo "Shareable sync complete."
