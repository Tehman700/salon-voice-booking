#!/bin/bash
# Deletes everything provision.sh created, so the demo stops costing money. The database is DESTROYED.
#   bash infra/ec2/teardown.sh --yes
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
[ "${1:-}" = "--yes" ] || { echo "This permanently deletes the demo server and its database. Re-run with --yes." >&2; exit 2; }

id="$(find_instance)"
if [ -n "$id" ] && [ "$id" != "None" ]; then
  aws ec2 terminate-instances --instance-ids $id >/dev/null
  echo "Terminating $id ..."
  aws ec2 wait instance-terminated --instance-ids $id
fi

alloc="$(awsq ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)"
[ "$alloc" = "None" ] || { aws ec2 release-address --allocation-id "$alloc"; echo "Released Elastic IP"; }

sg="$(awsq ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" --query 'SecurityGroups[0].GroupId' --output text)"
[ "$sg" = "None" ] || { aws ec2 delete-security-group --group-id "$sg"; echo "Deleted security group"; }

if aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam remove-role-from-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE" || true
  aws iam delete-instance-profile --instance-profile-name "$ROLE"
fi
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam detach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore || true
  aws iam delete-role --role-name "$ROLE"
  echo "Deleted IAM role"
fi
echo "All demo resources removed."
