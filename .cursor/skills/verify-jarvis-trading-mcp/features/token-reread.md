# Backend token reread on a 401

When the research API rejects the cached `X-API-Token` with a 401, the server drops it, rereads the token source once, and retries the request once if the reread gave a different token. A rotation in Key Vault clears up without a restart. If the reread gives the same token, or the retry also gets a 401, the user sees one clean error and nothing loops. Token values never reach logs or tool output.

## Sub-features

- `reread-warm`: the first call reads the vault once and caches the token.
- `reread-rotated`: after a rotation, one call sends the old token (401), reads the vault once, retries with the new token (200), and returns data.
- `reread-cached`: the next call, on any tool, sends the new token straight away with no vault read.
- `reread-stale-vault`: the vault still holds the rejected token. One 401, one vault read, no retry, clean error.
- `reread-bad-rotation`: the vault holds a different token that is also rejected. Exactly two 401s (old, then new), one vault read, clean error.
- `reread-recover`: once the vault holds the accepted token, the next call recovers with one 401 and one 200.
- `reread-no-leak`: no full token value in any evidence file, including server logs and tool errors. The access log and vault log carry the last 4 characters only.

## How to get to it (user POV)

- A friend asks Claude "what's the current crash risk score?" right after Brady rotates the backend token in Key Vault. The answer still arrives. Before PR #6 it failed until a restart.
- If the token was revoked and the vault was not updated, the friend sees `trading API rejected the token (401). Confirm the token is still active.` (README troubleshooting: "If the error sticks, that's on Brady's side").
- Only the Key Vault source can rotate under a running server. With `JARVIS_TRADING_TOKEN` set (local dev), the reread returns the same value, so a 401 always ends in the clean error with no retry.

## Driving it with mcp_client.py

Preconditions:

- Launch and Doctor passed, so the rotation server on `ROT_PORT` is up with the fake vault, and `$SCRATCH/paper-token` and `$SCRATCH/kv-secret` both hold `OLD1`.
- Run this block once, top to bottom, right after Launch. The steps depend on each other: each one starts from the token the previous one cached. To rerun it, run Cleanup and Launch again.

```bash
set -euo pipefail
. .cursor/skills/verify-jarvis-trading-mcp/vars.sh
rot() {
  .venv/bin/python "$SKILL_DIR/mcp_client.py" drive \
    --url "http://127.0.0.1:${ROT_PORT}/mcp" --evidence "$EVIDENCE" \
    --kv-log "$EVIDENCE/fake-kv-reads.jsonl" "$@"
}
ERR='trading API rejected the token (401). Confirm the token is still active.'

# reread-warm
rot --label rot-1-warm --tool get_crash_risk \
  --expect-rows '[{"status":200,"token_last4":"OLD1"}]' --expect-kv-reads 1

# reread-rotated: rotate the vault and the API together
set_token "$SCRATCH/paper-token" "$ROT_NEW"
set_token "$SCRATCH/kv-secret" "$ROT_NEW"
rot --label rot-2-rotated --tool get_crash_risk \
  --expect-rows '[{"status":401,"token_last4":"OLD1"},{"status":200,"token_last4":"NEW2"}]' \
  --expect-kv-reads 1

# reread-cached, on a different tool
rot --label rot-3-cached --tool get_iv --args '{"ticker":"avgo"}' \
  --expect-rows '[{"status":200,"token_last4":"NEW2"}]' --expect-kv-reads 0

# reread-stale-vault: the API moves on, the vault does not
set_token "$SCRATCH/paper-token" "$ROT_NEXT"
rot --label rot-4-stale-vault --tool get_crash_risk \
  --expect-rows '[{"status":401,"token_last4":"NEW2"}]' --expect-kv-reads 1 --expect-error "$ERR"

# reread-bad-rotation: the vault changes, but to a token the API also rejects
set_token "$SCRATCH/kv-secret" "$ROT_BAD"
rot --label rot-5-bad-rotation --tool get_crash_risk \
  --expect-rows '[{"status":401,"token_last4":"NEW2"},{"status":401,"token_last4":"BAD4"}]' \
  --expect-kv-reads 1 --expect-error "$ERR"

# reread-recover
set_token "$SCRATCH/kv-secret" "$ROT_NEXT"
rot --label rot-6-recover --tool get_crash_risk \
  --expect-rows '[{"status":401,"token_last4":"BAD4"},{"status":200,"token_last4":"NEW3"}]' \
  --expect-kv-reads 1

# reread-no-leak
.venv/bin/python "$SKILL_DIR/mcp_client.py" leakcheck --evidence "$EVIDENCE" \
  --token "$ROT_OLD" --token "$ROT_NEW" --token "$ROT_NEXT" --token "$ROT_BAD"
```

Pass: every `rot` call prints `"ok": true` with `"rows_matched": true` and `"outcome_matched": true`. `side-effects-rot-2-rotated.json` shows the 401 row with `OLD1` followed by the 200 row with `NEW2`, and one `fake-kv-reads.jsonl` row with `value_last4` `NEW2`. `call-get_crash_risk-rot-4-stale-vault.json` and `-rot-5-bad-rotation.json` have `is_error: true` and the exact error text. `leakcheck` prints `"ok": true` with `"hits": []`.

## Gotchas

- `--expect-rows` is an exact match. One extra 401 row is the "retried forever" failure this journey exists to catch, so never loosen it to a prefix or a count.
- The vault read count includes the first read of a fresh process. A rotation server that has already served a call starts `reread-warm` with a cached token and fails it; relaunch instead of reordering.
- A reread that returns the same token does not retry, so `reread-stale-vault` logs one row, not two.
- Each retry takes its own rate-limit slot. This block uses 9 of the default 30 per minute.
- Run `leakcheck` with the four rotation tokens only. The main server's token `paper` is also a key in every fixture body.
- If Launch's shadowing check fails, the real Azure SDK would load and try Managed Identity. Do not start the rotation server; fix `PYTHONPATH` first.
- Concurrent 401s sharing one reread is covered by `tests/test_token_refresh.py` only. Driving it live needs overlapping calls with precise timing, which this harness does not attempt.
