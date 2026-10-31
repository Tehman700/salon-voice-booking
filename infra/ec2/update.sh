#!/bin/bash
# Deploy the latest code to the demo server: pull the branch, rebuild, restart (migrations run first).
#   GIT_REF=main bash infra/ec2/update.sh
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
REF="${GIT_REF:-main}"
echo "Deploying $REF to $(site_host) ..."
remote "set -e
cd /opt/salon/repo
git fetch --depth 1 origin '$REF'
git checkout -q -f FETCH_HEAD
cd infra/ec2
docker compose --env-file /opt/salon/.env up -d --build
docker image prune -f >/dev/null
docker compose --env-file /opt/salon/.env ps"
echo "Done: https://$(site_host)/health/ready"
