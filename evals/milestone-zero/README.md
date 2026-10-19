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
| `task.py` | Inspect `Task` definition (+ `arin_milestone_mvq`) |
| `cases_mvq_synthetic.jsonl` | **Synthetic-only** MVQ cases (RED-681) |
| `run_mvq.py` | MVQ grader trial → `evidence/mvq-results.json` + scorecard |
| `grader/` | MVQ scorer, prompt, scorecard, QA agreement |
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

Live mode is **enabled** (`--mode hermes` defaults to **non–dry-run**).

Safety (fail closed):

1. **Interception probe** runs once before any live case (HTTP POST to local stub must return `blocked` / `eval_stub`).
2. **SMS hydrate bypass closed**: child env sets `SMS_RUNTIME_ENV_FILE` (stub `runtime.env` with stub `TELNYX_SMS_API_BASE`, empty `TELNYX_API_KEY`), `SMS_PROC_ENVIRON` (empty file), and blank `TELNYX_API_KEY` so `sms_send_confirmed.py` cannot refill real keys from `/proc/1/environ`.
3. **Throwaway `HERMES_HOME` copy** per trial (no real owner memory; stripped sessions/audit/learning-loop client dirs).
4. **Hermes 0.21.0 CLI**: `hermes chat -Q -q "<text>"` (or `--query-file` for long prompts).
5. **`mz-002` / `mz-007`** (`daily brief` prompts): `live_mode: fixture_only` until brief/outbound tools are stubbed.

```bash
cd /opt/data/skills/advisor-reach-hermes-skills   # your checkout on e23fjkv6
pip install -r evals/milestone-zero/requirements.txt
export ARIN_EVAL_BOX=e23fjkv6
export HERMES_HOME=/opt/data
hermes --version   # must contain 0.21.0

python3 evals/milestone-zero/run_trial.py --limit 20 --mode hermes --no-dry-run --skip-inspect
python3 evals/milestone-zero/run_repeat.py --repeats 5 --mode hermes --no-dry-run
```

Credential vars cleared in the child process include Composio, GHL, FUB, and Gmail-related keys (see `live_session.py`).

For harness CI without a binary: `ARIN_EVAL_STUB_HERMES=1` exercises live path + outbound stub using fixture text.

## MVQ grader (RED-681), v0.2.0

Two layers, scored **after selection** (case list hashed and frozen, behavior checks run, then every selected case is scored; behavior failures are recorded, not dropped):

1. **Deterministic (always):** `grader/routes/deterministic.py` regex rubric (R1-R5, fixed reason codes) + `grader/hard_fail.py` H1-H4. No model, nothing leaves the process.
2. **Judge (optional):** `ARIN_MVQ_GRADER_MODEL_ROUTE` (`fixture` in CI, `http`, or `grader/routes/<name>.py`). Unset / `deterministic` / `none` = deterministic only. A judge that errors or returns malformed output makes the case **unscored**, never a fail; `det_*` fields keep the deterministic result. Hard fails are OR'd; H1/H2 force R4 = 0.

Stub-only; **any delivered SMS in the outbound log fails the whole run** (exit 3).

Synthetic (CI):

```bash
ARIN_MVQ_GRADER_MODEL_ROUTE=fixture python3 evals/milestone-zero/run_mvq.py --evidence-dir /tmp/mvq-ev
python3 evals/milestone-zero/grader/qa_agreement.py \
  --human evals/milestone-zero/grader/fixtures/qa_human_sample.json --grader /tmp/mvq-ev/mvq-results.json
```

Real redacted cases (**ARIN TEST e23fjkv6 only**, run by Keel as `hermes`):

```bash
umask 077
D=/opt/data/eval-export/red667-20261017
python3 <checkout>/evals/milestone-zero/run_mvq.py --real --live --skip-behavior-checks \
  --cases $D/redacted/cases-export.jsonl --evidence-dir $D/mvq-v0.2.0 \
  --build-image arin-v1.5-5ce17af
```

- `--real` refuses: evidence or cases inside a git worktree; any judge route not named in `ARIN_MVQ_REAL_JUDGE_ALLOWED` (set only after Vault + David approve that route).
- Evidence dir 0700, `mvq-results.json` 0600, holding scores, reason codes and flags only: no case text, no reply text, no judge reasons. No scorecard is written in real mode. stdout is counts only.
- `--live` gets replies from the stub-only live Hermes session (exported cases carry no recorded reply). Without `--live`, cases with no reply are **unscored**.

Tuning: `ARIN_MVQ_GRADER_BAR` (default `8`), `ARIN_MVQ_GRADER_LINE_WEIGHTS`, `ARIN_MVQ_GRADER_ENABLED_HARD_FAILS`, optional `ARIN_MVQ_GRADER_CONFIG`. HTTP judge needs `ARIN_MVQ_GRADER_HTTP_URL` (no API keys in repo).

Grader prompt version: `grader/prompts/mvq-grader-v0.2.0.md` (`GRADER_VERSION` in `grader/version.py`).

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
