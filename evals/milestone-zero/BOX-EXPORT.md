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

Identify the session file under `$HERMES_HOME`. Copy it into `$D/raw-input/` (0700, see step 2) and nowhere else: **never `/tmp`** or any other path, because step 2's shred only covers `$D/raw-input`, `$D/names.txt` and the exporter copy. Sidecars (mode **0600**, never commit):

- `--known-names` — **required** for real JSONL export (`--out` / default append path). Per-box contact list (mode **0600**, never commit). Case-insensitive whole-word redaction for lowercase texting-style names; export **blocks (exit 1)** if omitted. `--redacted-text-out` has the same gates as `--out` (known names, `--source`, 0600/0700, no git checkout; tool-turn text is never written) and is for the CI leak check on synthetic fixtures only: **do not use it, or `--fixture-check`, on the box.** `--fixture-check` only accepts sessions under the repo's fixture dirs.  
- `--owner-name` — the only name ever kept (no built-in keep-list). Set it to the box owner's first name (`David`).
- `--rules` — `donotkeep_rules.json` with `do_not_keep` phrases (token-normalized, ≥75% overlap)  
- `--forgotten` — forgotten phrases (same matching)

## 2. Redact and build case (fail closed)

Real export (RED-681, Vault Oct 19): **every eligible section** of the owner's own text / CLI / API sessions, never automated runs and never selected by category. One process per section; `--source` comes from the state.db metadata for that session.

```bash
umask 077
D=/opt/data/eval-export/<run>          # 0700, outside any git checkout
X=<exporter copy>                       # PR #56 files, deleted with raw-input
python3 $X/export_session_to_case.py \
  --session $D/raw-input/<section>.json \
  --source cli \
  --id rt-01 \
  --owner-name David \
  --known-names $D/names.txt \
  --out $D/redacted/cases-export.jsonl \
  --manifest $D/redacted/manifests/rt-01.manifest.json 2>>$D/redacted/export-run.log
python3 $X/export_session_to_case.py --check-perms $D     # exit 1 + paths if anything is looser than 0600/0700
python3 $X/export_session_to_case.py --summarize $D/redacted/cases-export.jsonl   # ids and counts only
# Same session, before 3 AM AZ (daily snapshot): shred raw copies and the names file
# Each step runs even if an earlier one fails (no && chain), so names.txt is always removed.
# shred is best effort on overlay/COW filesystems; the delete is what matters.
find $D/raw-input -type f -exec shred -u {} + ; rm -rf $D/raw-input
shred -u $D/names.txt ; rm -f $D/names.txt
rm -rf $X
ls -A $D    # expect only redacted/ (counts-only check: ls -A $D | wc -l)
```

- **What a case keeps:** up to `--context-turns` (default 10) owner/ARIN turns before the last owner message, the last owner message, and the recorded ARIN reply (every ARIN turn after it; empty if the section ends on the owner). Tool/system turns are dropped (counted in `export_meta.turns_skipped_non_text`).
- **Whole-case redaction:** redaction, the drop rules, the health/legal guard and the residue scan run over every turn kept, not only the owner turn. A name detected anywhere is replaced in every turn with the same placeholder. The kept text is re-scanned right before writing.
- **Sources:** `--source` is required for real exports. Only `telnyx_sms`, `cli` and `api_server` are exported. Anything else (cron, telegram, webhook), or a mismatch with the session's own `source` field, is excluded (exit 2).
- **Permissions:** the export checks every path it will write (output file and dir, manifest and its `manifests/` dir, `--redacted-text-out` and its dir) **before writing anything**, and refuses (exit 1, no output) when a dir is looser than 0700 or an existing file looser than 0600 (for example after an fsGroup relabel). It re-checks after writing. `--check-perms DIR` checks a whole tree (setgid is allowed).
- **No case text in git:** `--out`, `--redacted-text-out` or `--manifest` inside a git worktree is refused (exit 1).
- **Top-level `tool_calls`** in a session are dropped (`fixture.tool_calls` is always `[]`; the count is in `export_meta.tool_calls_dropped`).
- **Names:** every word in the `--known-names` file is a name in any case and any position. One token after "text" (any case) plus an optional surname (capitalized, or lowercase unless it is an ordinary word), each token mapped separately, so "text Rosalind about" maps `Rosalind` and a later "Rosalind confirmed" is replaced too; a weekday or month followed by a surname after "text" ("text Sunday Reyes") is a person. A capitalized word at the start of a sentence, a line, a reply or a `Why:` line is a name when it is not in `common_words.txt` (after simple suffix stripping), whatever follows; dictionary words there are still a name when followed by a person verb, a possessive, a comma/colon, an adverb, a surname or the end of the line. ALL-CAPS words that are not ordinary English or a common acronym are names. Only `--owner-name` is ever kept: there is no built-in keep-list, so words such as Grace, Bill or Summer are redacted when they look like names (over-redaction is the safe failure). A do-not-keep rule that names a person drops any session mentioning that name. Still missed (the human read must look): lowercase nicknames not in the names file, Will/May/June/April as people, dictionary words used as names mid-shape.
- `--category` is a label only (default `unlabeled`). The case labeller sets it later.

- **Health or legal topic** (including common rewordings): entire session **excluded** (exit **2**), not redacted in place. A **second, independent** conservative pass (`conservative_guard.py`) re-scans redacted text; any residual health/legal/family/financial/credential-ish signal also forces exit **2** (default-deny).  
- **Phones** (10-digit, +1, 7-digit local): masked as `[PHONE ***1234]` (last four only).  
- Stdout stays empty; stderr logs **counts per class only** and `session_index=…` (no source path, no case body).

Leak-check helper (synthetic fixtures in CI):

```bash
python3 evals/milestone-zero/check_leaks.py \
  --cwd evals/milestone-zero \
  --cmd 'python3 export_session_to_case.py --session {in} --redacted-text-out {out} --known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex --source cli' \
  --strict-drop --fail-on-overredaction
python3 evals/milestone-zero/check_leaks.py \
  --cwd evals/milestone-zero --sessions fixtures/fake_sessions_heldout2 \
  --label heldout2 --strict-drop --fail-on-overredaction \
  --cmd 'python3 export_session_to_case.py --session {in} --redacted-text-out {out} --known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex --source cli'
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
