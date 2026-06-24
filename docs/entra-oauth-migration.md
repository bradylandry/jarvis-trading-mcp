# Entra OAuth Migration — landrycmd.com tenant

Goal: replace the static `X-API-Token` model with Microsoft Entra ID OAuth,
hosted in a **free Entra tenant on landrycmd.com** (separate from the firm's
acadianatek.com tenant). Personal R&D sandbox; experience transfers to ACADIANA TEK.

Decision: **free Entra tenant, no O365 license** — app registration + OAuth +
B2B guest (50k free MAU) cover everything here. Only buy O365 later if you want
mailboxes/Office on landrycmd.com.

---

## Phase 0 — Prereqs (do once)

- [ ] Confirm Cloudflare is the DNS host for landrycmd.com (it is — Registrar).
- [ ] Have a Microsoft identity to bootstrap tenant creation. You don't need a
      pre-existing one or an @outlook.com mailbox — sign up free at
      entra.microsoft.com using your existing Gmail (bjlandry@gmail.com) and
      Microsoft provisions a free Microsoft account during the flow. Not a paid
      seat. Note: this Gmail-backed account only *births* the tenant; the real
      admin is the `<you>@<tenant>.onmicrosoft.com` Global Admin account created
      with the tenant — use that to run it going forward.

## Phase 1 — Create the Entra tenant (~15 min, $0)

- [ ] Go to entra.microsoft.com → Manage tenants → Create → **Microsoft Entra ID**
      (workforce). Name it e.g. "landrycmd". This is a NEW tenant, separate from
      acadianatek.com.
- [ ] In the new tenant: Settings → Custom domain names → Add `landrycmd.com`.
- [ ] Add the TXT verification record at Cloudflare (paste the value Entra gives
      you). Verify. (Reversible — it's just a TXT record.)
- [ ] Note the **Tenant ID** (GUID) — you'll need it for token validation.

## Phase 2 — Register the trading API as an app (~20 min)

- [ ] Entra → App registrations → New registration. Name: "jarvis-trading-api".
      Supported account types: start with **single tenant** (lock down later if
      you want guests).
- [ ] Under **Expose an API**: set Application ID URI (e.g.
      `api://<app-id>`), add a scope like `trading.read` (admin + user consent,
      "Read trading research"). This scope is what the MCP will request.
- [ ] Record: **Application (client) ID**, **Tenant ID**, **Application ID URI**.
- [ ] (No client secret needed for the MCP if using device-code/public-client
      flow — see Phase 3.)

## Phase 3 — Register the MCP as a public client (~15 min)

- [ ] Either reuse the same app registration or create "jarvis-trading-mcp".
- [ ] Authentication → Add platform → **Mobile and desktop applications** →
      enable **"Allow public client flows"** (required for device-code flow).
- [ ] Add API permission → My APIs → jarvis-trading-api → delegated `trading.read`.
      Grant admin consent.

## Phase 4 — Wire device-code OAuth into the MCP (friend_mcp/server.py)

Replace the static-token path with MSAL device-code flow.

- [ ] `pip` add `msal` to pyproject dependencies.
- [ ] On first tool call with no cached token: run MSAL
      `PublicClientApplication.acquire_token_by_device_flow()`. Print the
      "go to microsoft.com/devicelogin, enter CODE XXXX" message via stderr/MCP.
- [ ] Cache the token (MSAL token cache) in the **OS keychain** (`keyring`), not
      plaintext config. Reuse silently; refresh when expired.
- [ ] Send `Authorization: Bearer <access_token>` to the API instead of
      `X-API-Token`. Keep `X-API-Token` as a fallback during transition.
- [ ] Update env: drop `JARVIS_TRADING_TOKEN`; add `JARVIS_TRADING_TENANT_ID`,
      `JARVIS_TRADING_CLIENT_ID`, `JARVIS_TRADING_SCOPE`.

## Phase 5 — Validate JWTs on the API side (GCP VM)

- [ ] API fetches Entra's public keys from the tenant JWKS endpoint
      (`https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys`).
- [ ] On each request: validate the Bearer JWT — signature, `iss`
      (`https://login.microsoftonline.com/<tenant-id>/v2.0`), `aud`
      (your Application ID URI / client ID), `exp`, and the `scp` claim contains
      `trading.read`.
- [ ] Map the `oid`/`sub` claim to a per-user identity → **per-user audit log**
      and **server-side rate limiting** (move enforcement off the client).
- [ ] Keep accepting `X-API-Token` temporarily; log which path each call uses so
      you can see when all users have migrated, then remove it.

## Phase 6 — Onboarding & cleanup

- [ ] (If opening to friends) switch app to allow guests, invite them as B2B
      guests — they sign in with their own identity, no license, free under 50k MAU.
- [ ] Update README: replace "get a token from Brady" with "sign in with your
      Microsoft account."
- [ ] Revoke old static tokens once everyone's on OAuth.
- [ ] Optional later: buy O365 on landrycmd.com only if you want email/Office.
- [ ] Optional later: Entra ID P1 (~$6/user/mo) only if you want Conditional
      Access (geo/MFA/device policies). Not needed for basic OAuth.

---

## Effort / value notes

- Phases 1-3 are clicks, ~1 hr total, $0.
- Phase 4-5 are the real engineering (MSAL flow + JWT validation). Half a day each
  if it's your first time with MSAL.
- Lightweight alternative if this proves over-built for a few users: keep tokens
  but add **expiry + rotation** and move them to keychain (Phase 4's keyring part
  without the OAuth). ~80% of the security win for ~20% of the effort.
