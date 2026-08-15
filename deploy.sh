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
ACR="acrjarvismcp$RANDOM"                          # must be globally unique, lowercase
ENVN="cae-jarvis-mcp"
APP="jarvis-trading-mcp"
KV_URL="https://kv-jarvis-lab2.vault.azure.net/"   # existing Key Vault
KV_SECRET="jarvis-trading-token"                    # secret holding the X-API-Token
# OAuth (landrycmd tenant) — set AFTER you register the app (leave blank for first deploy):
AUTH_CLIENT_ID="${AUTH_CLIENT_ID:-}"
AUTH_CLIENT_SECRET="${AUTH_CLIENT_SECRET:-}"
AUTH_TENANT_ID="${AUTH_TENANT_ID:-}"               # landrycmd / personal Default Directory tenant id
# --------------------

az account set --subscription "$SUBSCRIPTION"
az group create -n "$RG" -l "$LOCATION" -o none
az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true -o none
az acr build -r "$ACR" -t "$APP:latest" . 

az containerapp env create -n "$ENVN" -g "$RG" -l "$LOCATION" -o none 2>/dev/null || true

# First create/update WITHOUT auth to obtain the FQDN, then re-run with AUTH_* set.
az containerapp create -n "$APP" -g "$RG" --environment "$ENVN" \
  --image "$ACR.azurecr.io/$APP:latest" \
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

# Grant the app's Managed Identity read access to the Key Vault secret
PID=$(az containerapp show -n "$APP" -g "$RG" --query identity.principalId -o tsv)
az keyvault set-policy --name "${KV_URL#https://}" --object-id "$PID" --secret-permissions get 2>/dev/null \
  || echo "NOTE: grant the MI '$PID' get access on secret '$KV_SECRET' (RBAC or access policy)."

# Once the app is registered in the landrycmd tenant, re-run this block with AUTH_* set:
if [ -n "$AUTH_CLIENT_ID" ]; then
  az containerapp update -n "$APP" -g "$RG" \
    --set-env-vars \
      AUTH_CLIENT_ID="$AUTH_CLIENT_ID" \
      AUTH_TENANT_ID="$AUTH_TENANT_ID" \
      PUBLIC_BASE_URL="https://$FQDN" \
    --secrets auth-client-secret="$AUTH_CLIENT_SECRET" \
    --replace-env-vars AUTH_CLIENT_SECRET=secretref:auth-client-secret \
    -o none
  echo "auth enabled; connect from Claude at https://$FQDN/mcp"
else
  echo "NEXT: register the app in the landrycmd tenant with redirect https://$FQDN/auth/callback, then re-run with AUTH_* set."
fi
