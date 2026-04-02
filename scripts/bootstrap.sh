#!/bin/bash
set -e

# Ensure HOME is set for cloud-init environment
export HOME=/root
export PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

echo "=== Sentinel Bootstrap Script ==="

# 1. System Updates
echo "[1/5] Updating system packages..."
apt-get update
apt-get upgrade -y
apt-get install -y git jq awscli python3-pip curl

# 2. Create project directories
echo "[2/5] Creating project structure..."
mkdir -p /home/ubuntu/sentinel/scripts
mkdir -p /home/ubuntu/sentinel/skills

# 3. Copy project files (mounted from Terraform)
echo "[3/5] Setting up project files..."
if [ -d /tmp/sentinel-files ]; then
    cp /tmp/sentinel-files/scripts/* /home/ubuntu/sentinel/scripts/ 2>/dev/null || true
    cp /tmp/sentinel-files/skills/* /home/ubuntu/sentinel/skills/ 2>/dev/null || true
    chown -R ubuntu:ubuntu /home/ubuntu/sentinel
    chmod +x /home/ubuntu/sentinel/scripts/*.py
fi

# 4. Install Python dependencies
echo "[4/5] Installing Python dependencies..."
pip3 install --upgrade pip
pip3 install requests boto3

# 5. Install OpenClaw using official installer
echo "[5/5] Installing OpenClaw..."
# Install without interactive onboarding (we'll do it separately)
export OPENCLAW_NO_ONBOARD=1
yes | curl -fsSL https://openclaw.ai/install.sh | bash

# Verify installation
echo ""
echo "=== Verification ==="
node -v
npm -v
openclaw --version || echo "WARNING: openclaw command not found, may need PATH update"

# Fetch secrets from SSM
echo ""
echo "=== Fetching credentials from SSM ==="
export TG_TOKEN=$(aws ssm get-parameter --name "/sentinel/telegram_token" --with-decryption --query "Parameter.Value" --output text --region us-east-1 2>/dev/null || echo "")
export GEMINI_KEY=$(aws ssm get-parameter --name "/sentinel/gemini_api_key" --with-decryption --query "Parameter.Value" --output text --region us-east-1 2>/dev/null || echo "")

# Automated OpenClaw onboarding
if [ -n "$TG_TOKEN" ] && [ -n "$GEMINI_KEY" ]; then
    echo "Credentials found. Starting OpenClaw onboarding..."
    # Pipe answers in order:
    # 6 = Select Google for model provider
    # (Enter) = Keep Gemini Search (already selected)
    # $GEMINI_KEY = Gemini API key
    # $TG_TOKEN = Telegram token
    # yes = Auto-answer remaining prompts
    (echo "6"; sleep 1; echo ""; sleep 1; echo "$GEMINI_KEY"; sleep 1; echo "$TG_TOKEN"; sleep 1; yes) | openclaw onboard --install-daemon 2>&1 | tee /tmp/openclaw-onboard.log
    echo "OpenClaw onboarding complete. Check /tmp/openclaw-onboard.log for details."
else
    echo "ERROR: Missing credentials in SSM. Onboarding skipped."
    echo "Please set SSM parameters:"
    echo "  /sentinel/telegram_token"
    echo "  /sentinel/gemini_api_key"
fi

echo ""
echo "=== Bootstrap Complete ==="
echo "Instance ready at $(date)"

