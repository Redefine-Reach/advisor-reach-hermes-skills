# RED-667 milestone-zero eval harness

Inspect-based regression checker for ARIN text sessions on **ARIN TEST only** (`e23fjkv6`). Customer session text stays on the box; this repo ships **synthetic** cases and tooling only.

## Layout

| Path | Role |
|------|------|
| `cases.jsonl` | First 20 milestone-zero cases (no-answer, SEND draft, learning-loop save) |
| `redact.py` | Box-local redaction before a log line becomes a case |
| `hermes_bridge.py` | Hermes **0.21.0** pin + invoke / fixture replay |
| `checks.py` | Pass/fail rules per case |
| `task.py` | Inspect `Task` definition |
| `run_trial.py` | Trial runner → `evidence/trial-results.json` |
| `requirements.txt` | `inspect_ai` pin for CI and box venv |

## Quick start (hermetic, no live SMS)

```bash
python3 -m venv .venv-eval
. .venv-eval/bin/activate
pip install -r evals/milestone-zero/requirements.txt
python3 evals/milestone-zero/run_trial.py --limit 20 --mode fixture
node --test tests/arin-milestone-zero.test.mjs
```

## ARIN TEST box (`e23fjkv6`)

1. Lay this directory on the box under the skills repo checkout.
2. Redact a real log excerpt **on the box** before exporting:  
   `python3 evals/milestone-zero/redact.py --in session.txt --out session.redacted.txt`
3. Live Hermes trial (no real texts to customers):  
   `ARIN_EVAL_BOX=e23fjkv6 HERMES_HOME=/opt/data python3 evals/milestone-zero/run_trial.py --limit 20 --mode hermes --dry-run`
4. Inspect log: `evidence/trial-results.json` (and optional `.eval` under `evidence/` when Inspect writes one).

Do not run against fleet or customer boxes. Do not send real third-party SMS during evals (`--dry-run` stubs `sms-send-confirmed`).

## Blockers (Oct 16 trial)

| Blocker | Where it clears |
|---------|------------------|
| `hermes` binary / `HERMES_VERSION` not on CI VM | Run `--prove-wrap` on `e23fjkv6` after lay-down |
| Live `hermes` invoke disabled in repo | Box trial with `--mode hermes` once David approves non-fixture run |
| Cases are **synthetic** until redacted logs are exported from TEST | Replace rows in `cases.jsonl` after on-box redaction |

## Hermes 0.21.0

`hermes_bridge.py` records `HERMES_PIN = "0.21.0"`. `--prove-wrap` checks `hermes --version` (or `HERMES_VERSION`) and fails the trial metadata block when the pin mismatches.
