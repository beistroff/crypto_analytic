#!/bin/bash
# s3_share_sync.sh
# Syncs redacted shareable strategy files to the S3 strategy-share folder.

# 1. Update/Refresh shareable files from master workspace
mkdir -p /home/ubuntu/.openclaw/workspace/shareable
cp /home/ubuntu/.openclaw/workspace/SOUL.md /home/ubuntu/.openclaw/workspace/shareable/
cp /home/ubuntu/.openclaw/workspace/AGENTS.md /home/ubuntu/.openclaw/workspace/shareable/
cp /home/ubuntu/.openclaw/workspace/IDENTITY.md /home/ubuntu/.openclaw/workspace/shareable/
cp /home/ubuntu/.openclaw/workspace/memory/lessons_learned.md /home/ubuntu/.openclaw/workspace/shareable/
cp /home/ubuntu/.openclaw/workspace/USER.md /home/ubuntu/.openclaw/workspace/shareable/

# 2. Re-apply redactions
sed -i 's/- \*\*Name:\*\* Andriy/- \*\*Name:\*\* [REDACTED]/g' /home/ubuntu/.openclaw/workspace/shareable/USER.md
sed -i 's/- \*\*What to call them:\*\* Andriy/- \*\*What to call them:\*\* [REDACTED]/g' /home/ubuntu/.openclaw/workspace/shareable/USER.md

# 3. Sync to S3
echo "Syncing redacted shareable files to s3://openclaw-files/strategy-share/"
aws s3 sync /home/ubuntu/.openclaw/workspace/shareable/ s3://openclaw-files/strategy-share/ --delete --region us-east-1

echo "Shareable sync complete."
