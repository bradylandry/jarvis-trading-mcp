#!/usr/bin/env bash
# Deploy the Jarvis Trading MCP to Azure Container Apps in the gmail subscription
# (uses the credits), with OAuth on the landrycmd tenant and the backend token pulled
# from Key Vault via the app's Managed Identity. Review + fill the vars, then run.
#
# Prereqs (one-time):
#   - Backend X-API-Token stored as a Key Vault secret (see KV_SECRET below).
#   - App registration created in the LANDRYCMD tenant AFTER the first deploy gives you
#     the URL: redirect URI = https://<fqdn>/auth/callback. Then re-run with AUTH_* set.
set -euo pipefail

# ---- fill these ----
SUBSCRIPTION="Azure subscription 1 - gmail"      # the credits subscription
RG="rg-jarvis-mcp"
LOCATION="southcentralus"
# Stable across re-runs so a later deploy builds into the same registry.
# Override ACR_NAME if that name is already taken globally (5-50 lowercase letters and digits).
ACR="${ACR_NAME:-acrjarvismcp}"
ENVN="cae-jarvis-mcp"
APP="jarvis-trading-mcp"
KV_URL="https://kv-jarvis-lab2.vault.azure.net/"   # existing Key Vault
KV_SECRET="jarvis-trading-token"                    # secret holding the X-API-Token
# OAuth client secret in the same vault. The container app reads it by reference.
AUTH_KV_SECRET="jarvis-trading-auth-client-secret"
# set-policy --name is the vault name, not the host.
KV_NAME="${KV_URL#https://}"
KV_NAME="${KV_NAME%%/*}"
KV_NAME="${KV_NAME%%.vault.*}"
# OAuth (landrycmd tenant) — set AFTER you register the app (leave blank for first deploy):
AUTH_CLIENT_ID="${AUTH_CLIENT_ID:-}"
AUTH_CLIENT_SECRET="${AUTH_CLIENT_SECRET:-}"
AUTH_TENANT_ID="${AUTH_TENANT_ID:-}"               # landrycmd / personal Default Directory tenant id
# --------------------

# Fail CLOSED on half-set sign-in, before touching Azure. With an empty client secret the server's
# OAuth signing key would be derived from an empty string.
if [ -n "$AUTH_CLIENT_ID" ]; then
  if [ -z "${AUTH_CLIENT_SECRET//[[:space:]]/}" ]; then
    echo "AUTH_CLIENT_ID is set but AUTH_CLIENT_SECRET is empty; set both (or neither for the first deploy)." >&2
    exit 1
  fi
  if [ -z "${AUTH_TENANT_ID//[[:space:]]/}" ]; then
    echo "AUTH_CLIENT_ID is set but AUTH_TENANT_ID is empty; set it to the landrycmd tenant id." >&2
    exit 1
  fi
fi

AUTH_SECRET_FILE=""
CREATE_ERR=""
cleanup() {
  if [ -n "${AUTH_SECRET_FILE:-}" ]; then
    rm -f "$AUTH_SECRET_FILE"
  fi
  if [ -n "${CREATE_ERR:-}" ]; then
    rm -f "$CREATE_ERR"
  fi
}
trap cleanup EXIT

# RoleAssignmentExists means this rerun already granted the role. Any other error stops the script.
grant_role() {
  local principal="$1"
  local role="$2"
  local scope="$3"
  local err
  err=$(mktemp)
  if az role assignment create \
      --assignee-object-id "$principal" \
      --assignee-principal-type ServicePrincipal \
      --role "$role" \
      --scope "$scope" \
      -o none >"$err" 2>&1; then
    rm -f "$err"
    return 0
  fi
  if grep -q 'RoleAssignmentExists' "$err"; then
    rm -f "$err"
    return 0
  fi
  cat "$err" >&2
  rm -f "$err"
  exit 1
}

IMAGE="$ACR.azurecr.io/$APP:latest"

az account set --subscription "$SUBSCRIPTION"
az group create -n "$RG" -l "$LOCATION" -o none
# Create the registry once. A later run reuses it and still builds :latest.
if ! az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null; then
  az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true -o none
fi
az acr build -r "$ACR" -t "$APP:latest" .

az containerapp env create -n "$ENVN" -g "$RG" -l "$LOCATION" -o none 2>/dev/null || true

# First create/update WITHOUT auth to obtain the FQDN, then re-run with AUTH_* set.
# Keep going only when this name is already taken. Any other create error stops
# the script before registry changes or the image update.
CREATE_ERR=$(mktemp)
if ! az containerapp create -n "$APP" -g "$RG" --environment "$ENVN" \
  --image "$IMAGE" \
  --registry-server "$ACR.azurecr.io" \
  --ingress external --target-port 8080 \
  --min-replicas 1 --max-replicas 1 \
  --system-assigned \
  --env-vars \
    JARVIS_TRADING_API=https://trading.landrycmd.com \
    KEY_VAULT_URL="$KV_URL" \
    JARVIS_TOKEN_SECRET_NAME="$KV_SECRET" \
  -o none 2>"$CREATE_ERR"; then
  if grep -Eqi 'ContainerAppAlreadyExists|already exists' "$CREATE_ERR"; then
    echo "app exists; updating below"
  else
    cat "$CREATE_ERR" >&2
    exit 1
  fi
