# Box-local session export (ARIN TEST `e23fjkv6` only)

Run **on the test box**. Do not SCP raw session JSON off the box. Copy only redacted JSONL lines after this procedure passes.

## 1. Export session from Hermes logs (on box)

Identify the session file under `$HERMES_HOME` (path varies by deployment). Copy it to a working file, e.g. `/tmp/session-raw.json`. Use the operator path your box documents (gateway export, `sessions/` tree, etc.).

## 2. Redact and build case (fail closed)

```bash
cd /opt/data/skills/advisor-reach-hermes-skills   # or your checkout path
python3 evals/milestone-zero/export_session_to_case.py \
  --session /tmp/session-raw.json \
  --id mz-021 \
  --suite regression \
  --category send_draft \
  --out evals/milestone-zero/cases-export.local.jsonl
```

- Exit **0**: one redacted line appended to `cases-export.local.jsonl` (gitignored pattern: `cases-export*.jsonl`).
- Exit **1**: redaction residue (SSN, account, health). **Do not export.** Fix source or extend redact rules on-box.

Optional one-off text redaction:

```bash
python3 evals/milestone-zero/redact.py --in /tmp/session.txt --out /tmp/session.redacted.txt --fail-closed
```

## 3. Review on box

Inspect `cases-export.local.jsonl`. Confirm no phones, names of real customers, or bodies you do not want in evals.

## 4. Merge into harness (still on box first)

Validate with fixture replay:

```bash
python3 evals/milestone-zero/run_trial.py --mode fixture --limit 1   # after merging line into cases.jsonl
python3 evals/milestone-zero/run_repeat.py --repeats 5 --mode fixture
```

## 5. Leave the box

Only after steps 2–3 succeed, an operator may copy **the redacted JSONL line** into the git repo on a dev machine. Never copy `session-raw.json`.
