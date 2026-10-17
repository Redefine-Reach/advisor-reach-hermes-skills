# Box-local session export (ARIN TEST `e23fjkv6` only)

Run **on the test box**. Do not SCP raw session JSON off the box. Copy only redacted JSONL lines after this procedure passes.

**Policy:** Nothing leaves a box unredacted. Redaction is **necessary but not sufficient**: a human must read the **first redacted output** from David's sessions on ARIN TEST on the box before anything is copied off-box, and Vault still reviews batches before grader use. **No model-based health/legal classifier** is permitted until an approved on-box route exists (lexicon drop only today).

## Exit codes (`export_session_to_case.py`)

| Code | Meaning |
|------|---------|
| **0** | Redacted output written (`exported:` on stderr). |
| **1** | **Blocked** — residue, decode/JSON error, unsupported field type, or detector failure. No output file. |
| **2** | **Excluded** — whole session dropped (health, legal, do-not-keep, forgotten, forget/`/new`, opt-out, minor). Count only on stderr; **no output file** (not a successful export). |

Use **only** `export_session_to_case.py` for redaction. There is no supported `redact.py` CLI.

## Retention (30 days)

Redacted cases, manifests, and temp working files on the box: **delete within 30 days** of the run date (`deletion_date` in the manifest). Raw session copies: delete at end of the export run. Log deletion with **date and count only**.

## 1. Export session from Hermes logs (on box)

Identify the session file under `$HERMES_HOME`. Copy to a working file (e.g. `/tmp/session-raw.json`). Optional sidecars (mode **0600**, never commit):

- `--known-names` — **required** for real JSONL export (`--out` / default append path). Per-box contact list (mode **0600**, never commit). Case-insensitive whole-word redaction for lowercase texting-style names; export **blocks (exit 1)** if omitted. Leak-check via `--redacted-text-out` still passes `{known}` from the fixture dir in CI.  
- `--rules` — `donotkeep_rules.json` with `do_not_keep` phrases (token-normalized, ≥75% overlap)  
- `--forgotten` — forgotten phrases (same matching)

## 2. Redact and build case (fail closed)

```bash
cd /opt/data/skills/advisor-reach-hermes-skills
python3 evals/milestone-zero/export_session_to_case.py \
  --session /tmp/session-raw.json \
  --id mz-021 \
  --suite regression \
  --category send_draft \
  --owner-name Alex \
  --known-names /tmp/box-known-names.txt \
  --rules /tmp/donotkeep-rules.json \
  --forgotten /tmp/forgotten-phrases.txt \
  --session-index opaque-7f3a \
  --out evals/milestone-zero/cases-export.local.jsonl \
  --manifest evals/milestone-zero/cases-export.local.manifest.json
```

- **Health or legal topic** (including common rewordings): entire session **excluded** (exit **2**), not redacted in place. A **second, independent** conservative pass (`conservative_guard.py`) re-scans redacted text; any residual health/legal/family/financial/credential-ish signal also forces exit **2** (default-deny).  
- **Phones** (10-digit, +1, 7-digit local): masked as `[PHONE ***1234]` (last four only).  
- Stdout stays empty; stderr logs **counts per class only** and `session_index=…` (no source path, no case body).

Leak-check helper (synthetic fixtures in CI):

```bash
python3 evals/milestone-zero/check_leaks.py \
  --cwd evals/milestone-zero \
  --cmd 'python3 export_session_to_case.py --session {in} --redacted-text-out {out} --known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex' \
  --strict-drop --fail-on-overredaction
python3 evals/milestone-zero/check_leaks.py \
  --cwd evals/milestone-zero --sessions fixtures/fake_sessions_heldout2 \
  --label heldout2 --strict-drop --fail-on-overredaction \
  --cmd 'python3 export_session_to_case.py --session {in} --redacted-text-out {out} --known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex'
# Private unseen set (not committed): run locally or in CI with a secret path
export MZ_PRIVATE_LEAK_SESSIONS=/secure/path/to/private_sessions
python3 evals/milestone-zero/check_leaks.py --label private --cwd evals/milestone-zero \
  --cmd '...same --cmd...' --strict-drop --fail-on-overredaction
# Or: --private-sessions /secure/path/to/private_sessions
```

## 3. Human review on box

Inspect redacted output. Confirm placeholders, phone masks, and no raw customer text you would not ship to evals.

## 4. Merge into harness (on box first)

```bash
python3 evals/milestone-zero/run_trial.py --mode fixture --limit 1
python3 evals/milestone-zero/run_repeat.py --repeats 5 --mode fixture
```

## 5. Leave the box

Copy **only** the redacted JSONL line after steps 2–3. Never copy raw sessions or sidecar name/rule files.
