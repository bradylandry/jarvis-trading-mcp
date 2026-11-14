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
az containerapp create -n "$APP" -g "$RG" --environment "$ENVN" \
  --image "$IMAGE" \
  --registry-server "$ACR.azurecr.io" \
  --ingress external --target-port 8080 \
  --min-replicas 1 --max-replicas 1 \
  --system-assigned \
  --env-vars \
    JARVIS_TRADING_API=https://trading.landrycmd.com \
    KEY_VAULT_URL="$KV_URL" \
    JARVIS_TOKEN_SECRET_NAME="$KV_SECRET" \
  -o none 2>/dev/null || echo "app exists; updating below"

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo "App URL: https://$FQDN   (redirect URI: https://$FQDN/auth/callback)"

# Grant the app's Managed Identity read access to the Key Vault secret.
# --name is the vault name. A failure stops the script.
PID=$(az containerapp show -n "$APP" -g "$RG" --query identity.principalId -o tsv)
az keyvault set-policy --name "$KV_NAME" --object-id "$PID" --secret-permissions get

# Point the running app at the image this run just built.
# One --set-env-vars list: update merges those pairs and leaves the rest.
# --replace-env-vars would clear the list first and keep only its own pairs.
if [ -n "$AUTH_CLIENT_ID" ]; then
  # update_containerapp does not take --secrets. secret set stores the value.
  az containerapp secret set -n "$APP" -g "$RG" \
    --secrets "auth-client-secret=$AUTH_CLIENT_SECRET" -o none
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
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" -o none
  echo "NEXT: register the app in the landrycmd tenant with redirect https://$FQDN/auth/callback, then re-run with AUTH_* set."
fi
