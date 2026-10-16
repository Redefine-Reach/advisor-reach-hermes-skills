// RED-667 milestone-zero harness contract (hermetic).
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
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

test("cases.jsonl has 20 synthetic milestone-zero rows", () => {
  const lines = readFileSync(join(mz, "cases.jsonl"), "utf8").trim().split("\n");
  assert.equal(lines.length, 20);
  const cats = new Set(lines.map((line) => JSON.parse(line).category));
  assert.ok(cats.has("no_answer"));
  assert.ok(cats.has("send_draft"));
  assert.ok(cats.has("memory_save"));
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
  for (const row of payload.cases) {
    assert.equal(row.pass, true, row.id);
  }
});

test("hermes_bridge pins 0.21.0", () => {
  const res = py(["-c", "from hermes_bridge import HERMES_PIN; print(HERMES_PIN)"]);
  assert.equal(res.stdout.trim(), "0.21.0");
});
