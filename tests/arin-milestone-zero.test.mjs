// RED-667 milestone-zero harness contract (hermetic).
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const mz = join(root, "evals", "milestone-zero");

function py(args, extraEnv = {}) {
  const env = { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", ...extraEnv };
  return spawnSync("python3", args, { cwd: mz, env, encoding: "utf8" });
}

test("redact strips SSN-shaped spans", () => {
  const raw = "Patient SSN 123-45-6789 and account #123456789012";
  const res = py(["-c", `from redact import redact; import json; print(json.dumps(redact(${JSON.stringify(raw)})))`]);
  assert.equal(res.status, 0, res.stderr);
  const [, codes] = JSON.parse(res.stdout.trim());
  assert.ok(codes.includes("ssn"));
});

test("redact --fail-closed exits 1 when residue remains", () => {
  const dir = mkdtempSync(join(tmpdir(), "mz-redact-"));
  const inp = join(dir, "in.txt");
  writeFileSync(inp, "placeholder");
  const out = join(dir, "out.txt");
  const res = py([
    "-c",
    `import sys
from unittest.mock import patch
import redact
with patch.object(redact, "redact_fail_closed", return_value=("x", [], False, ["ssn"])):
    code = redact.main(["--in", ${JSON.stringify(inp)}, "--out", ${JSON.stringify(out)}, "--fail-closed"])
sys.exit(code)`,
  ]);
  assert.equal(res.status, 1);
});

test("cases.jsonl has 20 rows with suite tags", () => {
  const lines = readFileSync(join(mz, "cases.jsonl"), "utf8").trim().split("\n");
  assert.equal(lines.length, 20);
  const rows = lines.map((line) => JSON.parse(line));
  const suites = new Set(rows.map((r) => r.suite));
  assert.ok(suites.has("regression"));
  assert.ok(suites.has("capability"));
  const cats = new Set(rows.map((r) => r.category));
  assert.ok(cats.has("no_answer"));
  assert.ok(cats.has("send_draft"));
  assert.ok(cats.has("memory_save"));
});

test("SEND gate uses outbound log not assistant SEND text", () => {
  const res = py([
    "-c",
    `import json
from checks import run_checks
case={"id":"t","expect":{"send_staged_not_sent":True}}
bad={"assistant_text":"no send token","outbound_log":[]}
good={"assistant_text":"plain reply","outbound_log":[{"kind":"staged"}]}
print(json.dumps([run_checks(case,bad)[0], run_checks(case,good)[0]]))`,
  ]);
  assert.equal(res.status, 0, res.stderr);
  const [badOk, goodOk] = JSON.parse(res.stdout.trim());
  assert.equal(badOk, false);
  assert.equal(goodOk, true);
});

test("fixture trial passes all cases and writes evidence", () => {
  const res = py(["run_trial.py", "--limit", "20", "--mode", "fixture", "--skip-inspect"]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const evidence = join(mz, "evidence", "trial-results.json");
  assert.equal(existsSync(evidence), true);
  const payload = JSON.parse(readFileSync(evidence, "utf8"));
  assert.equal(payload.summary.total, 20);
  assert.equal(payload.summary.passed, 20);
  assert.equal(payload.hermes_pin, "0.21.0");
  assert.equal(payload.box, "e23fjkv6");
});

test("repeat runner requires 5 runs and passes on fixture", () => {
  const res = py(["run_repeat.py", "--repeats", "5", "--mode", "fixture", "--limit", "20"]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const payload = JSON.parse(readFileSync(join(mz, "evidence", "repeat-results.json"), "utf8"));
  assert.equal(payload.repeats, 5);
  assert.equal(payload.summary.failed, 0);
});

test("live hermes path with stub records outbound and blocks delivered", () => {
  const res = py(
    [
      "-c",
      `import json
from hermes_bridge import run_hermes
from outbound_stub import OutboundRecorder
from checks import run_checks
case=json.loads(open("cases.jsonl").readline())
rec=OutboundRecorder()
run=run_hermes(case, dry_run=False, recorder=rec)
ok,failures=run_checks(case, run)
print(json.dumps({"ok":ok,"delivered":rec.delivered_count(),"mode":run.get("mode")}))`,
    ],
    { ARIN_EVAL_STUB_HERMES: "1", HERMES_VERSION: "0.21.0" },
  );
  assert.equal(res.status, 0, res.stderr);
  const body = JSON.parse(res.stdout.trim());
  assert.equal(body.ok, true);
  assert.equal(body.delivered, 0);
  assert.equal(body.mode, "hermes");
});

test("hermes_bridge pins 0.21.0", () => {
  const res = py(["-c", "from hermes_bridge import HERMES_PIN; print(HERMES_PIN)"]);
  assert.equal(res.stdout.trim(), "0.21.0");
});

test("hermes chat argv uses -Q -q for Hermes 0.21.0", () => {
  const res = py([
    "-c",
    `from live_session import hermes_chat_argv
a=hermes_chat_argv("/usr/bin/hermes","hello owner")
print(" ".join(a))`,
  ]);
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /chat -Q -q .*hello owner/);
});

test("interception probe passes against local stub", () => {
  const res = py([
    "-c",
    `import tempfile
from pathlib import Path
from outbound_stub import OutboundRecorder, start_http_stub
from live_session import write_sms_stub_files, interception_probe
rec=OutboundRecorder()
srv, base = start_http_stub(rec)
d=Path(tempfile.mkdtemp())
rt, pe = write_sms_stub_files(base, d)
ok, detail = interception_probe(base, rt, pe)
srv.shutdown()
import sys; sys.exit(0 if ok else 1)`,
  ]);
  assert.equal(res.status, 0, res.stderr + res.stdout);
});

test("mz-002 and mz-007 are fixture-only in live mode", () => {
  const lines = readFileSync(join(mz, "cases.jsonl"), "utf8").trim().split("\n");
  const rows = lines.map((l) => JSON.parse(l));
  for (const id of ["mz-002", "mz-007"]) {
    const row = rows.find((r) => r.id === id);
    assert.equal(row.live_mode, "fixture_only");
  }
});
