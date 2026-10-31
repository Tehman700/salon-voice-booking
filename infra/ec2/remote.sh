#!/bin/bash
# Run a shell command on the demo server (through AWS Systems Manager, no SSH).
#   bash infra/ec2/remote.sh 'docker compose --env-file /opt/salon/.env -f /opt/salon/repo/infra/ec2/docker-compose.yml ps'
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
[ $# -ge 1 ] || { echo "usage: remote.sh '<command>'" >&2; exit 2; }
remote "$1"
