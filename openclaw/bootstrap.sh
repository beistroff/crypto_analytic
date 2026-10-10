#!/bin/bash
# Sentinel instance bootstrap (runs once as root via EC2 user data).
#
# Installs OS packages, a Python venv and OpenClaw. It does NOT deploy the sentinel
# package and does NOT onboard OpenClaw: both are manual first-bring-up steps
# (see openclaw/README.md).
#
# Expected environment (exported by Terraform, see terraform/env/ec2/locals.tf):
#   OPENCLAW_VERSION    exact version for the installer, or latest/next
#   OPENCLAW_S3_BUCKET  backup bucket name
#   AWS_REGION          AWS region
set -euo pipefail

: "${OPENCLAW_VERSION:?OPENCLAW_VERSION is required}"
: "${OPENCLAW_S3_BUCKET:?OPENCLAW_S3_BUCKET is required}"
: "${AWS_REGION:?AWS_REGION is required}"

AGENT_USER="ubuntu"
AGENT_HOME="/home/${AGENT_USER}"
SENTINEL_DIR="${AGENT_HOME}/sentinel"
export DEBIAN_FRONTEND=noninteractive

echo "=== Sentinel bootstrap start: $(date -u +%FT%TZ) ==="

echo "[1/5] System packages"
apt-get update
apt-get upgrade -y
# Remove distro Node so it cannot conflict with the Node the OpenClaw installer provides.
apt-get remove -y nodejs npm libnode-dev || true
apt-get autoremove -y
apt-get install -y git jq curl ca-certificates unzip python3-venv python3-pip
# Ubuntu 24.04 has no apt awscli; the AWS-maintained snap provides CLI v2.
snap install aws-cli --classic

echo "[2/5] Project directories and Python venv"
install -d -o "${AGENT_USER}" -g "${AGENT_USER}" "${SENTINEL_DIR}"
sudo -u "${AGENT_USER}" python3 -m venv "${SENTINEL_DIR}/venv"

echo "[3/5] Environment for the agent user"
cat > /etc/profile.d/sentinel.sh <<ENVEOF
export OPENCLAW_S3_BUCKET='${OPENCLAW_S3_BUCKET}'
export AWS_REGION='${AWS_REGION}'
export AWS_DEFAULT_REGION='${AWS_REGION}'
ENVEOF
chmod 644 /etc/profile.d/sentinel.sh

echo "[4/5] OpenClaw ${OPENCLAW_VERSION} (installed as ${AGENT_USER}, not root)"
# Let the user systemd service (gateway) keep running without a login session.
loginctl enable-linger "${AGENT_USER}"

# Download first, run second: nothing is piped straight into a shell.
INSTALLER="$(mktemp /tmp/openclaw-install.XXXXXX.sh)"
curl -fsSL --proto '=https' --tlsv1.2 -o "${INSTALLER}" https://openclaw.ai/install.sh
chmod 755 "${INSTALLER}"
sudo -u "${AGENT_USER}" -H env OPENCLAW_VERSION="${OPENCLAW_VERSION}" OPENCLAW_NO_ONBOARD=1 \
  bash "${INSTALLER}" --no-onboard
rm -f "${INSTALLER}"

echo "[5/5] Verification"
sudo -u "${AGENT_USER}" -H bash -lc 'node -v && npm -v && openclaw --version' \
  || echo "WARNING: openclaw not on PATH yet; check the installer output above"

touch "${SENTINEL_DIR}/.bootstrap-done"
echo "=== Bootstrap complete: $(date -u +%FT%TZ) ==="
echo "Next: open an SSM session, run 'openclaw onboard', then deploy the sentinel package."
