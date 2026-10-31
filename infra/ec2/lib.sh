#!/bin/bash
# Shared helpers for the infra/ec2 scripts. Source it; don't run it.
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' AWS_PAGER=""   # Git Bash on Windows must not rewrite /paths in CLI args

NAME="${NAME:-salon-demo}"
PROJECT_TAG="salon-voice"
REGION="${AWS_REGION:-$(aws configure get region)}"
export AWS_DEFAULT_REGION="$REGION"
ROLE="$NAME-ec2"        # instance profile (lets the server be managed through Systems Manager, no SSH)
SG_NAME="$NAME"

# `aws ... --output text` from Windows can carry a trailing carriage return.
awsq() { aws "$@" | tr -d '\r'; }

find_instance() {
  awsq ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text
}

instance_ip() {
  awsq ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].PublicIp' --output text
}

site_host() { echo "$(instance_ip | tr . -).sslip.io"; }

# Run a shell command on the server through Systems Manager and print its output.
remote() {
  local id cmd_id json status
  id="$(find_instance)"
  [ -n "$id" ] && [ "$id" != "None" ] || { echo "No $NAME server found. Run provision.sh first." >&2; return 1; }
  json="$(python -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]]}))' "$1")"
  cmd_id="$(awsq ssm send-command --instance-ids "$id" --document-name AWS-RunShellScript \
    --parameters "$json" --timeout-seconds 900 --query 'Command.CommandId' --output text)"
  for _ in $(seq 1 180); do
    status="$(awsq ssm get-command-invocation --command-id "$cmd_id" --instance-id "$id" --query Status --output text 2>/dev/null || echo Pending)"
    case "$status" in Success|Failed|Cancelled|TimedOut) break ;; esac
    sleep 5
  done
  awsq ssm get-command-invocation --command-id "$cmd_id" --instance-id "$id" \
    --query '[StandardOutputContent,StandardErrorContent]' --output text
  [ "$status" = "Success" ] || { echo "Remote command ended with status: $status" >&2; return 1; }
}
