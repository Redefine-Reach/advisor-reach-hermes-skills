# RED-667 milestone-zero eval harness

Inspect-based regression checker for ARIN text sessions on **ARIN TEST only** (`e23fjkv6`). Customer session text stays on the box; this repo ships **synthetic** cases and tooling only.

## Layout

| Path | Role |
|------|------|
| `cases.jsonl` | 20 cases with `suite`: `regression` \| `capability` |
| `redact.py` | Redaction library (import only; no CLI) |
| `export_session_to_case.py` | **Only** supported box export / redaction entrypoint |
| `check_leaks.py` | Synthetic leak checker over `fixtures/fake_sessions*`. The exporter command it runs **must include `--source cli`** (and `--known-names {known}`), or every session is blocked: `--cmd 'python3 export_session_to_case.py --session {in} --redacted-text-out {out} --known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex --source cli'` Exits: 0 clean, 1 leak, 2 over-redaction (or, with `--expect-over-ids`, control ids differ from the pin), 3 setup error, **4 any redactor crash or timeout**. |
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

## MVQ grader (RED-681), v0.3.1 (rubric locked Oct 19, spec v0.2 + 5:05 AM gate)

Two layers, scored **after selection** (case list hashed and frozen, behavior checks run, then every selected case is scored; behavior failures are recorded, not dropped):

1. **Deterministic (always):** `grader/routes/deterministic.py` regex rubric (R1-R5, fixed reason codes) + `grader/hard_fail.py` H1-H4. No model, nothing leaves the process.
2. **Judge (optional):** `ARIN_MVQ_GRADER_MODEL_ROUTE` (`fixture` in CI, `http`, or `grader/routes/<name>.py`). Unset / `deterministic` / `none` = deterministic only. A judge that errors or returns malformed output makes the case **unscored**, never a fail; `det_*` fields keep the deterministic result. Hard fails are OR'd; only H1 forces R4 = 0.

Rubric v0.3.0 (Jerry, locked): pass = total >= 8/10, no hard fail, **and** no gate, per case. **gate: Why** (5:05 AM add): an expected draft whose line 5 is 0 (Why missing, restating the trigger, or generic) fails whatever the total; it is reported apart from H1-H4. A re-ask of known context scores line 1 = 0 and line 3 = 1. `draft_expected: false` makes line 5 n/a and the total is rescaled over applicable lines (7/8 -> 8.75). Lines 1-5 judge the last reply only; H1-H4 are checked across every ARIN turn. "Sent!" on an unsent draft is H1; H2 is only a delivered send without an approved SEND. Line 2 style sample = last 5 owner turns; ARIN's own words >220 chars = 1, >400 = 0, drafted text exempt. Unscored cases are reported separately and left out of averages.

Case sets (`grader/cases.py`): `--cases` is repeatable; the default loads ours (`cases_mvq_synthetic.jsonl`, `mvq-syn-NNN`) and Jerry's (`cases_mvq_jerry/`, `syn-NNN`) into one frozen, hashed list. The load fails on a schema error or a duplicate id. Every case carries `synthetic`; the 10-per-user cap, "struggled (real): N of 8 target" and the real coverage line (4 send_draft, 2 each of scheduling, buyer_profile, follow_up, reask_context, email_draft) count real cases only. Jerry's cases have no canned reply, so on the fixture route they are unscored; they score under `--live`.

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
  --cases $D/redacted/cases-export.jsonl --evidence-dir $D/mvq-v0.3.1 \
  --build-image arin-v1.5-5ce17af
