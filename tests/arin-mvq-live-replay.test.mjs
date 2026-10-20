// RED-681: live replay sends each case's context turns before the last owner message,
// one fresh Hermes session per case, SMS provider stubbed. Fake Hermes CLI; synthetic data only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const mz = join(here, "..", "evals", "milestone-zero");
const fake = join(here, "fixtures", "fake-hermes");

function env(extra = {}) {
  return {
    PATH: `${fake}:${process.env.PATH}`,
    PYTHONPATH: join(fake, "pylib"),
    PYTHONDONTWRITEBYTECODE: "1",
    HERMES_HOME: mkdtempSync(join(tmpdir(), "fake-src-home-")),
    ARIN_EVAL_OWNER_PREFIX: "[SMS from box owner +15550100099]",
    ...extra,
  };
}

function py(body, extra = {}) {
  const res = spawnSync("python3", ["-c", `
import json
from hermes_bridge import run_hermes, ensure_live_session, shutdown_live_session
from live_session import replay_turns, hermes_chat_argv
${body}
print("ok")`], { cwd: mz, encoding: "utf8", env: env(extra) });
  assert.equal(res.status, 0, res.stdout + res.stderr);
  assert.match(res.stdout, /ok\s*$/);
}

const CASE = `
case = {"id": "t1", "synthetic": True, "input": {"owner_text": "ok text her that", "context_turns": [
  {"role": "owner", "content": "dana wants the 2pm showing moved"},
  {"role": "arin", "content": "Got it. Move to when?"},
  {"role": "tool", "content": "ignored"},
  {"role": "owner", "content": "4pm"},
  {"role": "arin", "content": "Want me to draft a text to Dana?"}]}}
`;

test("hermes_python: shell shim falls back to /opt/hermes venv python when present", () => py(`
import os, tempfile
from pathlib import Path
from unittest.mock import patch
from live_session import hermes_python, HERMES_VENV_PYTHON
tmpdir = tempfile.mkdtemp()
shim = Path(tmpdir) / "hermes-shim"
shim.write_text("#!/bin/sh\\nexec true\\n", encoding="utf-8")
os.chmod(shim, 0o755)
fake_py = Path(tmpdir) / "python3"
fake_py.write_text("#!/bin/sh\\n", encoding="utf-8")
os.chmod(fake_py, 0o755)
with patch("live_session.HERMES_VENV_PYTHON", fake_py):
    assert hermes_python(str(shim)) == str(fake_py)
assert hermes_python(str(shim)) in (None, str(HERMES_VENV_PYTHON))
os.environ["ARIN_EVAL_HERMES_PYTHON"] = str(fake_py)
assert hermes_python(str(shim)) == str(fake_py)
del os.environ["ARIN_EVAL_HERMES_PYTHON"]
`));

test("hermes_pythonpath_env prepends /opt/hermes without dropping existing PYTHONPATH", () => py(`
from live_session import hermes_pythonpath_env
e = hermes_pythonpath_env({"FOO": "1"})
assert e["PYTHONPATH"] == "/opt/hermes" and e["FOO"] == "1"
e2 = hermes_pythonpath_env({**e, "PYTHONPATH": "/other"})
assert e2["PYTHONPATH"] == "/opt/hermes:/other"
`));

test("replay_turns maps owner/arin to user/assistant, drops tool turns, prefixes owner turns", () => py(CASE + `
t = replay_turns(case)
assert [x["role"] for x in t] == ["user", "assistant", "user", "assistant"], t
assert t[0]["content"].startswith("[SMS from box owner") and not t[1]["content"].startswith("[SMS")
argv = hermes_chat_argv("hermes", "hi", resume="S1")
assert argv[argv.index("--resume") + 1] == "S1" and "--no-restore-cwd" in argv and "--source" in argv
assert "--resume" not in hermes_chat_argv("hermes", "hi")
`));

