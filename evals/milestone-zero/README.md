# RED-667 milestone-zero eval harness

Inspect-based regression checker for ARIN text sessions on **ARIN TEST only** (`e23fjkv6`). Customer session text stays on the box; this repo ships **synthetic** cases and tooling only.

## Layout

| Path | Role |
|------|------|
| `cases.jsonl` | 20 cases with `suite`: `regression` \| `capability` |
| `redact.py` | Box-local redaction (`--fail-closed`) |
| `export_session_to_case.py` | Box-local session → redacted JSONL case |
| `BOX-EXPORT.md` | Operator procedure for TEST exports |
| `outbound_stub.py` | Stub Telnyx base URL; outbound JSONL log |
| `hermes_bridge.py` | Hermes **0.21.0** live invoke + fixture replay |
| `checks.py` | Pass/fail (SEND gate uses **outbound log**, not the word SEND) |
| `run_trial.py` | Single-pass trial → `evidence/trial-results.json` |
| `run_repeat.py` | **≥5 repeats** per case; all must pass |
| `task.py` | Inspect `Task` definition |
| `requirements.txt` | `inspect_ai` pin |

## Suite tags

| Tag | Cases | Use |
|-----|------:|-----|
| `regression` | 14 | no_answer + send_draft — must not break |
| `capability` | 6 | memory_save — behavior we are proving |

Filter: `run_repeat.py --suite regression`.

## Quick start (CI / hermetic)

```bash
pip install -r evals/milestone-zero/requirements.txt
python3 evals/milestone-zero/run_trial.py --limit 20 --mode fixture --skip-inspect
python3 evals/milestone-zero/run_repeat.py --repeats 5 --mode fixture
node --test tests/arin-milestone-zero.test.mjs
```

## Live Hermes on ARIN TEST (`e23fjkv6`)

Live mode is **enabled** (`--mode hermes` defaults to **non–dry-run**). Outbound SMS is **stubbed**: `TELNYX_SMS_API_BASE` points at a local HTTP stub that returns success but **never** delivers; trials **fail** if the outbound log records `delivered`.

```bash
export ARIN_EVAL_BOX=e23fjkv6
export HERMES_HOME=/opt/data
export HERMES_VERSION=0.21.0   # until `hermes --version` works
python3 evals/milestone-zero/run_trial.py --limit 20 --mode hermes --no-dry-run
python3 evals/milestone-zero/run_repeat.py --repeats 5 --mode hermes --no-dry-run
```

Optional override: `ARIN_EVAL_HERMES_CMD='hermes chat -q --message'` (message appended).

For harness CI without a binary: `ARIN_EVAL_STUB_HERMES=1` exercises live path + outbound stub using fixture text.

## Model grader policy

- **Allowed only** on **redacted or synthetic** cases (`cases.jsonl`, `cases-export.local.jsonl` after `export_session_to_case.py`).
- Use a **zero-retention** API route or a **self-hosted** grader on the box/VPC. Do not send raw session logs to vendor graders.
- If `redact.py --fail-closed` or `export_session_to_case.py` reports residue, **stop** — no grader call, no export off-box.
- Deterministic checks in `checks.py` remain the gate for milestone-zero; model graders are optional supplements, not replacements.

## Box export (nothing leaves until redacted)

See **`BOX-EXPORT.md`**. Summary:

1. Export session JSON on-box only.  
2. `export_session_to_case.py` → `cases-export.local.jsonl` (fail closed).  
3. Review on-box; merge into `cases.jsonl` after replay passes.  
4. Copy **only** the redacted JSONL line off-box if needed.

## Evidence paths

| Run | File |
|-----|------|
| Trial | `evals/milestone-zero/evidence/trial-results.json` |
| Repeat | `evals/milestone-zero/evidence/repeat-results.json` |
| Inspect | `evals/milestone-zero/evidence/*.eval` (gitignored) |

## Hermes 0.21.0

`HERMES_PIN = "0.21.0"`. `prove_wrap()` must pass on TEST before you treat live Hermes results as valid.
