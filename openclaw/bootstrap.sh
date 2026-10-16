#!/bin/bash
# Sentinel instance bootstrap (runs once as root via EC2 user data).
#
# Installs OS packages, a Python venv and the sentinel package (at SENTINEL_REF), runs
# the readiness gate (`sentinel health`: keys in SSM, DynamoDB tables, the backup
# bucket, CMC and Gemini), then installs OpenClaw. The gate runs before OpenClaw so a
# bad key or missing table fails within minutes. ~/sentinel/.ready is written when the
# gate passed and the OpenClaw installer finished; whether `openclaw` is on PATH is only
# warned about (the installer may set PATH for login shells only), so check it with
# `openclaw --version`. It does NOT onboard OpenClaw: that is a manual first-bring-up
# step (see openclaw/README.md).
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
# pausing 5, 10, 20 s between attempts (for tools without a retry option of their own).
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

echo "[1/6] System packages"
# On first boot unattended-upgrades often holds the dpkg lock: wait for it, and retry
# package downloads, instead of failing. A changed config file keeps the local version
# without asking (user data has no terminal, so a dpkg prompt would fail the upgrade).
APT=(apt-get -y -o DPkg::Lock::Timeout=300 -o Acquire::Retries=3
  -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
"${APT[@]}" update
"${APT[@]}" upgrade
"${APT[@]}" install git jq curl ca-certificates unzip python3-venv python3-pip
# Ubuntu 24.04 has no apt awscli; the AWS-maintained snap provides CLI v2.
snap wait system seed.loaded
retry 3 snap install aws-cli --classic

echo "[2/6] Project directories and Python venv"
install -d -o "${AGENT_USER}" -g "${AGENT_USER}" "${SENTINEL_DIR}"
sudo -u "${AGENT_USER}" python3 -m venv "${SENTINEL_DIR}/venv"

echo "[3/6] Environment for the agent user"
cat > /etc/profile.d/sentinel.sh <<ENVEOF
export OPENCLAW_S3_BUCKET='${OPENCLAW_S3_BUCKET}'
export AWS_REGION='${AWS_REGION}'
export AWS_DEFAULT_REGION='${AWS_REGION}'
ENVEOF
chmod 644 /etc/profile.d/sentinel.sh

echo "[4/6] Sentinel package at ${SENTINEL_REF}"
SRC_DIR="${SENTINEL_DIR}/src"
clone_sentinel() {
  rm -rf "${SRC_DIR}"
  sudo -u "${AGENT_USER}" -H git clone --quiet --depth 1 --branch "${SENTINEL_REF}" \
    "${SENTINEL_REPO}" "${SRC_DIR}"
}
retry 3 clone_sentinel
# constraints.txt pins the exact versions tested in CI, so a boot never pulls new releases.
retry 3 sudo -u "${AGENT_USER}" -H "${SENTINEL_DIR}/venv/bin/pip" install --quiet \
  -c "${SRC_DIR}/constraints.txt" -e "${SRC_DIR}[ec2]"

echo "[5/6] Readiness gate (retries transient failures for up to ${GATE_WAIT_S}s)"
# sudo resets the environment, so pass the settings the package reads explicitly.
if ! sudo -u "${AGENT_USER}" -H env AWS_REGION="${AWS_REGION}" \
  OPENCLAW_S3_BUCKET="${OPENCLAW_S3_BUCKET}" SENTINEL_LOG_LEVEL=INFO \
  "${SENTINEL_DIR}/venv/bin/sentinel" health --wait "${GATE_WAIT_S}"; then
  echo "=== NOT READY: see the health report above. OpenClaw was not installed." >&2
  echo "    Fix the cause, then rerun the whole bootstrap as root:" >&2
  echo "    sudo cloud-init single --name scripts_user --frequency always" >&2
  exit 1
fi

echo "[6/6] OpenClaw ${OPENCLAW_VERSION} (installed as ${AGENT_USER}, not root)"
# The gateway alone takes about 1 GB; on a 2 GB instance an agent turn pushed it into the
# OOM killer, so add 2 GB of swap (once).
if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
# Let the user systemd service (gateway) keep running without a login session.
loginctl enable-linger "${AGENT_USER}"
# Download first, run second: nothing is piped straight into a shell.
INSTALLER="$(mktemp /tmp/openclaw-install.XXXXXX.sh)"
curl -fsSL --retry 3 --retry-all-errors --proto '=https' --tlsv1.2 \
  -o "${INSTALLER}" https://openclaw.ai/install.sh
chmod 755 "${INSTALLER}"
sudo -u "${AGENT_USER}" -H env OPENCLAW_VERSION="${OPENCLAW_VERSION}" OPENCLAW_NO_ONBOARD=1 \
  bash "${INSTALLER}" --no-onboard
rm -f "${INSTALLER}"
sudo -u "${AGENT_USER}" -H bash -lc 'node -v && npm -v && openclaw --version' \
  || echo "WARNING: openclaw not on PATH yet; check the installer output above"

sudo -u "${AGENT_USER}" touch "${SENTINEL_DIR}/.ready"
echo "=== Instance ready: $(date -u +%FT%TZ) ==="
echo "Next: open an SSM session and run 'openclaw onboard' (see openclaw/README.md)."