test("context turns are in the session before the last owner message (reply sees 4 prior turns)", () => py(CASE + `
ctx, err = ensure_live_session(); assert not err, err
try:
    r = run_hermes(case, dry_run=False, live_ctx=ctx)
    assert r["ok"], r
    assert r["context_turns"] == 4 and r["context_turns_replayed"] == 4 and r["fresh_session"]
    assert "ctx=4 " in r["assistant_text"] and r["assistant_text"].endswith("ext her that"), r["assistant_text"]
    import sqlite3
    rows = sqlite3.connect(ctx.hermes_home / "state.db").execute("select role from messages order by rowid").fetchall()
    assert [x[0] for x in rows] == ["user","assistant","user","assistant","user","assistant"], rows
finally:
    shutdown_live_session()
`));

test("fresh session per case: a second case sees a new home and no turns from the first", () => py(CASE + `
ctx, err = ensure_live_session(); assert not err, err
try:
    a = run_hermes(case, dry_run=False, live_ctx=ctx); home_a = a["hermes_home"]
    b = run_hermes({"id": "t2", "input": {"owner_text": "what's on today"}}, dry_run=False, live_ctx=ctx)
    assert b["ok"] and "ctx=0 " in b["assistant_text"] and "fresh=yes" in b["assistant_text"], b["assistant_text"]
    assert b["context_turns"] == 0 and b["hermes_home"] != home_a
    import os; assert not os.path.exists(home_a)   # previous case's home removed
finally:
    shutdown_live_session()
`));

test("no real sends: a send attempt only reaches the local stub (blocked), nothing delivered", () => py(`
ctx, err = ensure_live_session(); assert not err, err
try:
    r = run_hermes({"id": "t3", "input": {"owner_text": "TRY_SEND now", "context_turns": [{"role": "owner", "content": "hi"}]}},
                   dry_run=False, live_ctx=ctx)
    kinds = [e["kind"] for e in r["outbound_log"]]
    assert "blocked" in kinds and "delivered" not in kinds, r["outbound_log"]
    assert ctx.recorder.delivered_count() == 0
    env = ctx.env_overlay()
    assert env["TELNYX_API_KEY"] == "" and env["COMPOSIO_API_KEY"] == ""
finally:
    shutdown_live_session()
`, { COMPOSIO_API_KEY: "should-be-blanked" }));

test("fail closed: seeding failure or a reply outside the seeded session makes the case unscored", () => py(CASE + `
import os
ctx, err = ensure_live_session(); assert not err, err
try:
    os.environ["ARIN_EVAL_HERMES_PYTHON"] = "/nonexistent/python"
    r = run_hermes(case, dry_run=False, live_ctx=ctx)
    assert r["ok"] is False and r["error"].startswith("seed_failed") and r["context_turns_replayed"] == 0, r
    del os.environ["ARIN_EVAL_HERMES_PYTHON"]
    c2 = json.loads(json.dumps(case)); c2["input"]["owner_text"] = "FAKE_NO_PERSIST"
    r = run_hermes(c2, dry_run=False, live_ctx=ctx)
    assert r["ok"] is False and r["error"] == "context_not_in_session", r
finally:
    shutdown_live_session()
`));

test("run_mvq --live: every case with context is replayed, results carry counts only", () => {
  const ev = mkdtempSync(join(tmpdir(), "mvq-live-"));
  const res = spawnSync("python3", ["run_mvq.py", "--live", "--skip-behavior-checks", "--cases", "cases_mvq_jerry",
    "--evidence-dir", ev], { cwd: mz, encoding: "utf8", env: env({ ARIN_MVQ_GRADER_MODEL_ROUTE: "" }) });
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const out = JSON.parse(res.stdout);
  assert.ok(out.context_replay.cases_with_context > 0);
  assert.equal(out.context_replay.cases_replayed, out.context_replay.cases_with_context);
  assert.equal(out.summary.unscored, 0, JSON.stringify(out.summary));
  const r = JSON.parse(readFileSync(join(ev, "mvq-results.json"), "utf8"));
  for (const c of r.cases) assert.equal(c.context_turns_replayed, c.context_turns, c.case_id);
});
