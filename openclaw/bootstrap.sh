#!/bin/bash
# Sentinel instance bootstrap (runs once as root via EC2 user data).
#
# Installs OS packages, a Python venv, the sentinel package (at SENTINEL_REF) and
# OpenClaw, then runs the readiness gate (`sentinel health`): keys in SSM, DynamoDB
# tables, the backup bucket, CMC and Gemini. ~/sentinel/.ready exists only when the
# gate passes. It does NOT onboard OpenClaw: that is a manual first-bring-up step
# (see openclaw/README.md).
#
# Expected environment (exported by Terraform, see terraform/env/ec2/locals.tf):
#   OPENCLAW_VERSION    exact version for the installer, or latest/next
#   OPENCLAW_S3_BUCKET  backup bucket name
#   AWS_REGION          AWS region
#   SENTINEL_REF        git tag or branch of this repo to deploy
set -euo pipefail

: "${OPENCLAW_VERSION:?OPENCLAW_VERSION is required}"
: "${OPENCLAW_S3_BUCKET:?OPENCLAW_S3_BUCKET is required}"
: "${AWS_REGION:?AWS_REGION is required}"
: "${SENTINEL_REF:?SENTINEL_REF is required}"

AGENT_USER="ubuntu"
AGENT_HOME="/home/${AGENT_USER}"
SENTINEL_DIR="${AGENT_HOME}/sentinel"
SENTINEL_REPO="https://github.com/beistroff/crypto_analytic.git"
# How long the readiness gate keeps retrying transient failures.
GATE_WAIT_S=600
export DEBIAN_FRONTEND=noninteractive

# retry ATTEMPTS CMD...: rerun a network step that can fail transiently at boot,
# pausing 5, 10, 20 s between attempts.
retry() {
  local attempts="$1" pause=5 n=1
  shift
  until "$@"; do
    if ((n >= attempts)); then
      echo "FAILED after ${attempts} attempts: $*" >&2
      return 1
    fi
    echo "Attempt ${n}/${attempts} failed, retrying in ${pause}s: $*" >&2
    sleep "${pause}"
    n=$((n + 1))
    pause=$((pause * 2))
  done
}

echo "=== Sentinel bootstrap start: $(date -u +%FT%TZ) ==="

echo "[1/7] System packages"
# On first boot unattended-upgrades often holds the dpkg lock: wait for it, and retry
# package downloads, instead of failing.
APT=(apt-get -y -o DPkg::Lock::Timeout=300 -o Acquire::Retries=3)
"${APT[@]}" update
"${APT[@]}" upgrade
# Remove distro Node so it cannot conflict with the Node the OpenClaw installer provides.
"${APT[@]}" remove nodejs npm libnode-dev || true
"${APT[@]}" autoremove
"${APT[@]}" install git jq curl ca-certificates unzip python3-venv python3-pip
# Ubuntu 24.04 has no apt awscli; the AWS-maintained snap provides CLI v2.
snap wait system seed.loaded
retry 3 snap install aws-cli --classic

echo "[2/7] Project directories and Python venv"
install -d -o "${AGENT_USER}" -g "${AGENT_USER}" "${SENTINEL_DIR}"
sudo -u "${AGENT_USER}" python3 -m venv "${SENTINEL_DIR}/venv"

echo "[3/7] Environment for the agent user"
cat > /etc/profile.d/sentinel.sh <<ENVEOF
export OPENCLAW_S3_BUCKET='${OPENCLAW_S3_BUCKET}'
export AWS_REGION='${AWS_REGION}'
export AWS_DEFAULT_REGION='${AWS_REGION}'
ENVEOF
chmod 644 /etc/profile.d/sentinel.sh

echo "[4/7] Sentinel package at ${SENTINEL_REF}"
SRC_DIR="${SENTINEL_DIR}/src"
clone_sentinel() {
  rm -rf "${SRC_DIR}"
  sudo -u "${AGENT_USER}" -H git clone --quiet --depth 1 --branch "${SENTINEL_REF}" \
    "${SENTINEL_REPO}" "${SRC_DIR}"
}
retry 3 clone_sentinel
retry 3 sudo -u "${AGENT_USER}" -H "${SENTINEL_DIR}/venv/bin/pip" install --quiet -e "${SRC_DIR}[ec2]"

echo "[5/7] OpenClaw ${OPENCLAW_VERSION} (installed as ${AGENT_USER}, not root)"
# Let the user systemd service (gateway) keep running without a login session.
loginctl enable-linger "${AGENT_USER}"

# Download first, run second: nothing is piped straight into a shell.
INSTALLER="$(mktemp /tmp/openclaw-install.XXXXXX.sh)"
retry 3 curl -fsSL --proto '=https' --tlsv1.2 -o "${INSTALLER}" https://openclaw.ai/install.sh
chmod 755 "${INSTALLER}"
sudo -u "${AGENT_USER}" -H env OPENCLAW_VERSION="${OPENCLAW_VERSION}" OPENCLAW_NO_ONBOARD=1 \
  bash "${INSTALLER}" --no-onboard
rm -f "${INSTALLER}"

echo "[6/7] Verification"
sudo -u "${AGENT_USER}" -H bash -lc 'node -v && npm -v && openclaw --version' \
  || echo "WARNING: openclaw not on PATH yet; check the installer output above"
touch "${SENTINEL_DIR}/.bootstrap-done"

echo "[7/7] Readiness gate (retries transient failures for up to ${GATE_WAIT_S}s)"
# sudo resets the environment, so pass the settings the package reads explicitly.
if sudo -u "${AGENT_USER}" -H env AWS_REGION="${AWS_REGION}" \
  OPENCLAW_S3_BUCKET="${OPENCLAW_S3_BUCKET}" SENTINEL_LOG_LEVEL=INFO \
  "${SENTINEL_DIR}/venv/bin/sentinel" health --wait "${GATE_WAIT_S}"; then
  sudo -u "${AGENT_USER}" touch "${SENTINEL_DIR}/.ready"
  echo "=== Instance ready: $(date -u +%FT%TZ) ==="
  echo "Next: open an SSM session and run 'openclaw onboard' (see openclaw/README.md)."
else
  echo "=== NOT READY: see the health report above. After fixing the cause, run as ${AGENT_USER}:" >&2
  echo "    ${SENTINEL_DIR}/venv/bin/sentinel health --wait 60 && touch ${SENTINEL_DIR}/.ready" >&2
  exit 1
fi
