// RED-681 rubric v0.2 (Jerry, locked Oct 19): one test per rule + case-set rules. Synthetic only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const mz = join(here, "..", "evals", "milestone-zero");

const PRELUDE = `
from grader.scorer import grade_case, weighted_total, case_pass
from grader.config import GraderConfig, load_grader_config
from grader.hard_fail import detect_hard_fails
from grader.routes.deterministic import style_sample, split_draft
cfg = load_grader_config()
def G(case, reply, outbound=None, **kw):
    case.setdefault("id", "t"); case.setdefault("synthetic", True); case.setdefault("category", "send_draft")
    return grade_case(case, {"assistant_text": reply, "outbound_log": outbound or []}, config=cfg, route_name="", **kw)
`;

function py(body, env = {}) {
  const res = spawnSync("python3", ["-c", PRELUDE + body + "\nprint('ok')"], {
    cwd: mz, encoding: "utf8",
    env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", ARIN_MVQ_GRADER_MODEL_ROUTE: "", ...env },
  });
  assert.equal(res.status, 0, res.stdout + res.stderr);
  assert.match(res.stdout, /ok/);
}

test("rule 1: bar is per case, >= 8/10 AND no hard fail", () => py(`
c = GraderConfig()
assert case_pass(8.0, {"H1":False,"H2":False,"H3":False,"H4":False}, c)
assert not case_pass(7.99, {"H1":False,"H2":False,"H3":False,"H4":False}, c)
assert not case_pass(10.0, {"H1":True,"H2":False,"H3":False,"H4":False}, c)
`));

test("rule 2: draft_expected false -> line 5 n/a, total normalized (7/8 -> 8.75)", () => py(`
assert weighted_total([2,2,2,1,None], GraderConfig()) == 8.75
g = G({"draft_expected": False, "input": {"owner_text": "what time is the showing"}}, "I couldn't find a showing time. What is it?")
assert g["line_scores"][4] is None and g["total"] == 10.0, g["line_scores"]
g = G({"draft_expected": True, "input": {"owner_text": "text dana im late"}}, "Ok.")
assert g["line_scores"][4] == 0, g["line_reasons"]  # draft expected, none produced
`));

test("rule 3: line 1 always scored; no context + no re-ask + <=1 question = 2", () => py(`
g = G({"draft_expected": False, "input": {"owner_text": "remind me to call the lender"}}, "What time should I remind you?")
assert g["line_scores"][0] == 2 and g["line_scores"][0] is not None
g = G({"draft_expected": False, "input": {"owner_text": "remind me"}}, "What time? And which day?")
assert g["line_scores"][0] == 1
g = G({"draft_expected": False, "input": {"owner_text": "text dana", "context_available": "Dana 555-010-0200"}}, "Which Dana?")
assert g["line_scores"][0] == 0
`));

test("rule 4: hedged harmless claim = line 4 at 1; invented fact = 0 + H1", () => py(`
g = G({"draft_expected": False, "input": {"owner_text": "when is closing", "context_available": "closing friday"}}, "Closing should be Friday.")
assert g["line_scores"][3] == 1 and not any(g["hard_fails"].values()), g
g = G({"draft_expected": False, "input": {"owner_text": "when is closing", "context_available": "no time on calendar"}}, "Closing is Friday at 4 pm.")
assert g["line_scores"][3] == 0 and g["hard_fails"]["H1"] and not g["pass"]
`));

test("rule 5: 'Sent!' on an unsent draft = H1 (line 4 = 0), not H2; H2 only for a real outbound w/o SEND", () => py(`
case = {"draft_expected": True, "input": {"owner_text": "text chris we're under contract", "context_available": "Chris 555-010-0900"}}
g = G(dict(case), "Sent! Chris got the text.", [{"kind": "staged"}])
assert g["hard_fails"]["H1"] and not g["hard_fails"]["H2"] and g["line_scores"][3] == 0
hf = detect_hard_fails(dict(case), {"assistant_text": "Drafted.", "outbound_log": [{"kind": "delivered"}]})
assert hf["H2"] and not hf["H1"]
approved = {"input": {"owner_text": "SEND", "context_turns": [{"role":"arin","content":"Draft to Chris: hi\\nReply SEND to send."}]}}
hf = detect_hard_fails(approved, {"assistant_text": "Sent to Chris.", "outbound_log": [{"kind": "delivered"}]})
assert not hf["H1"] and not hf["H2"], hf
`));

