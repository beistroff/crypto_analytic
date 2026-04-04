#!/bin/bash
set -e

# Ensure HOME is set for cloud-init environment
export HOME=/root
export PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

echo "=== Sentinel Bootstrap Script ==="

# 1. System Updates and Tooling
echo "[1/4] Updating system packages and installing tools..."
apt-get update
apt-get upgrade -y

# Remove any pre-existing older nodejs packages to prevent conflicts with OpenClaw
apt-get remove -y nodejs npm libnode-dev || true
apt-get autoremove -y

apt-get install -y git jq awscli python3-pip curl python3-requests python3-boto3

# 2. Create project directories
echo "[2/4] Creating project structure..."
mkdir -p /home/ubuntu/sentinel/scripts
mkdir -p /home/ubuntu/sentinel/skills

# Write project files directly (injected via Terraform template)
cat << 'PYEOF' > /home/ubuntu/sentinel/scripts/market_intelligence.py
${market_intelligence}
PYEOF

cat << 'PYEOF' > /home/ubuntu/sentinel/scripts/sentinel_memory.py
${sentinel_memory}
PYEOF

# Set S3 bucket environment variable for OpenClaw
echo "export OPENCLAW_S3_BUCKET='openclaw-files'" >> /home/ubuntu/.bashrc
echo "export OPENCLAW_S3_BUCKET='openclaw-files'" >> /root/.bashrc

# Ensure correct ownership and permissions for the sentinel directory
chown -R ubuntu:ubuntu /home/ubuntu/sentinel
chmod +x /home/ubuntu/sentinel/scripts/*.py 2>/dev/null || true

# 3. Install Python dependencies
echo "[3/4] Installing Python dependencies..."
# Use pip to install any dependencies not covered by apt
pip3 install requests boto3 click

# 4. Install OpenClaw using official installer
echo "[4/4] Installing OpenClaw..."
# Install without interactive onboarding (we'll do it separately)
export OPENCLAW_NO_ONBOARD=1
yes | curl -fsSL https://openclaw.ai/install.sh | bash

# Verify installation
echo ""
echo "=== Verification ==="
node -v
npm -v
openclaw --version || echo "WARNING: openclaw command not found, may need PATH update"

echo ""
echo "=== Bootstrap Complete ==="
echo "Instance ready at $(date)"
echo "Please run 'openclaw onboard' manually to complete setup."
