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
# kv-jarvis-lab2 may live outside that subscription. Export KV_SUBSCRIPTION to override.
KV_SUBSCRIPTION="${KV_SUBSCRIPTION:-$SUBSCRIPTION}"
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
# OAuth (landrycmd tenant). Set AFTER you register the app (leave blank for first deploy):
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
# Keep the value in this shell for the printf below. Child processes, including
# az acr build, must not inherit it.
export -n AUTH_CLIENT_SECRET

AUTH_SECRET_FILE=""
SHOW_ERR=""
cleanup() {
  if [ -n "${AUTH_SECRET_FILE:-}" ]; then
    rm -f "$AUTH_SECRET_FILE"
  fi
  if [ -n "${SHOW_ERR:-}" ]; then
    rm -f "$SHOW_ERR"
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

# Azure CLI exits 3 for ResourceNotFound. Any other failure is printed and stops
# the script, so a transient error is not treated as "missing, create it".
show_or_missing() {
  local rc=0
  SHOW_ERR=$(mktemp)
  "$@" >"$SHOW_ERR" 2>&1 || rc=$?
  if [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ]; then
    rm -f "$SHOW_ERR"
    SHOW_ERR=""
    return "$rc"
  fi
  cat "$SHOW_ERR" >&2
  rm -f "$SHOW_ERR"
  SHOW_ERR=""
  exit 1
}

# runningState, not provisioningState. Provisioned only means the revision object
# was accepted. Failed, Degraded, and ActivationFailed stop the deploy.
wait_for_running_revision() {
  local rev="$1"
  local state="" try=0
  rev="${rev//[[:space:]]/}"
  if [ -z "$rev" ]; then
    echo "latest revision name is empty; not treating the deploy as healthy" >&2
    exit 1
  fi
  # 36 * 5s is about three minutes. Activating is not a failure yet.
  while [ "$try" -lt 36 ]; do
    try=$((try + 1))
    if ! state="$(az containerapp revision show -n "$APP" -g "$RG" --revision "$rev" \
        --query properties.runningState -o tsv)"; then
      echo "could not read runningState for revision $rev" >&2
      exit 1
    fi
    state="${state//[[:space:]]/}"
    case "$state" in
      Running)
        return 0
        ;;
      Failed|Degraded|ActivationFailed)
        echo "revision $rev is $state" >&2
        exit 1
        ;;
    esac
    sleep 5
  done
  echo "revision $rev did not reach Running (last: ${state:-empty})" >&2
  exit 1
}

# The first create uses the registry admin user so that pull does not wait on
# AcrPull to propagate. Once this revision is Running on the system identity,
# turn admin off and drop the password create stored on the app.
# az names that secret <server>-<username> with the dots removed.
finish_registry_access() {
  local pw_secret names
  az acr update -n "$ACR" --admin-enabled false -o none
  pw_secret="$(printf '%s' "${ACR}.azurecr.io-${ACR}" | tr -d '.' | tr '[:upper:]' '[:lower:]')"
  names="$(az containerapp secret list -n "$APP" -g "$RG" --query '[].name' -o tsv)"
  if printf '%s\n' "$names" | grep -Fxq "$pw_secret"; then
    az containerapp secret remove -n "$APP" -g "$RG" --secret-names "$pw_secret" -o none
  fi
}

# A brand-new Key Vault Secrets User grant is often not visible yet. Retry only
# on the RBAC path. An access-policy vault fails on the first error.
set_auth_secret_ref() {
  local try=0 err
  while [ "$try" -lt 5 ]; do
    try=$((try + 1))
    err=$(mktemp)
    if az containerapp secret set -n "$APP" -g "$RG" \
        --secrets "auth-client-secret=keyvaultref:${KV_URL%/}/secrets/${AUTH_KV_SECRET},identityref:system" \
        -o none >"$err" 2>&1; then
      rm -f "$err"
      return 0
    fi
    cat "$err" >&2
    rm -f "$err"
    if [ "$KV_RBAC" -ne 1 ] || [ "$try" -eq 5 ]; then
      if [ "$KV_RBAC" -eq 1 ]; then
        echo "containerapp secret set failed after retries. A new Key Vault Secrets User grant can take a few minutes to apply. Re-run once it is visible." >&2
      else
        echo "containerapp secret set failed" >&2
      fi
      exit 1
    fi
    sleep "$try"
  done
}

# A new tag every run, including sub-second digits so two deploys in the same
# second still differ. Container Apps does not start a revision when the image
# string is unchanged, so deploying :latest again can leave the old digest running.
# :latest is still published. The app is updated to this unique tag.
TAG="$(date -u +%Y%m%d%H%M%S%N)"
IMAGE="$ACR.azurecr.io/$APP:$TAG"