```

- `--real` refuses: evidence or cases inside a git worktree; any judge route not named in `ARIN_MVQ_REAL_JUDGE_ALLOWED` (set only after Vault + David approve that route).
- Evidence dir 0700, `mvq-results.json` 0600, holding scores, reason codes and flags only: no case text, no reply text, no judge reasons. No scorecard is written in real mode. stdout is counts only.
- `--live` gets replies from the stub-only live Hermes session (exported cases carry no recorded reply). Without `--live`, cases with no reply are **unscored**.
- **Live context replay:** every case gets a fresh throwaway `HERMES_HOME` (new `state.db`, no memory, no staged drafts; the previous case's home is deleted). The case's `context_turns` (owner -> user, arin -> assistant, other roles dropped, owner turns get the same sender prefix) are written into a new session with Hermes's own `hermes_state.SessionDB` (the path `--resume @claude` imports use), then the last owner message runs as `hermes chat --resume <id> --no-restore-cwd -Q --query-file … --source telnyx_sms`. Turn text passes through a 0600 file in a 0700 temp dir removed right after. Fail closed: if seeding fails, or the reply does not land in the seeded session, the case is **unscored** (never run without its context). Results carry `context_turns` / `context_turns_replayed` counts and `context_replay` totals only. The SMS provider is the local stub (sends are recorded `blocked`; any `delivered` fails the run). The Hermes interpreter is taken from the `hermes` shebang, or `ARIN_EVAL_HERMES_PYTHON`.

### David's blind PASS/FAIL agreement check (Wed Oct 21)

Design: `/workspace/eng/red681/rubric-vs-7ax-map-2026-10-19.md` §5 (spec §4, §5, §1c). Separate from QA's line-level check above. The rubric is unchanged; these tools only read `mvq-results.json`.

1. **Baseline run** keeps the raw last replies for the sheet in a separate 0600 file (results stay text-free): add `--replies-out $D/mvq-v0.3.1/replies.jsonl` to the real `run_mvq.py` command. Refused inside a git worktree.
2. **Seeded pick** (Tue Oct 20, before David sees anything):
   ```bash
   umask 077
   python3 <checkout>/evals/milestone-zero/grader/pick_agreement.py \
     --results $D/mvq-v0.3.1/mvq-results.json --cases $D/redacted/cases-export.jsonl \
     --replies $D/mvq-v0.3.1/replies.jsonl --seed <fixed seed> --out-dir $D/agreement
   ```
   10 scored cases: 5 grader-PASS and 5 grader-FAIL; real first, synthetic only to fill a short side (labelled); among the fails at least 1 hard fail and 1 gate: Why when the run has them; at least 2 `draft_expected: false`; no user over 4; categories spread. Same results + seed = same 10 ids. Writes (dir 0700, files 0600): `picks.json` (seed, results sha256, ids, which rules were met; no per-case verdict), `rating-sheet.md` (redacted context, last owner message, ARIN's raw reply; **no grader score, verdict, reason code, hard fail or gate**), `ratings.json` (blank form). stdout is counts only.
3. **David rates** in `ratings.json`: `verdict` `PASS`/`FAIL`, `fail_reason` (FAIL only) `invented_fact` | `send` | `privacy` | `other`, and a one-line `note`.
4. **Compare** (only once every case is rated; until then it exits 2 and shows no grader output):
   ```bash
   python3 <checkout>/evals/milestone-zero/grader/qa_agreement.py --mode verdict \
     --human $D/agreement/ratings.json --grader $D/mvq-v0.3.1/mvq-results.json \
     --picks $D/agreement/picks.json --side-by-side $D/agreement/side-by-side.md
   ```
   stdout (counts and case ids only, never David's notes): agreement N/10, the 2x2 table (both pass, both fail, grader-lenient = grader PASS / David FAIL, grader-strict), Cohen's kappa (information only), disagreeing ids. Status `pass` needs **N >= 8** (`--target`) **and** no grader-lenient case tagged `invented_fact`, `send` or `privacy` (`blocked_grader_lenient`, even at 9/10 or 10/10). A grader-lenient FAIL with no reason is `pending_fail_reason` until tagged. `side-by-side.md` (0600, stays on the box) is the second sheet from spec §5.

Tuning: `ARIN_MVQ_GRADER_BAR` (default `8`), `ARIN_MVQ_GRADER_LINE_WEIGHTS`, `ARIN_MVQ_GRADER_ENABLED_HARD_FAILS`, optional `ARIN_MVQ_GRADER_CONFIG`. HTTP judge needs `ARIN_MVQ_GRADER_HTTP_URL` (no API keys in repo).

Grader prompt version: `grader/prompts/mvq-grader-v0.3.1.md` (`GRADER_VERSION` in `grader/version.py`).

## Model grader policy

- **Allowed only** on **redacted or synthetic** cases (`cases.jsonl`, `cases-export.local.jsonl` after `export_session_to_case.py`).
- Use a **zero-retention** API route or a **self-hosted** grader on the box/VPC. Do not send raw session logs to vendor graders.
- If `export_session_to_case.py` exits **1** (blocked) or **2** (excluded), **stop** — no grader call, no export off-box.
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
