#!/bin/bash
# Runs once as root on the server's first boot (provision.sh prepends the variables below).
# Installs Docker, fetches the code, generates secrets and starts the stack. Log: /var/log/salon-bootstrap.log
#
# Required: REPO_URL, GIT_REF, SITE_ADDRESS    Optional: CORS_ORIGINS
set -euo pipefail
exec > >(tee -a /var/log/salon-bootstrap.log) 2>&1
: "${REPO_URL:?}" "${GIT_REF:?}" "${SITE_ADDRESS:?}"
APP_DIR=/opt/salon
echo "=== salon bootstrap $(date -u +%FT%TZ) ==="

# A 1 GB server needs swap to survive building the Python image.
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y docker.io docker-compose-v2 git curl
systemctl enable --now docker

mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/repo/.git" ]; then
  git clone --depth 1 --branch "$GIT_REF" "$REPO_URL" "$APP_DIR/repo"
fi

# Secrets are generated here and never leave the server (or the repo).
if [ ! -f "$APP_DIR/.env" ]; then
  umask 077
  cat > "$APP_DIR/.env" <<EOF
SITE_ADDRESS=$SITE_ADDRESS
DB_PASSWORD=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
CORS_ORIGINS=${CORS_ORIGINS:-https://$SITE_ADDRESS}
GIT_REF=$GIT_REF
EOF
fi

cd "$APP_DIR/repo/infra/ec2"
docker compose --env-file "$APP_DIR/.env" up -d --build
echo "=== bootstrap finished $(date -u +%FT%TZ) ==="