az account set --subscription "$SUBSCRIPTION"
az group create -n "$RG" -l "$LOCATION" -o none
acr_rc=0
show_or_missing az acr show -n "$ACR" -g "$RG" -o none || acr_rc=$?
if [ "$acr_rc" -eq 3 ]; then
  # Admin stays on for this first create. finish_registry_access turns it off
  # after the system-identity revision is Running.
  az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true -o none
elif [ "$acr_rc" -ne 0 ]; then
  echo "az acr show failed (exit $acr_rc)" >&2
  exit 1
fi
az acr build -r "$ACR" -t "$APP:$TAG" -t "$APP:latest" .

az containerapp env create -n "$ENVN" -g "$RG" -l "$LOCATION" -o none 2>/dev/null || true

# Create only when show says the app is missing (exit 3). Any other show error
# already stopped the script. Do not infer existence from create's error text.
app_rc=0
show_or_missing az containerapp show -n "$APP" -g "$RG" -o none || app_rc=$?
if [ "$app_rc" -eq 0 ]; then
  echo "app exists; updating below"
elif [ "$app_rc" -eq 3 ]; then
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
    -o none
else
  echo "az containerapp show failed (exit $app_rc)" >&2
  exit 1
fi

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
RBAC=$(az keyvault show -n "$KV_NAME" --subscription "$KV_SUBSCRIPTION" --query properties.enableRbacAuthorization -o tsv)
RBAC="${RBAC//[[:space:]]/}"
KV_RBAC=0
case "$RBAC" in
  true|True|TRUE) KV_RBAC=1 ;;
esac
if [ "$KV_RBAC" -eq 1 ]; then
  VAULT_ID=$(az keyvault show -n "$KV_NAME" --subscription "$KV_SUBSCRIPTION" --query id -o tsv)
  VAULT_ID="${VAULT_ID//[[:space:]]/}"
  if [ -z "$VAULT_ID" ]; then
    echo "key vault id is empty; cannot assign Key Vault Secrets User" >&2
    exit 1
  fi
  grant_role "$PID" "Key Vault Secrets User" "${VAULT_ID}/secrets/${KV_SECRET}"
else
  az keyvault set-policy --name "$KV_NAME" --subscription "$KV_SUBSCRIPTION" --object-id "$PID" --secret-permissions get -o none
fi

# The client secret goes to Key Vault before any image change. It is not an az argument.
if [ -n "$AUTH_CLIENT_ID" ]; then
  AUTH_SECRET_FILE=$(mktemp)
  chmod 600 "$AUTH_SECRET_FILE"
  printf '%s' "$AUTH_CLIENT_SECRET" > "$AUTH_SECRET_FILE"
  unset AUTH_CLIENT_SECRET
  az keyvault secret set --vault-name "$KV_NAME" --subscription "$KV_SUBSCRIPTION" --name "$AUTH_KV_SECRET" --file "$AUTH_SECRET_FILE" -o none
  rm -f "$AUTH_SECRET_FILE"
  AUTH_SECRET_FILE=""
  if [ "$KV_RBAC" -eq 1 ]; then
    grant_role "$PID" "Key Vault Secrets User" "${VAULT_ID}/secrets/${AUTH_KV_SECRET}"
  fi
  set_auth_secret_ref
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
REV=""
if [ -n "$AUTH_CLIENT_ID" ]; then
  REV="$(az containerapp update -n "$APP" -g "$RG" \
    --image "$IMAGE" \
    --set-env-vars \
      JARVIS_TRADING_API=https://trading.landrycmd.com \
      KEY_VAULT_URL="$KV_URL" \
      JARVIS_TOKEN_SECRET_NAME="$KV_SECRET" \
      AUTH_CLIENT_ID="$AUTH_CLIENT_ID" \
      AUTH_TENANT_ID="$AUTH_TENANT_ID" \
      PUBLIC_BASE_URL="https://$FQDN" \
      AUTH_CLIENT_SECRET=secretref:auth-client-secret \
    --query properties.latestRevisionName -o tsv)"
else
  # A previous --replace-env-vars wipe drops these. Set them again and leave AUTH_* in place.
  REV="$(az containerapp update -n "$APP" -g "$RG" \
    --image "$IMAGE" \
    --set-env-vars \
      JARVIS_TRADING_API=https://trading.landrycmd.com \
      KEY_VAULT_URL="$KV_URL" \
      JARVIS_TOKEN_SECRET_NAME="$KV_SECRET" \
    --query properties.latestRevisionName -o tsv)"
fi
wait_for_running_revision "$REV"
finish_registry_access
if [ -n "$AUTH_CLIENT_ID" ]; then
  echo "auth enabled; connect from Claude at https://$FQDN/mcp"
else
  echo "NEXT: register the app in the landrycmd tenant with redirect https://$FQDN/auth/callback, then re-run with AUTH_* set."
fi
