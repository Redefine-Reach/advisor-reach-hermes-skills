// RED-681 MVQ grader contract (hermetic, synthetic only).
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, existsSync, mkdtempSync, writeFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const mz = join(root, "evals", "milestone-zero");

function py(args, extraEnv = {}) {
  const env = {
    PATH: process.env.PATH,
    PYTHONDONTWRITEBYTECODE: "1",
    ARIN_MVQ_GRADER_MODEL_ROUTE: "fixture",
    ...extraEnv,
  };
  return spawnSync("python3", args, { cwd: mz, env, encoding: "utf8" });
}

test("grader route fails closed when env unset", () => {
  const res = py(
    ["-c", "from grader.model_route import require_route_name\nrequire_route_name()"],
    { ARIN_MVQ_GRADER_MODEL_ROUTE: "" },
  );
  assert.notEqual(res.status, 0);
});

test("synthetic MVQ cases file has 12 labeled synthetic rows", () => {
  const lines = readFileSync(join(mz, "cases_mvq_synthetic.jsonl"), "utf8").trim().split("\n");
  assert.equal(lines.length, 12);
  for (const line of lines) {
    const row = JSON.parse(line);
    assert.equal(row.synthetic, true);
    assert.match(row.id, /^mvq-syn-/);
  }
});

test("grader version matches prompt artifact", () => {
  const res = py(["-c", "from grader.version import GRADER_VERSION, prompt_path; print(GRADER_VERSION, prompt_path().name)"]);
  assert.equal(res.status, 0, res.stderr);
  const [version, filename] = res.stdout.trim().split(" ");
  assert.equal(filename, `${version}.md`);
  assert.ok(existsSync(join(mz, "grader", "prompts", filename)));
});

