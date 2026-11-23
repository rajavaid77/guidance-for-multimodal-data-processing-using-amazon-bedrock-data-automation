#!/usr/bin/env bash
# Create a portal user. Cognito emails a temporary password; MFA (TOTP) is set up at first sign-in.
#   ./create_user.sh provider  alice@example.com PRV-1001
#   ./create_user.sh examiner  bob@example.com
set -euo pipefail
ROLE="${1:?role: provider|examiner}"; EMAIL="${2:?email}"; PROVIDER_ID="${3:-}"
STACK="${STACK_NAME:-agentic-claims-v2}"; REGION="${AWS_REGION:-us-west-2}"
POOL=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)

ATTRS=(Name=email,Value="$EMAIL" Name=email_verified,Value=true)
case "$ROLE" in
  provider) GROUP=providers; [[ -n "$PROVIDER_ID" ]] || { echo "provider_id required (e.g. PRV-1001)"; exit 1; }
            ATTRS+=(Name=custom:provider_id,Value="$PROVIDER_ID");;
  examiner) GROUP=examiners;;
  *) echo "role must be provider or examiner"; exit 1;;
esac

aws cognito-idp admin-create-user --region "$REGION" --user-pool-id "$POOL" --username "$EMAIL" \
  --user-attributes "${ATTRS[@]}" --desired-delivery-mediums EMAIL >/dev/null
aws cognito-idp admin-add-user-to-group --region "$REGION" --user-pool-id "$POOL" --username "$EMAIL" --group-name "$GROUP"
echo "Created $EMAIL in group $GROUP. A temporary password was emailed by Cognito."