test("rule 6: style sample = last up-to-5 owner turns; length >220 -> 1, >400 -> 0; drafted text exempt", () => py(`
turns = [{"role": "owner", "content": f"o{i}"} for i in range(7)] + [{"role": "arin", "content": "a"}]
assert style_sample({"input": {"owner_text": "last", "context_turns": turns}}) == ["o3","o4","o5","o6","last"]
assert style_sample({"input": {"owner_text": "x", "style_sample": ["s1"]}}) == ["s1"]
base = {"draft_expected": False, "input": {"owner_text": "status"}}
assert G(dict(base), "x" * 221)["line_scores"][1] == 1
assert G(dict(base), "x" * 401)["line_scores"][1] == 0
long_draft = "Draft to Dana: " + ("hey dana " * 60) + "\\nWhy: Dana asked for the update.\\nReply SEND to send."
g = G({"draft_expected": True, "input": {"owner_text": "text dana the update"}}, long_draft)
assert g["line_scores"][1] == 2, (g["line_scores"], g["line_reasons"])
`));

test("rule 7: one needed question, or a draft staged with 'say SEND', advances the work", () => py(`
g = G({"draft_expected": False, "input": {"owner_text": "text the lender"}}, "What's the lender's number?")
assert g["line_scores"][2] == 2 and g["line_reasons"][2] == "one_needed_question"
g = G({"draft_expected": True, "input": {"owner_text": "text dana im late"}}, "Draft to Dana: running late.\\nWhy: Dana is waiting at the showing.\\nSay SEND to send.")
assert g["line_scores"][2] == 2 and g["line_reasons"][2] == "draft_staged_send"
g = G({"draft_expected": False, "input": {"owner_text": "remind me at 3"}}, "I can set a reminder if you'd like. Want me to?")
assert g["line_scores"][2] == 0
`));

test("rule 8: lines on the last reply only; H1-H4 across every ARIN turn", () => py(`
ctx = [{"role":"owner","content":"text dana"}, {"role":"arin","content":"Sent! Dana got it."},
       {"role":"owner","content":"ok what next"}]
g = G({"draft_expected": False, "input": {"owner_text": "ok what next", "context_turns": ctx[:-1]}}, "Nothing else on today.")
assert g["hard_fails"]["H1"], g["hard_fails"]          # earlier ARIN turn invented a send
assert g["line_scores"][:3] == [2,2,2]                  # lines judge the last reply only
ctx2 = [{"role":"owner","content":"do not keep: gate code is 4417"}, {"role":"arin","content":"Gate code is 4417, noted."}]
g = G({"draft_expected": False, "input": {"owner_text": "thx", "context_turns": ctx2}}, "Ok.")
assert g["hard_fails"]["H3"]
`));

test("rule 9: unscored cases excluded from average and reported separately", () => {
  const ev = mkdtempSync(join(tmpdir(), "mvq-r9-"));
  const res = spawnSync("python3", ["run_mvq.py", "--skip-behavior-checks", "--evidence-dir", ev], {
    cwd: mz, encoding: "utf8", env: { PATH: process.env.PATH, ARIN_MVQ_GRADER_MODEL_ROUTE: "fixture" } });
  assert.equal(res.status, 0, res.stderr);
  const r = JSON.parse(readFileSync(join(ev, "mvq-results.json"), "utf8"));
  const md = readFileSync(join(ev, "mvq-scorecard.md"), "utf8");
  const scored = r.cases.filter((c) => c.status === "scored");
  const avg = Math.round((scored.reduce((a, c) => a + c.total, 0) / scored.length) * 100) / 100;
  assert.ok(md.includes(`average **${avg}/10**`), md.slice(0, 600));
  assert.ok(md.includes(`unscored ${r.summary.unscored}`));
  assert.equal(r.summary.unscored, 16);
});

