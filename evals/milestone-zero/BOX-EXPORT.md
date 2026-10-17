# Box-local session export (ARIN TEST `e23fjkv6` only)

Run **on the test box**. Do not SCP raw session JSON off the box. Copy only redacted JSONL lines after this procedure passes.

**Policy:** Nothing leaves a box unredacted. Redaction here is **necessary but not sufficient** — operators still owe a human spot check on-box and Vault review before anything is merged into shared eval corpora.

## 1. Export session from Hermes logs (on box)

Identify the session file under `$HERMES_HOME` (path varies by deployment). Copy it to a working file, e.g. `/tmp/session-raw.json`. Use the operator path your box documents (gateway export, `sessions/` tree, etc.).

Prepare optional sidecar files (mode **0600**, never commit):

- `--known-names` — one known client/person name per line for this box
- `--rules` — `rules.json` with `do_not_keep` phrases (token-normalized matching)
- `--forgotten` — one forgotten phrase per line

## 2. Redact and build case (fail closed)

```bash
cd /opt/data/skills/advisor-reach-hermes-skills   # or your checkout path
python3 evals/milestone-zero/export_session_to_case.py \
  --session /tmp/session-raw.json \
  --id mz-021 \
  --suite regression \
  --category send_draft \
  --known-names /tmp/box-known-names.txt \
  --rules /tmp/donotkeep-rules.json \
  --forgotten /tmp/forgotten-phrases.txt \
  --session-index opaque-7f3a \
  --out evals/milestone-zero/cases-export.local.jsonl \
  --manifest evals/milestone-zero/cases-export.local.manifest.json
```

- Exit **0** (exported): one redacted line appended to `cases-export.local.jsonl` (gitignored: `cases-export*.jsonl`). Stdout stays empty; stderr logs **counts per class only** and `session_index=…` (no source path, no case body).
- Exit **0** (`excluded_sessions: 1`): session matched do-not-keep, forgotten, opt-out, minor, or forget/`/new` rules — **no file written**.
- Exit **1**: decode/JSON error, detector exception, unknown field type, or residue after the independent second pass. **Do not export.**

Output files are created mode **0600**; parent directories **0700**. The manifest is content-free (redaction version, per-class counts, generated date, deletion date +30d).

Optional one-off text redaction:

```bash
python3 evals/milestone-zero/redact.py \
  --in /tmp/session.txt \
  --out /tmp/session.redacted.txt \
  --known-names /tmp/box-known-names.txt \
  --manifest /tmp/session.redacted.manifest.json \
  --fail-closed
```

## 3. Review on box

Inspect `cases-export.local.jsonl`. Confirm placeholders only (`[REDACTED_PHONE]`, `CLIENT_n`, etc.) and no raw customer text you would not want in evals.

## 4. Merge into harness (still on box first)

Validate with fixture replay:

```bash
python3 evals/milestone-zero/run_trial.py --mode fixture --limit 1   # after merging line into cases.jsonl
python3 evals/milestone-zero/run_repeat.py --repeats 5 --mode fixture
```

## 5. Leave the box

Only after steps 2–3 succeed, an operator may copy **the redacted JSONL line** into the git repo on a dev machine. Never copy `session-raw.json` or sidecar name/rule files.