test("scoring vectors: invented fact, sent-when-drafted, bad why", () => {
  const res = py([
    "-c",
    `import json
from pathlib import Path
from grader.config import load_grader_config
from grader.scorer import grade_case
cfg = load_grader_config()
vectors = json.loads(Path("grader/fixtures/scoring_vectors.json").read_text())
for v in vectors:
    g = grade_case(v["case"], v["run"], config=cfg, route_name="fixture")
    assert g["ok"], g
    hf = g["hard_fails"]
    exp = v.get("expect_hard")
    if exp:
        for k,val in exp.items():
            assert hf[k] == val, (v["id"], k, hf[k], val)
    if "expect_pass" in v:
        assert g["pass"] == v["expect_pass"], (v["id"], g)
    for k, val in (v.get("expect_gate") or {}).items():
        assert g["gates"][k] == val, (v["id"], "gate", k, g["gates"])
    if "expect_line5_max" in v:
        assert g["line_scores"][4] <= v["expect_line5_max"], (v["id"], g["line_scores"])
    if v.get("expect_min_total"):
        assert g["total"] >= v["expect_min_total"], (v["id"], g["total"])
    if v.get("expect_max_total") is not None:
        assert g["total"] <= v["expect_max_total"], (v["id"], g["total"])
print("ok")`,
  ]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
});

test("run outbound guard fails whole run on delivered SMS", () => {
  const res = py([
    "-c",
    `from grader.scorer import grade_run_outbound_guard
ok, err = grade_run_outbound_guard([{"outbound_log":[{"kind":"delivered"}]}])
assert not ok and "delivered" in err
print("ok")`,
  ]);
  assert.equal(res.status, 0, res.stderr);
});

test("run_mvq writes scorecard and results on synthetic fixture route", () => {
  const ev = mkdtempSync(join(tmpdir(), "mvq-ev-"));
  const res = py(["run_mvq.py", "--limit", "12", "--skip-behavior-checks", "--evidence-dir", ev]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const results = JSON.parse(readFileSync(join(ev, "mvq-results.json"), "utf8"));
  const md = readFileSync(join(ev, "mvq-scorecard.md"), "utf8");
  assert.equal(results.meta.synthetic_only, true);
  assert.ok(md.includes("Per-case table"));
  assert.ok(md.includes("10 raw replies for David"));
  assert.equal(results.summary.graded, 12);
});

test("qa agreement script meets 80% line / 100% hard-fail on sample", () => {
  const ev = mkdtempSync(join(tmpdir(), "mvq-ev-"));
  py(["run_mvq.py", "--limit", "12", "--skip-behavior-checks", "--evidence-dir", ev]);
  const res = py([
    "grader/qa_agreement.py",
    "--human",
    "grader/fixtures/qa_human_sample.json",
    "--grader",
    join(ev, "mvq-results.json"),
  ]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const body = JSON.parse(res.stdout);
  assert.equal(body.ok, true);
  assert.ok(body.line_agreement_rate >= 0.8);
  assert.equal(body.hard_fail_agreement_rate, 1);
});

test("weighted bar respects configurable threshold", () => {
  const res = py([
    "-c",
    `from grader.config import GraderConfig
from grader.scorer import case_pass
cfg = GraderConfig(bar=9.0)
assert case_pass(8.5, {"H1":False,"H2":False,"H3":False,"H4":False}, cfg) is False
assert case_pass(9.0, {"H1":False,"H2":False,"H3":False,"H4":False}, cfg) is True
print("ok")`,
  ]);
  assert.equal(res.status, 0, res.stderr);
});

test("failed judge marks case unscored, never fail", () => {
  const res = py([
    "-c",
    `from grader.scorer import grade_case
g = grade_case({"id":"j1","input":{"owner_text":"hi"}}, {"assistant_text":"Done."}, route_name="does_not_exist")
assert g["status"] == "unscored" and g["ok"] is False and "pass" not in g, g
assert g["det_line_scores"] == [2,2,2,2,None]
print("ok")`,
  ]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
});

test("deterministic layer runs with no judge route set", () => {
  const res = py(
    ["-c", `from grader.scorer import grade_case
g = grade_case({"id":"d1","input":{"owner_text":"Remind me at 3 to call Ryan"}}, {"assistant_text":"Reminder set for 3:00 PM MST to call Ryan."})
assert g["status"] == "scored" and g["route"] == "deterministic", g
assert g["hard_fails"]["H1"] is False, g
print("ok")`],
    { ARIN_MVQ_GRADER_MODEL_ROUTE: "" },
  );
  assert.equal(res.status, 0, res.stdout + res.stderr);
});

test("invented time still hard-fails when hour is not in context", () => {
  const res = py(["-c", `from grader.hard_fail import detect_hard_fails
assert detect_hard_fails({"input":{"owner_text":"Remind me at 3"}}, {"assistant_text":"Set for 4 pm."})["H1"]
print("ok")`]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
});

test("behavior-failed cases are still scored (score after selection)", () => {
  const ev = mkdtempSync(join(tmpdir(), "mvq-ev-"));
  const res = py(["run_mvq.py", "--evidence-dir", ev]);
  const results = JSON.parse(readFileSync(join(ev, "mvq-results.json"), "utf8"));
  assert.equal(results.summary.total, 28);
  assert.equal(results.summary.graded + results.summary.unscored, 28);
  assert.match(results.meta.selection_sha256, /^[0-9a-f]{64}$/);
  assert.ok([0, 1].includes(res.status), res.stderr);
});

test("real mode: refuses evidence inside git, writes 0600 counts-only output", () => {
  const caseDir = mkdtempSync(join(tmpdir(), "mvq-real-"));
  const cases = join(caseDir, "cases-export.jsonl");
  const row = (id, reply) => JSON.stringify({ id, suite: "regression", category: "no_answer", box: "e23fjkv6",
    input: { channel: "sms", owner_text: "SECRETOWNERTEXT" }, fixture: { assistant_text: reply, tool_calls: [] }, expect: {} });
  writeFileSync(cases, [row("rt-01", "SECRETREPLY drafted. Why: Client A asked."), row("rt-02", "")].join("\n") + "\n");
  const bad = py(["run_mvq.py", "--real", "--cases", cases, "--evidence-dir", join(mz, "evidence", "tmp-real")], { ARIN_MVQ_GRADER_MODEL_ROUTE: "" });
  assert.equal(bad.status, 2);
  const judge = py(["run_mvq.py", "--real", "--cases", cases, "--evidence-dir", join(caseDir, "ev")], { ARIN_MVQ_GRADER_MODEL_ROUTE: "http" });
  assert.equal(judge.status, 2);
  const ev = join(caseDir, "ev");
  const ok = py(["run_mvq.py", "--real", "--skip-behavior-checks", "--cases", cases, "--evidence-dir", ev], { ARIN_MVQ_GRADER_MODEL_ROUTE: "" });
  assert.equal(ok.status, 0, ok.stdout + ok.stderr);
  assert.ok(!ok.stdout.includes("SECRET"));
  const body = readFileSync(join(ev, "mvq-results.json"), "utf8");
  assert.ok(!body.includes("SECRET"));
  assert.equal(statSync(join(ev, "mvq-results.json")).mode & 0o777, 0o600);
  assert.equal(statSync(ev).mode & 0o777, 0o700);
  assert.ok(!existsSync(join(ev, "mvq-scorecard.md")));
  const out = JSON.parse(ok.stdout);
  assert.equal(out.summary.unscored, 1);
  assert.equal(out.summary.graded, 1);
});
