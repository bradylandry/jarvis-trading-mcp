# Feature map

Maintained source for verifying jarvis-trading-mcp. Update this index and the matching file when a user-facing tool, the backend token path, or startup auth changes.

## Baseline preconditions

- Run from the repository root with SKILL.md's Launch up and Doctor passing.
- Source `vars.sh` first: `. .cursor/skills/verify-jarvis-trading-mcp/vars.sh`. It sets `EVIDENCE`, the ports, `SKILL_DIR`, the placeholder rotation tokens, and `set_token`.
- Drive serially. Tool features use the main server on `MCP_PORT`. Token reread uses the rotation server on `ROT_PORT`. Sign-in guard starts its own servers on `SIGNIN_PORT`.
- Never drive an instance this run did not start.

## Features

| Feature | Tools or surface | Server | File |
| --- | --- | --- | --- |
| Find candidates | `scan_universe` | main | [scan-universe.md](scan-universe.md) |
| Evaluate one contract | `get_thesis` | main | [contract-thesis.md](contract-thesis.md) |
| Directional fit | `get_fit_score` | main | [fit-score.md](fit-score.md) |
| Macro regime | `get_crash_risk`, `get_geopolitical` | main | [macro-regime.md](macro-regime.md) |
| Earnings and implied vol | `get_earnings_analysis`, `get_iv` | main | [earnings-and-iv.md](earnings-and-iv.md) |
| Backend token reread on a 401 | any tool; `get_crash_risk` and `get_iv` driven | rotation | [token-reread.md](token-reread.md) |
| Half-set sign-in refused | server startup env | own, per case | [signin-guard.md](signin-guard.md) |

## Proof and skip reporting

- Each drive writes `call-<tool>[-label].json` and `side-effects[-label].json`. The access-log rows in the side-effects file are the proof, not the tool result alone.
- Report a failed journey with its side-effects file. Do not reorder or loosen a journey to make it pass.
- An unreachable path is reported with the command tried and the missing precondition.
