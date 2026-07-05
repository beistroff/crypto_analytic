#!/bin/bash
# s3_backup.sh
# Performs a full backup of the OpenClaw workspace and the sentinel scripts to S3.

TIMESTAMP=$(date -u +%Y-%m-%d_%H-%M_UTC)

echo "Starting backup to s3://openclaw-files/backups/$TIMESTAMP/"

# Full System Backup
aws s3 cp /home/ubuntu/.openclaw/workspace/ s3://openclaw-files/backups/$TIMESTAMP/workspace/ --recursive --region us-east-1
aws s3 cp /home/ubuntu/sentinel/ s3://openclaw-files/backups/$TIMESTAMP/sentinel/ --recursive --region us-east-1

echo "Backup complete."
