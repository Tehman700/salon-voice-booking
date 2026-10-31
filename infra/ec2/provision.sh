#!/bin/bash
# Creates the demo server in AWS with the AWS CLI. Safe to re-run: it reuses what already exists.
#
#   GIT_REF=main bash infra/ec2/provision.sh [--wait]
#
# Creates: a security group (ports 80/443 only), an IAM role + instance profile (Systems Manager
# access, no SSH), an Elastic IP, and one small EC2 instance whose first-boot script installs Docker,
# fetches this repo and starts the stack. Cost: see docs/deployment.md (about $12/month).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

TYPE="${INSTANCE_TYPE:-t3.micro}"   # t4g.micro (ARM) is ~$1.5/month cheaper when AWS has capacity
GIT_REF="${GIT_REF:-main}"
REPO_URL="${REPO_URL:-https://github.com/Tehman700/salon-voice-booking.git}"
DISK_GB="${DISK_GB:-12}"

existing="$(find_instance)"
if [ -n "$existing" ] && [ "$existing" != "None" ]; then
  echo "A $NAME server already exists ($existing). Use update.sh to deploy, or teardown.sh to remove it."
  echo "URL: https://$(site_host)"
  exit 0
fi

echo "Region: $REGION | type: $TYPE | code: $GIT_REF"

# --- network ---
vpc="$(awsq ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "$vpc" != "None" ] || { echo "No default VPC in $REGION" >&2; exit 1; }
azs="$(awsq ec2 describe-instance-type-offerings --location-type availability-zone \
  --filters "Name=instance-type,Values=$TYPE" --query 'InstanceTypeOfferings[].Location' --output text)"
subnets=()
for az in $azs; do
  subnet="$(awsq ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" "Name=availability-zone,Values=$az" "Name=default-for-az,Values=true"     --query 'Subnets[0].SubnetId' --output text)"
  [ "$subnet" = "None" ] || subnets+=("$subnet")
done
[ ${#subnets[@]} -gt 0 ] || { echo "No default subnet in an AZ that offers $TYPE" >&2; exit 1; }

sg="$(awsq ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$vpc" \
  --query 'SecurityGroups[0].GroupId' --output text)"
if [ "$sg" = "None" ]; then
  sg="$(awsq ec2 create-security-group --group-name "$SG_NAME" --vpc-id "$vpc" \
    --description "Salon Voice demo: web only (80/443), no SSH" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=$PROJECT_TAG}]" \
    --query GroupId --output text)"
  for port in 80 443; do
    aws ec2 authorize-security-group-ingress --group-id "$sg" --protocol tcp --port "$port" --cidr 0.0.0.0/0 >/dev/null
  done
  echo "Created security group $sg"
fi

# --- IAM: let Systems Manager manage the box, so there is no SSH key to lose or port to open ---
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --tags "Key=Project,Value=$PROJECT_TAG" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  echo "Created IAM role $ROLE"
fi
if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE" --tags "Key=Project,Value=$PROJECT_TAG" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  echo "Waiting for IAM to propagate..."; sleep 15
fi

# --- stable public address ---
alloc="$(awsq ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)"
if [ "$alloc" = "None" ]; then
  alloc="$(awsq ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=$PROJECT_TAG}]" \
    --query AllocationId --output text)"
  echo "Allocated Elastic IP"
fi
site="$(site_host)"

# --- machine image: Ubuntu 24.04 LTS, ARM for Graviton (…g.) types ---
arch=amd64; case "$TYPE" in *g.*) arch=arm64 ;; esac
ami="$(awsq ssm get-parameter --name "/aws/service/canonical/ubuntu/server/24.04/stable/current/$arch/hvm/ebs-gp3/ami-id" \
  --query Parameter.Value --output text)"

# --- first-boot script: our variables + bootstrap.sh ---
userdata="#!/bin/bash
export REPO_URL='$REPO_URL' GIT_REF='$GIT_REF' SITE_ADDRESS='$site' CORS_ORIGINS='${CORS_ORIGINS:-https://$site}'
$(tail -n +2 "$HERE/bootstrap.sh")"

# Small instance types are sometimes out of capacity in one zone: try each zone in turn.
id=""
for subnet in "${subnets[@]}"; do
  if id="$(aws ec2 run-instances --image-id "$ami" --instance-type "$TYPE" --subnet-id "$subnet"     --security-group-ids "$sg" --iam-instance-profile "Name=$ROLE"     --metadata-options HttpTokens=required,HttpEndpoint=enabled     --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}"     --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=$PROJECT_TAG}]"                          "ResourceType=volume,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=$PROJECT_TAG}]"     --user-data "$userdata" --query 'Instances[0].InstanceId' --output text 2>/tmp/run-instances.err | tr -d '')"; then
    break
  fi
  id=""
  echo "No capacity in subnet $subnet, trying the next zone ($(head -c 120 /tmp/run-instances.err))"
done
[ -n "$id" ] || { echo "Could not launch $TYPE in any zone. Try INSTANCE_TYPE=t3a.micro or t4g.micro." >&2; exit 1; }
echo "Launched $id"
aws ec2 wait instance-running --instance-ids "$id"
aws ec2 associate-address --instance-id "$id" --allocation-id "$alloc" >/dev/null

echo
echo "Server:  $id ($TYPE) at $(instance_ip)"
echo "API:     https://$site   (docs: https://$site/docs)"
echo "The first boot installs Docker and builds the image: allow about 5-10 minutes."
echo "Progress: bash infra/ec2/remote.sh 'tail -n 20 /var/log/salon-bootstrap.log'"

if [ "${1:-}" = "--wait" ]; then
  echo "Waiting for the API to answer..."
  for _ in $(seq 1 90); do
    if curl -fsS --max-time 8 "https://$site/health/ready" 2>/dev/null; then echo; echo "Ready."; exit 0; fi
    sleep 10
  done
  echo "Not ready after 15 minutes; check the bootstrap log (command above)." >&2
  exit 1
fi
