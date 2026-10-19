// RED-681: David's blind PASS/FAIL agreement check (seeded pick + verdict mode). Synthetic only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, rmSync, statSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const mz = join(here, "..", "evals", "milestone-zero");
const ENV = { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", ARIN_MVQ_GRADER_MODEL_ROUTE: "" };

function run(args, env = {}) {
  return spawnSync("python3", args, { cwd: mz, encoding: "utf8", env: { ...ENV, ...env } });
}

function py(body) {
  const res = run(["-c", `import json\nfrom grader.pick_agreement import pick_cases, PickError\nfrom grader.qa_agreement import compare_verdicts, RatingError\n${body}\nprint('ok')`]);
  assert.equal(res.status, 0, res.stdout + res.stderr);
  assert.match(res.stdout, /ok/);
}

// A synthetic "baseline": 14 real-looking (synthetic:false) scored rows, 4 synthetic, 2 unscored.
const ROWS = `
def row(i, p, user, cat, syn=False, h1=False, why=False, de=True, status="scored"):
    return {"case_id": f"c{i:02d}", "status": status, "ok": status == "scored", "pass": p if status == "scored" else None,
            "user": user, "category": cat, "synthetic": syn, "draft_expected": de, "total": 9.0 if p else 5.0,
            "hard_fails": {"H1": h1, "H2": False, "H3": False, "H4": False}, "gates": {"Why": why}}
rows = [
  row(1, True, "David", "send_draft"), row(2, True, "David", "scheduling", de=False),
  row(3, True, "David", "follow_up"), row(4, True, "David", "send_draft"), row(5, True, "David", "email_draft"),
  row(6, True, "Joe", "buyer_profile", de=False), row(7, True, "Joe", "send_draft"),
  row(8, False, "David", "send_draft", h1=True), row(9, False, "Joe", "send_draft", why=True),
  row(10, False, "Ryan", "reask_context", de=False), row(11, False, "Ryan", "follow_up"),
  row(12, False, "Marc", "scheduling"), row(13, False, "Marc", "email_draft"), row(14, False, "Joe", "follow_up"),
  row(15, True, "syn", "send_draft", syn=True), row(16, False, "syn", "invented_fact", syn=True, h1=True),
  row(17, True, "syn", "follow_up", syn=True), row(18, False, "syn", "why_line", syn=True, why=True),
  row(19, None, "David", "send_draft", status="unscored"), row(20, None, "Joe", "send_draft", status="unscored"),
]
results = {"meta": {"grader_version": "mvq-grader-v0.3.1"}, "cases": rows}
`;

test("pick: 5 grader-pass + 5 grader-fail, real first, hard fail + gate: Why, >=2 no-draft, user cap 4", () => py(`${ROWS}
p = pick_cases(results, 20261020)
by = {r["case_id"]: r for r in rows}
ids = p["ids"]
assert len(ids) == 10 and len(set(ids)) == 10
assert sum(1 for i in ids if by[i]["pass"]) == 5, ids
assert all(by[i]["status"] == "scored" for i in ids)          # unscored never picked
assert all(not by[i]["synthetic"] for i in ids), ids           # 14 real scored -> no synthetic needed
assert any(by[i]["hard_fails"]["H1"] and not by[i]["pass"] for i in ids)
assert any(by[i]["gates"]["Why"] and not by[i]["pass"] for i in ids)
assert sum(1 for i in ids if by[i]["draft_expected"] is False) >= 2
users = {}
for i in ids: users[by[i]["user"]] = users.get(by[i]["user"], 0) + 1
assert max(users.values()) <= 4, users
c = p["checks"]
assert c["fail_hard_fail"] == "met" and c["fail_gate_why"] == "met" and c["split"]["grader_pass"] == 5
`));

test("pick: same seed -> same ids in the same order; another seed can differ", () => py(`${ROWS}
a = pick_cases(results, 7)["ids"]; b = pick_cases(results, 7)["ids"]
assert a == b
assert any(pick_cases(results, s)["ids"] != a for s in range(1, 30))
`));

test("pick: short real stratum is filled with labelled synthetic cases", () => py(`${ROWS}
few = [r for r in rows if r["synthetic"] or r["case_id"] in ("c01", "c02", "c03", "c08", "c09", "c10", "c11", "c12", "c13")]
p = pick_cases({"cases": few}, 3)
by = {r["case_id"]: r for r in few}
assert sum(1 for i in p["ids"] if by[i]["pass"]) == 5
assert p["checks"]["real"] == 8 and p["checks"]["synthetic"] == 2, p["checks"]
`));

test("pick: too few scored cases fails closed", () => py(`${ROWS}
try:
    pick_cases({"cases": rows[:4]}, 1); raise SystemExit("expected PickError")
except PickError:
    pass
`));

function syntheticRun() {
  const dir = mkdtempSync(join(tmpdir(), "mvq-agree-"));
  const res = run(["run_mvq.py", "--evidence-dir", join(dir, "ev"), "--replies-out", join(dir, "replies.jsonl")],
    { ARIN_MVQ_GRADER_MODEL_ROUTE: "fixture" });
  assert.equal(res.status, 0, res.stdout + res.stderr);
  const pick = run(["grader/pick_agreement.py", "--results", join(dir, "ev", "mvq-results.json"),
    "--cases", "cases_mvq_synthetic.jsonl", "--cases", "cases_mvq_jerry",
    "--replies", join(dir, "replies.jsonl"), "--seed", "20261020", "--out-dir", join(dir, "pick")]);
  assert.equal(pick.status, 0, pick.stdout + pick.stderr);
  return { dir, pickOut: pick.stdout };
}

test("end to end: blind sheet shows input + reply, never grader scores; files 0600, dir 0700", () => {
  const { dir, pickOut } = syntheticRun();
  try {
    const sheet = readFileSync(join(dir, "pick", "rating-sheet.md"), "utf8");
    const picks = JSON.parse(readFileSync(join(dir, "pick", "picks.json"), "utf8"));
    const form = JSON.parse(readFileSync(join(dir, "pick", "ratings.json"), "utf8"));
    assert.equal(picks.case_ids.length, 10);
    assert.deepEqual(form.map((r) => r.case_id), picks.case_ids);
    assert.ok(form.every((r) => r.verdict === null));
    for (const cid of picks.case_ids) assert.ok(sheet.includes("`" + cid + "`"));
    assert.match(sheet, /ARIN's reply/);
    assert.match(sheet, /Why: Dana is waiting/); // raw reply text is on the sheet
    // No grader output anywhere David can see before rating:
    const body = sheet.slice(sheet.indexOf("## Case 1"));
    assert.match(sheet, /\(synthetic\)/); // synthetic picks are labelled
    for (const bad of [/total/i, /\/10/, /\bH[1-4]\b/, /gate/i, /draft_missing_why|why_present|draft_staged_send/, /grader (pass|fail)/i, /score/i]) {
      assert.doesNotMatch(body, bad);
      assert.doesNotMatch(JSON.stringify(form), bad);
    }
    const pj = JSON.stringify(picks);
    assert.doesNotMatch(pj, /"pass":|"total"|"hard_fails"|"line_scores"/); // no per-case verdicts in picks.json
    assert.doesNotMatch(pickOut, /Dana|Why:/); // stdout: counts only
    assert.equal(statSync(join(dir, "pick")).mode & 0o777, 0o700);
    for (const f of ["picks.json", "rating-sheet.md", "ratings.json"]) assert.equal(statSync(join(dir, "pick", f)).mode & 0o777, 0o600);
    assert.equal(statSync(join(dir, "replies.jsonl")).mode & 0o777, 0o600);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

function rate(dir, verdictFor) {
  const picks = JSON.parse(readFileSync(join(dir, "pick", "picks.json"), "utf8"));
  const res = JSON.parse(readFileSync(join(dir, "ev", "mvq-results.json"), "utf8"));
  const g = Object.fromEntries(res.cases.map((c) => [c.case_id, c]));
  const rows = picks.case_ids.map((id, i) => ({ case_id: id, ...verdictFor(g[id], i), note: "PRIVATE-NOTE-" + i }));
  writeFileSync(join(dir, "pick", "ratings.json"), JSON.stringify(rows));
  return rows;
}

function verdict(dir, extra = []) {
  return run(["grader/qa_agreement.py", "--mode", "verdict", "--human", join(dir, "pick", "ratings.json"),
    "--grader", join(dir, "ev", "mvq-results.json"), "--picks", join(dir, "pick", "picks.json"), ...extra]);
}

test("verdict mode: refuses to compare (and shows nothing) until all 10 are rated", () => {
  const { dir } = syntheticRun();
  try {
    const res = verdict(dir);
    assert.equal(res.status, 2);
    assert.match(res.stderr, /10 of 10 cases not rated yet/);
    assert.doesNotMatch(res.stdout + res.stderr, /agreement|both_pass|grader_lenient/);
    rate(dir, (g, i) => (i === 0 ? { verdict: null } : { verdict: g.pass ? "PASS" : "FAIL" }));
    const res2 = verdict(dir, ["--side-by-side", join(dir, "pick", "side-by-side.md")]);
    assert.equal(res2.status, 2);
    assert.ok(!existsSync(join(dir, "pick", "side-by-side.md")));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verdict mode: 10/10 and 8/10 sign off; 7/10 is below target", () => {
  const { dir } = syntheticRun();
  try {
    rate(dir, (g) => ({ verdict: g.pass ? "PASS" : "FAIL", fail_reason: g.pass ? null : "other" }));
    let res = verdict(dir, ["--side-by-side", join(dir, "pick", "side-by-side.md")]);
    assert.equal(res.status, 0, res.stdout + res.stderr);
    let body = JSON.parse(res.stdout);
    assert.equal(body.agreement, 10); assert.equal(body.status, "pass"); assert.equal(body.kappa, 1);
    assert.doesNotMatch(res.stdout, /PRIVATE-NOTE/); // notes never on stdout
    const sbs = readFileSync(join(dir, "pick", "side-by-side.md"), "utf8");
    assert.match(sbs, /PRIVATE-NOTE-0/); assert.match(sbs, /10\/10/);
    assert.equal(statSync(join(dir, "pick", "side-by-side.md")).mode & 0o777, 0o600);

    // 2 grader-strict disagreements (grader FAIL, David PASS) -> 8/10, still signs off
    let flipped = 0;
    rate(dir, (g) => {
      if (!g.pass && flipped < 2) { flipped++; return { verdict: "PASS" }; }
      return { verdict: g.pass ? "PASS" : "FAIL", fail_reason: g.pass ? null : "other" };
    });
    res = verdict(dir); body = JSON.parse(res.stdout);
    assert.equal(res.status, 0, res.stdout); assert.equal(body.agreement, 8); assert.equal(body.table.grader_strict, 2);
    assert.equal(body.disagreeing_case_ids.length, 2);

    flipped = 0;
    rate(dir, (g) => {
      if (!g.pass && flipped < 3) { flipped++; return { verdict: "PASS" }; }
      return { verdict: g.pass ? "PASS" : "FAIL", fail_reason: g.pass ? null : "other" };
    });
    res = verdict(dir); body = JSON.parse(res.stdout);
    assert.equal(res.status, 1); assert.equal(body.agreement, 7); assert.equal(body.status, "below_target");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verdict mode: a grader PASS that David FAILs for an invented fact, a send or privacy blocks sign-off even at 9/10", () => {
  for (const reason of ["invented_fact", "send", "privacy"]) {
    py(`
grader = [{"case_id": f"c{i}", "status": "scored", "pass": i < 5} for i in range(10)]
human = [{"case_id": f"c{i}", "verdict": "PASS" if i < 5 else "FAIL", "fail_reason": None if i < 5 else "other"} for i in range(10)]
human[0] = {"case_id": "c0", "verdict": "FAIL", "fail_reason": "${reason}", "note": "x"}
r = compare_verdicts(human, grader)
assert r["agreement"] == 9 and r["table"]["grader_lenient"] == 1
assert r["ok"] is False and r["status"] == "blocked_grader_lenient" and r["blocking_case_ids"] == ["c0"], r
`);
  }
});

test("verdict mode: grader-lenient FAIL with no reason stays pending; 'other' is a plain disagreement", () => py(`
grader = [{"case_id": f"c{i}", "status": "scored", "pass": i < 5} for i in range(10)]
human = [{"case_id": f"c{i}", "verdict": "PASS" if i < 5 else "FAIL"} for i in range(10)]
human[0] = {"case_id": "c0", "verdict": "FAIL"}
r = compare_verdicts(human, grader)
assert r["status"] == "pending_fail_reason" and r["ok"] is False and r["needs_fail_reason_case_ids"] == ["c0"]
human[0]["fail_reason"] = "other"
r = compare_verdicts(human, grader)
assert r["status"] == "pass" and r["agreement"] == 9
`));

test("verdict mode: ids must match picks.json; bad reason, duplicate or unscored case is refused", () => py(`
grader = [{"case_id": f"c{i}", "status": "scored", "pass": True} for i in range(10)] + [{"case_id": "u", "status": "unscored"}]
human = [{"case_id": f"c{i}", "verdict": "PASS"} for i in range(10)]
for bad, kw in (
    (human, {"expected_ids": [f"c{i}" for i in range(1, 11)]}),
    (human[:9] + [{"case_id": "c9", "verdict": "FAIL", "fail_reason": "vibes"}], {}),
    (human[:9] + [{"case_id": "c8", "verdict": "PASS"}], {}),
    (human[:9] + [{"case_id": "u", "verdict": "PASS"}], {}),
):
    try:
        compare_verdicts(bad, grader, **kw); raise SystemExit("expected RatingError")
    except RatingError:
        pass
`));

test("lines mode is unchanged (QA sample still agrees)", () => {
  const dir = mkdtempSync(join(tmpdir(), "mvq-agree-lines-"));
  try {
    const r = run(["run_mvq.py", "--evidence-dir", dir], { ARIN_MVQ_GRADER_MODEL_ROUTE: "fixture" });
    assert.equal(r.status, 0, r.stderr);
    const res = run(["grader/qa_agreement.py", "--human", "grader/fixtures/qa_human_sample.json", "--grader", join(dir, "mvq-results.json")]);
    assert.equal(res.status, 0, res.stdout + res.stderr);
    assert.equal(JSON.parse(res.stdout).hard_fail_agreement_rate, 1);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("run_mvq --real refuses --replies-out inside a git worktree", () => {
  const res = run(["run_mvq.py", "--real", "--evidence-dir", "/tmp/x-mvq-never", "--replies-out", join(mz, "replies.jsonl")]);
  assert.equal(res.status, 2);
  assert.match(res.stderr, /replies-out must be outside/);
  assert.ok(!existsSync(join(mz, "replies.jsonl")));
});