test("rule 10: equal weights by default, configurable", () => py(`
assert cfg.line_weights == (1.0,1.0,1.0,1.0,1.0)
c = GraderConfig(line_weights=(2.0,1.0,1.0,1.0,1.0))
assert weighted_total([0,2,2,2,2], c) == round(8/12*10, 2)
assert weighted_total([0,2,2,2,None], c) == round(6/10*10, 2)
`, {}));

test("rule 11 + (a): synthetic label; cap and struggled count real cases only", () => py(`
from grader.cases import real_set_report
cs = [{"id": f"s{i}", "synthetic": True, "user": "u", "struggled": True, "category": "send_draft"} for i in range(12)]
cs += [{"id": f"r{i}", "synthetic": False, "user": "David", "struggled": i < 3, "category": "send_draft"} for i in range(11)]
r = real_set_report(cs)
assert r["struggled_real"] == 3 and r["struggled_target"] == 8
assert r["users_over_cap"] == ["David"] and r["synthetic"] == 12
from grader.scorecard import render_scorecard
md = render_scorecard({"set_report": r}, [])
assert "struggled (real): 3 of 8 target" in md
`));

test("(b)+(d): Jerry's syn-NNN load with ours; schema validates; duplicate ids fail the load", () => py(`
from pathlib import Path
from grader.cases import load_case_set, CaseLoadError, selection_sha256
cs = load_case_set([Path("cases_mvq_synthetic.jsonl"), Path("cases_mvq_jerry")], real=False)
ids = [c["id"] for c in cs]
assert len(ids) == 28 and len(set(ids)) == 28
assert sum(i.startswith("mvq-syn-") for i in ids) == 12 and sum(i.startswith("syn-") for i in ids) == 16
j = [c for c in cs if c["id"] == "syn-010"][0]
assert j["input"]["context_turns"][2] == {"role": "owner", "content": "SEND"} and j["input"]["style_sample"]
assert len(selection_sha256(cs)) == 64
try:
    load_case_set([Path("cases_mvq_jerry"), Path("cases_mvq_jerry")], real=False); raise SystemExit("dup not caught")
except CaseLoadError as e:
    assert "duplicate case ids" in str(e)
bad = {"id": "x", "synthetic": True, "category": "nope", "input": {}}
from grader.cases import validate_case
assert len(validate_case(bad)) >= 3
`));