fi
rm -f "$CREATE_ERR"
CREATE_ERR=""

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo "App URL: https://$FQDN   (redirect URI: https://$FQDN/auth/callback)"

# A new system identity is sometimes blank on the first show. Retry briefly,
# then stop before any grant so an empty principal id is not written into a policy.
PID=""
pid_try=0
while [ "$pid_try" -lt 5 ]; do
  pid_try=$((pid_try + 1))
  PID=$(az containerapp show -n "$APP" -g "$RG" --query identity.principalId -o tsv)
  PID="${PID//[[:space:]]/}"
  if [ -n "$PID" ]; then
    break
  fi
  if [ "$pid_try" -lt 5 ]; then
    sleep 1
  fi
done
if [ -z "$PID" ]; then
  echo "identity.principalId is empty; not granting Key Vault or registry access" >&2
  exit 1
fi

# Access-policy vaults take set-policy. RBAC vaults reject set-policy, so grant
# Key Vault Secrets User on this one secret. RoleAssignmentExists is a successful rerun.
RBAC=$(az keyvault show -n "$KV_NAME" --query properties.enableRbacAuthorization -o tsv)
RBAC="${RBAC//[[:space:]]/}"
KV_RBAC=0
case "$RBAC" in
  true|True|TRUE) KV_RBAC=1 ;;
esac
if [ "$KV_RBAC" -eq 1 ]; then
  VAULT_ID=$(az keyvault show -n "$KV_NAME" --query id -o tsv)
  VAULT_ID="${VAULT_ID//[[:space:]]/}"
  if [ -z "$VAULT_ID" ]; then
    echo "key vault id is empty; cannot assign Key Vault Secrets User" >&2
    exit 1
  fi
  grant_role "$PID" "Key Vault Secrets User" "${VAULT_ID}/secrets/${KV_SECRET}"
else
  az keyvault set-policy --name "$KV_NAME" --object-id "$PID" --secret-permissions get
fi

# The client secret goes to Key Vault before any image change. It is not an az argument.
if [ -n "$AUTH_CLIENT_ID" ]; then
  AUTH_SECRET_FILE=$(mktemp)
  chmod 600 "$AUTH_SECRET_FILE"
  printf '%s' "$AUTH_CLIENT_SECRET" > "$AUTH_SECRET_FILE"
  unset AUTH_CLIENT_SECRET
  az keyvault secret set --vault-name "$KV_NAME" --name "$AUTH_KV_SECRET" --file "$AUTH_SECRET_FILE" -o none
  rm -f "$AUTH_SECRET_FILE"
  AUTH_SECRET_FILE=""
  if [ "$KV_RBAC" -eq 1 ]; then
    grant_role "$PID" "Key Vault Secrets User" "${VAULT_ID}/secrets/${AUTH_KV_SECRET}"
  fi
  az containerapp secret set -n "$APP" -g "$RG" \
    --secrets "auth-client-secret=keyvaultref:${KV_URL%/}/secrets/${AUTH_KV_SECRET},identityref:system" \
    -o none
fi

# Pull with the system identity. Do not pass the ACR admin password on argv.
# This stays immediately before the image update, after grants, so a grant error
# does not switch the running app to a registry it cannot pull from yet.
ACR_ID=$(az acr show -n "$ACR" -g "$RG" --query id -o tsv)
ACR_ID="${ACR_ID//[[:space:]]/}"
if [ -z "$ACR_ID" ]; then
  echo "registry id is empty; cannot assign AcrPull" >&2
  exit 1
fi
grant_role "$PID" "AcrPull" "$ACR_ID"
az containerapp registry set -n "$APP" -g "$RG" \
  --server "$ACR.azurecr.io" \
  --identity system \
  -o none

# Point the running app at the image this run just built.
# One --set-env-vars list: update merges those pairs and leaves the rest.
# --replace-env-vars would clear the list first and keep only its own pairs.
if [ -n "$AUTH_CLIENT_ID" ]; then
  az containerapp update -n "$APP" -g "$RG" \
    --image "$IMAGE" \
    --set-env-vars \
      JARVIS_TRADING_API=https://trading.landrycmd.com \
      KEY_VAULT_URL="$KV_URL" \
      JARVIS_TOKEN_SECRET_NAME="$KV_SECRET" \
      AUTH_CLIENT_ID="$AUTH_CLIENT_ID" \
      AUTH_TENANT_ID="$AUTH_TENANT_ID" \
      PUBLIC_BASE_URL="https://$FQDN" \
      AUTH_CLIENT_SECRET=secretref:auth-client-secret \
    -o none
  echo "auth enabled; connect from Claude at https://$FQDN/mcp"
else
  # A previous --replace-env-vars wipe drops these. Set them again and leave AUTH_* in place.
  az containerapp update -n "$APP" -g "$RG" \
    --image "$IMAGE" \
    --set-env-vars \
      JARVIS_TRADING_API=https://trading.landrycmd.com \
      KEY_VAULT_URL="$KV_URL" \
      JARVIS_TOKEN_SECRET_NAME="$KV_SECRET" \
    -o none
  echo "NEXT: register the app in the landrycmd tenant with redirect https://$FQDN/auth/callback, then re-run with AUTH_* set."
fi
