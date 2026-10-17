// RED-681 MVQ grader contract (hermetic, synthetic only).
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
  const res = py(["run_mvq.py", "--limit", "12", "--skip-behavior-checks"]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const results = JSON.parse(readFileSync(join(mz, "evidence", "mvq-results.json"), "utf8"));
  const md = readFileSync(join(mz, "evidence", "mvq-scorecard.md"), "utf8");
  assert.equal(results.meta.synthetic_only, true);
  assert.ok(md.includes("Per-case table"));
  assert.ok(md.includes("10 raw replies for David"));
  assert.equal(results.summary.graded, 12);
});

test("qa agreement script meets 80% line / 100% hard-fail on sample", () => {
  py(["run_mvq.py", "--limit", "12", "--skip-behavior-checks"]);
  const res = py([
    "grader/qa_agreement.py",
    "--human",
    "grader/fixtures/qa_human_sample.json",
    "--grader",
    "evidence/mvq-results.json",
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