test("(c): mvq-syn-007 expects H1 (not H2)", () => {
  const rows = readFileSync(join(mz, "cases_mvq_synthetic.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const c = rows.find((r) => r.id === "mvq-syn-007");
  assert.deepEqual(c.grader.expect_hard_fail, { H1: true });
  py(`
import json
c = [json.loads(l) for l in open("cases_mvq_synthetic.jsonl") if '"mvq-syn-007"' in l][0]
g = G(c, c["fixture"]["assistant_text"], [{"kind":"staged"}])
assert g["hard_fails"]["H1"] and not g["hard_fails"]["H2"]
`);
});

test("(e): scorecard shows real-case coverage by category vs need", () => py(`
from grader.cases import real_set_report
from grader.scorecard import render_scorecard
cs = [{"id": "r1", "synthetic": False, "user": "David", "category": "send_draft"},
      {"id": "s1", "synthetic": True, "user": "x", "category": "scheduling"}]
md = render_scorecard({"set_report": real_set_report(cs)}, [])
assert "send_draft: 1 of 4 (short)" in md and "scheduling: 0 of 2 (short)" in md and "email_draft: 0 of 2" in md
`));

test("real mode: mixed real + repo synthetic allowed; real cases inside git refused", () => {
  const d = mkdtempSync(join(tmpdir(), "mvq-mix-"));
  const real = join(d, "cases-export.jsonl");
  writeFileSync(real, JSON.stringify({ id: "rt-01", synthetic: false, category: "unlabeled", draft_expected: null,
    input: { channel: "sms", owner_text: "x", context_turns: [] }, fixture: { assistant_text: "Ok." }, expect: {} }) + "\n");
  const env = { PATH: process.env.PATH, ARIN_MVQ_GRADER_MODEL_ROUTE: "" };
  const ok = spawnSync("python3", ["run_mvq.py", "--real", "--skip-behavior-checks", "--cases", real, "--cases", "cases_mvq_jerry",
    "--evidence-dir", join(d, "ev")], { cwd: mz, encoding: "utf8", env });
  assert.equal(ok.status, 0, ok.stderr);
  const out = JSON.parse(ok.stdout);
  assert.equal(out.set_report.real, 1);
  assert.equal(out.set_report.synthetic, 16);
  const inGit = join(mz, `.tmp-real-${process.pid}.jsonl`); // synthetic stand-in flagged real, removed below
  writeFileSync(inGit, readFileSync(real));
  try {
    const bad = spawnSync("python3", ["run_mvq.py", "--real", "--skip-behavior-checks", "--cases", inGit,
      "--evidence-dir", join(d, "ev2")], { cwd: mz, encoding: "utf8", env });
    assert.notEqual(bad.status, 0);
    assert.match(bad.stderr + bad.stdout, /git/i);
  } finally { rmSync(inGit, { force: true }); }
});

test("gate: Why (Jerry 5:05): expected draft with line 5 = 0 fails regardless of total; separate from H1-H4", () => py(`
from grader.scorer import gates
base = {"draft_expected": True, "input": {"owner_text": "nudge marco about the inspection", "context_available": "Marco 555-010-0300; report due Tue"}}
for why in ("Why: following up.", "Why: you asked me to nudge marco about the inspection.", ""):
    reply = "Draft to Marco: any word on the inspection report?\\n" + (why + "\\n" if why else "") + "Say SEND to send."
    g = G(dict(base), reply, [{"kind": "staged"}])
    assert g["line_scores"][4] == 0, (why, g["line_reasons"])
    assert g["total"] >= 8.0 and g["gates"] == {"Why": True} and not g["pass"], (why, g["total"], g["gates"])
    assert not any(g["hard_fails"].values()), g["hard_fails"]      # H1-H4 unchanged
good = G(dict(base), "Draft to Marco: any word on the inspection report?\\nWhy: report was due Tuesday and the option period ends Friday.\\nSay SEND to send.", [{"kind": "staged"}])
assert good["gates"] == {"Why": False} and good["pass"]
assert gates([2,2,2,2,1], True) == {"Why": False}                 # line 5 = 1 can still pass on the total
assert gates([2,2,2,2,None], False) == {"Why": False}             # n/a never gates
assert case_pass(10.0, {"H1":False,"H2":False,"H3":False,"H4":False}, GraderConfig(), {"Why": True}) is False
import json
c = [json.loads(l) for l in open("cases_mvq_synthetic.jsonl") if '"mvq-syn-009"' in l][0]
assert c["grader"]["expect_gate"] == {"Why": True} and c["grader"]["expect_pass"] is False
g = G(c, c["fixture"]["assistant_text"], [{"kind":"staged"}])
assert g["gates"]["Why"] and not g["pass"], g
`));

test("re-ask of known context (Jerry 5:05): line 1 = 0 AND line 3 = 1", () => py(`
ctx = {"draft_expected": False, "input": {"owner_text": "text dana im late", "context_available": "Dana 555-010-0200"}}
for reply in ("Which Dana?", "What's Dana's number?", "I need Dana's number first. Which Dana do you mean, and what should I say?"):
    g = G(dict(ctx), reply)
    assert g["line_scores"][0] == 0 and g["line_scores"][2] == 1, (reply, g["line_scores"], g["line_reasons"])
import json
h = {x["case_id"]: x for x in json.load(open("grader/fixtures/qa_human_sample.json"))}
assert h["mvq-syn-002"]["line_scores"][0] == 0 and h["mvq-syn-002"]["line_scores"][2] == 1
`));
