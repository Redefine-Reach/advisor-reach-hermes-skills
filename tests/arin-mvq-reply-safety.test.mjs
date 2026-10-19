// RED-681 / Vault PR #57 review: raw ARIN replies are scanned and redacted before any sheet, a
// credential blocks, raw replies are shredded, outputs follow the exporter's permission rules,
// every output has a deletion date, and the eval HERMES_HOME is built from an allowlist.
// Synthetic / fake data only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, statSync, existsSync, chmodSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const mz = join(here, "..", "evals", "milestone-zero");
const ENV = { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", ARIN_MVQ_GRADER_MODEL_ROUTE: "fixture" };
const FAKE_KEY = "sk_live_FAKEabc123xyz789";
const FAKE_PHONE = "480-555-0177";
const FAKE_NAME = "Octavian Wrexley";

function run(args, env = {}) {
  return spawnSync("python3", args, { cwd: mz, encoding: "utf8", env: { ...ENV, ...env } });
}

function tmp(prefix) {
  const d = mkdtempSync(join(tmpdir(), prefix));
  chmodSync(d, 0o700);
  return d;
}

function baseline(dir, cases = ["cases_mvq_synthetic.jsonl", "cases_mvq_jerry"]) {
  const res = run(["run_mvq.py", "--evidence-dir", join(dir, "ev"), "--replies-out", join(dir, "raw", "replies.jsonl"),
    ...cases.flatMap((c) => ["--cases", c])]);
  return res;
}

function pick(dir, extra = [], cases = ["cases_mvq_synthetic.jsonl", "cases_mvq_jerry"]) {
  return run(["grader/pick_agreement.py", "--results", join(dir, "ev", "mvq-results.json"),
    ...cases.flatMap((c) => ["--cases", c]), "--replies", join(dir, "raw", "replies.jsonl"),
    "--seed", "20261020", "--out-dir", join(dir, "pick"), ...extra]);
}

function plantReplies(dir, fn) {
  const f = join(dir, "raw", "replies.jsonl");
  const rows = readFileSync(f, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  writeFileSync(f, rows.map((r, i) => JSON.stringify({ ...r, assistant_text: fn(r, i) })).join("\n") + "\n");
  return rows.map((r) => r.case_id);
}

test("a reply with a phone number and a known name is redacted on the sheet, counted and flagged", () => {
  const dir = tmp("mvq-safe-");
  try {
    assert.equal(baseline(dir).status, 0);
    plantReplies(dir, (r) => `Texted nothing yet. ${FAKE_NAME} asked you to call ${FAKE_PHONE}. Reply SEND to send.`);
    const names = join(dir, "names.txt");
    writeFileSync(names, FAKE_NAME + "\n"); chmodSync(names, 0o600);
    const res = pick(dir, ["--known-names", names]);
    assert.equal(res.status, 0, res.stdout + res.stderr);
    const sheet = readFileSync(join(dir, "pick", "rating-sheet.md"), "utf8");
    assert.doesNotMatch(sheet, /Octavian|Wrexley/);
    assert.doesNotMatch(sheet.replace(/[-\s]/g, ""), /4805550177/);
    assert.match(sheet, /\[PHONE \*\*\*0177\]/);
    assert.match(sheet, /_Check: ARIN's reply had phone details/);
    const picks = JSON.parse(readFileSync(join(dir, "pick", "picks.json"), "utf8"));
    for (const id of picks.case_ids) {
      assert.ok(picks.reply_scan[id].phone >= 1 && picks.reply_scan[id].name >= 1, id);
      assert.deepEqual(picks.reply_flags[id], ["phone"]);
    }
    assert.doesNotMatch(JSON.stringify(picks) + res.stdout + res.stderr, /Octavian|0177/);
    assert.ok(!existsSync(join(dir, "raw", "replies.jsonl"))); // raw file gone after the sheet
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("pick_agreement: a reply containing a fake API key blocks; nothing written, id reported, never the value", () => {
  const dir = tmp("mvq-safe-");
  try {
    assert.equal(baseline(dir).status, 0);
    const ids = plantReplies(dir, (r, i) => (i === 0 ? `Here is the key: ${FAKE_KEY}` : r.assistant_text));
    const res = pick(dir);
    const out = res.stdout + res.stderr;
    if (res.status === 3) {
      assert.match(res.stderr, /reply_credential/);
      assert.ok(JSON.parse(res.stderr).case_ids.includes(ids[0]));
      assert.ok(!existsSync(join(dir, "pick")) || readdirSync(join(dir, "pick")).length === 0);
      assert.ok(existsSync(join(dir, "raw", "replies.jsonl"))); // not shredded: no sheet was made
    } else {
      // the planted case was not among the 10 picks: the sheet must still be key-free
      assert.equal(res.status, 0, out);
      assert.doesNotMatch(readFileSync(join(dir, "pick", "rating-sheet.md"), "utf8"), /sk_live_/);
    }
    assert.doesNotMatch(out, /sk_live_|FAKEabc/);
    // Force the planted case into the picks: every reply carries the key -> always blocked.
    rmSync(join(dir, "pick"), { recursive: true, force: true });
    assert.equal(baseline(dir).status, 0);
    plantReplies(dir, () => `token: ${FAKE_KEY}`);
    const res2 = pick(dir);
    assert.equal(res2.status, 3, res2.stdout + res2.stderr);
    assert.equal(JSON.parse(res2.stderr).case_ids.length, 10);
    assert.doesNotMatch(res2.stdout + res2.stderr, /sk_live_|FAKEabc/);
    assert.ok(!existsSync(join(dir, "pick", "rating-sheet.md")));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("run_mvq: a reply with a key is blocked, never graded PASS, never written to --replies-out; exit 5 with ids", () => {
  const dir = tmp("mvq-safe-");
  try {
    const src = readFileSync(join(mz, "cases_mvq_synthetic.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    src[0].fixture.assistant_text = `Draft ready. Your Stripe key is ${FAKE_KEY}\nWhy: you asked.\nReply SEND to send.`;
    const cf = join(dir, "cases.jsonl");
    writeFileSync(cf, src.map((c) => JSON.stringify(c)).join("\n") + "\n");
    const res = baseline(dir, [cf]);
    assert.equal(res.status, 5, res.stdout + res.stderr);
    assert.deepEqual(JSON.parse(res.stderr.trim().split("\n").pop()).case_ids, [src[0].id]);
    assert.doesNotMatch(res.stdout + res.stderr, /sk_live_|FAKEabc/);
    const results = JSON.parse(readFileSync(join(dir, "ev", "mvq-results.json"), "utf8"));
    const row = results.cases.find((c) => c.case_id === src[0].id);
    assert.equal(row.status, "blocked_credential"); assert.notEqual(row.pass, true);
    assert.equal(results.summary.blocked_credential, 1);
    const replies = readFileSync(join(dir, "raw", "replies.jsonl"), "utf8");
    assert.doesNotMatch(replies, /sk_live_/);
    assert.ok(!replies.includes(`"${src[0].id}"`));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("--keep-raw-replies keeps the file for synthetic picks and is refused for real picks", () => {
  const dir = tmp("mvq-safe-");
  try {
    assert.equal(baseline(dir).status, 0);
    const res = pick(dir, ["--keep-raw-replies"]);
    assert.equal(res.status, 0, res.stdout + res.stderr);
    assert.equal(JSON.parse(res.stdout).raw_replies, "kept_synthetic");
    assert.ok(existsSync(join(dir, "raw", "replies.jsonl")));
    // results with real (synthetic:false) rows -> refused before anything is written
    const rows = Array.from({ length: 12 }, (_, i) => ({ case_id: `r${i}`, status: "scored", ok: true, pass: i % 2 === 0,
      user: `u${i % 4}`, category: `c${i % 3}`, synthetic: false, draft_expected: i < 3 ? false : true,
      hard_fails: { H1: i === 1 }, gates: { Why: i === 3 } }));
    const rf = join(dir, "real-results.json"); writeFileSync(rf, JSON.stringify({ cases: rows }));
    const res2 = run(["grader/pick_agreement.py", "--results", rf, "--cases", "cases_mvq_synthetic.jsonl",
      "--seed", "1", "--out-dir", join(dir, "pick-real"), "--keep-raw-replies"]);
    assert.equal(res2.status, 2);
    assert.match(res2.stderr, /keep-raw-replies is for synthetic/);
    assert.ok(!existsSync(join(dir, "pick-real")));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("permissions are checked before any write: loose folder, setgid folder, loose parent, loose file, git checkout", () => {
  const dir = tmp("mvq-safe-");
  try {
    assert.equal(baseline(dir, ["cases_mvq_synthetic.jsonl"]).status, 0);
    const cases = ["cases_mvq_synthetic.jsonl"];
    // existing 0755 out-dir: refused, not chmod'ed, nothing written
    mkdirSync(join(dir, "pick"), { mode: 0o755 }); chmodSync(join(dir, "pick"), 0o755);
    let r = pick(dir, [], cases);
    assert.equal(r.status, 2, r.stdout + r.stderr); assert.match(r.stderr, /loose_permissions/);
    assert.equal(statSync(join(dir, "pick")).mode & 0o7777, 0o755);
    assert.deepEqual(readdirSync(join(dir, "pick")), []);
    // setgid 2770 out-dir
    chmodSync(join(dir, "pick"), 0o2770);
    r = pick(dir, [], cases);
    assert.equal(r.status, 2); assert.equal(statSync(join(dir, "pick")).mode & 0o7777, 0o2770);
    assert.deepEqual(readdirSync(join(dir, "pick")), []);
    // 0700 out-dir under a loose (0755) parent
    rmSync(join(dir, "pick"), { recursive: true });
    mkdirSync(join(dir, "loose"), { mode: 0o755 }); chmodSync(join(dir, "loose"), 0o755);
    r = run(["grader/pick_agreement.py", "--results", join(dir, "ev", "mvq-results.json"), "--cases", cases[0],
      "--replies", join(dir, "raw", "replies.jsonl"), "--seed", "1", "--out-dir", join(dir, "loose", "pick")]);
    assert.equal(r.status, 2); assert.ok(!existsSync(join(dir, "loose", "pick")));
    // an existing 0644 rating-sheet.md is refused (never truncated then chmod'ed)
    mkdirSync(join(dir, "pick"), { mode: 0o700 });
    writeFileSync(join(dir, "pick", "rating-sheet.md"), "old\n"); chmodSync(join(dir, "pick", "rating-sheet.md"), 0o644);
    r = pick(dir, [], cases);
    assert.equal(r.status, 2); assert.equal(readFileSync(join(dir, "pick", "rating-sheet.md"), "utf8"), "old\n");
    assert.ok(existsSync(join(dir, "raw", "replies.jsonl"))); // nothing shredded on refusal
    // run_mvq --replies-out into a loose folder: refused before the run
    r = run(["run_mvq.py", "--evidence-dir", join(dir, "ev2"), "--replies-out", join(dir, "loose", "replies.jsonl")]);
    assert.equal(r.status, 2); assert.ok(!existsSync(join(dir, "loose", "replies.jsonl"))); assert.ok(!existsSync(join(dir, "ev2")));
    // qa_agreement --side-by-side inside a git checkout or a loose folder: refused, nothing written
    rmSync(join(dir, "pick"), { recursive: true, force: true });
    assert.equal(pick(dir, [], cases).status, 0);
    const picks = JSON.parse(readFileSync(join(dir, "pick", "picks.json"), "utf8"));
    const g = Object.fromEntries(JSON.parse(readFileSync(join(dir, "ev", "mvq-results.json"), "utf8")).cases.map((c) => [c.case_id, c]));
    writeFileSync(join(dir, "pick", "ratings.json"), JSON.stringify(picks.case_ids.map((id) =>
      ({ case_id: id, verdict: g[id].pass ? "PASS" : "FAIL", fail_reason: g[id].pass ? null : "other" }))));
    for (const target of [join(mz, "side-by-side.md"), join(dir, "loose", "side-by-side.md")]) {
      r = run(["grader/qa_agreement.py", "--mode", "verdict", "--human", join(dir, "pick", "ratings.json"),
        "--grader", join(dir, "ev", "mvq-results.json"), "--picks", join(dir, "pick", "picks.json"), "--side-by-side", target]);
      assert.equal(r.status, 2, r.stdout + r.stderr); assert.match(r.stderr, /side-by-side refused/);
      assert.ok(!existsSync(target));
    }
    r = run(["grader/qa_agreement.py", "--mode", "verdict", "--human", join(dir, "pick", "ratings.json"),
      "--grader", join(dir, "ev", "mvq-results.json"), "--picks", join(dir, "pick", "picks.json"),
      "--side-by-side", join(dir, "pick", "side-by-side.md")]);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const sm = JSON.parse(readFileSync(join(dir, "pick", "retention-manifest.json"), "utf8"));
    assert.ok(sm.files.some((f) => f.kind === "side_by_side" && /^\d{4}-\d{2}-\d{2}$/.test(f.deletion_date)));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("every output has a deletion date in a retention manifest; the shredded raw file is recorded", () => {
  const dir = tmp("mvq-safe-");
  try {
    assert.equal(baseline(dir).status, 0);
    const rm = JSON.parse(readFileSync(join(dir, "raw", "retention-manifest.json"), "utf8"));
    assert.equal(rm.retention_days, 30);
    assert.equal(statSync(join(dir, "raw", "retention-manifest.json")).mode & 0o777, 0o600);
    assert.equal(rm.files[0].kind, "raw_replies");
    assert.equal(pick(dir).status, 0);
    const m = JSON.parse(readFileSync(join(dir, "pick", "retention-manifest.json"), "utf8"));
    const kinds = Object.fromEntries(m.files.map((f) => [f.kind, f]));
    for (const k of ["agreement_picks", "rating_sheet", "agreement_ratings", "raw_replies"]) {
      assert.match(kinds[k].deletion_date, /^\d{4}-\d{2}-\d{2}$/, k);
      const days = (Date.parse(kinds[k].deletion_date) - Date.parse(kinds[k].created_at.slice(0, 10))) / 86400000;
      assert.equal(days, 30, k);
    }
    assert.equal(kinds.raw_replies.status, "shredded");
    const rm2 = JSON.parse(readFileSync(join(dir, "raw", "retention-manifest.json"), "utf8"));
    assert.equal(rm2.files[0].status, "shredded");
    assert.match(readFileSync(join(dir, "pick", "rating-sheet.md"), "utf8"), /deleted by \d{4}-\d{2}-\d{2}/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("eval HERMES_HOME is rebuilt from an allowlist: no state.db*, auth, .env, logs, cron, export or data; 0700; shredded", () => {
  const src = tmp("fake-arin-home-");
  try {
    const put = (rel, body = "PLANTED-SECRET") => { mkdirSync(dirname(join(src, rel)), { recursive: true }); writeFileSync(join(src, rel), body); };
    put("state.db"); put("state.db-wal"); put("state.db-shm"); put("auth.json"); put(".env"); put("google_token.json");
    put("MEMORY.md"); put("USER.md"); put("logs/gateway.log"); put("cron/jobs.json"); put("sessions/s1.json");
    put("memory/m.json"); put("audit/sms-outbound.jsonl"); put("pending/memory/x.json");
    put("eval-export/run1/names.txt"); put("eval-export/run1/raw-input/s.json"); put("eval-export/run1/mvq/replies.jsonl");
    put("config.yaml", "model:\n  provider: custom\n  default: test/model\nplatform_toolsets:\n  telnyx_sms: [skills]\n" +
      "mcp_servers:\n  gmail: {url: PLANTED-SECRET}\ncron:\n  allow_agent_scheduling: true\nmemory:\n  provider: PLANTED-SECRET\n");
    put("skills/sms/SKILL.md", "# sms skill\n"); put("skills/sms/scripts/run.py", "print(1)\n");
    put("skills/sms/data/cache.db"); put("skills/sms/state.db"); put("skills/sms/out.jsonl"); put("skills/sms/token.json");
    put("skills/sms/logs/x.log"); put("skills/sms/.env");
    chmodSync(src, 0o755);
    const res = spawnSync("python3", ["-c", `
import json, os, sys
from pathlib import Path
from live_session import make_eval_hermes_home, shred_tree
home = make_eval_hermes_home(Path(sys.argv[1]))
files = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
blob = "".join(p.read_text(errors="ignore") for p in home.rglob("*") if p.is_file())
print(json.dumps({"files": files, "mode": oct(home.stat().st_mode & 0o777),
                  "modes": sorted({oct(p.stat().st_mode & 0o777) for p in home.rglob("*")}),
                  "secret": "PLANTED-SECRET" in blob, "cfg": (home / "config.yaml").read_text()}))
shred_tree(home)
print(json.dumps({"gone": not home.exists()}))
`, src], { cwd: mz, encoding: "utf8", env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1" } });
    assert.equal(res.status, 0, res.stdout + res.stderr);
    const [a, b] = res.stdout.trim().split("\n").map((l) => JSON.parse(l));
    assert.deepEqual(a.files, ["MEMORY.md", "USER.md", "config.yaml", "skills", "skills/sms", "skills/sms/SKILL.md",
      "skills/sms/scripts", "skills/sms/scripts/run.py"]);
    assert.equal(a.mode, "0o700");
    assert.ok(a.modes.every((m) => ["0o700", "0o600"].includes(m)), a.modes);
    assert.equal(a.secret, false);
    assert.match(a.cfg, /provider: custom/); assert.doesNotMatch(a.cfg, /mcp_servers|cron|memory/);
    assert.equal(b.gone, true);
  } finally { rmSync(src, { recursive: true, force: true }); }
});
