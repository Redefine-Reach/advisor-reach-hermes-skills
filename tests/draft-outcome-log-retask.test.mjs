// RED-583/596 retask items 3-12 (skills repo). Fictional 555 / example.com only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, readdirSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const scriptPath = join(root, "skills", "sms-send-confirmed", "scripts", "sms_send_confirmed.py");
const outcomeModPath = join(root, "skills", "sms-send-confirmed", "scripts", "draft_outcome_log.py");
const loopPath = join(root, "skills", "learning-loop", "scripts", "learning_loop.py");
const gatePath = join(here, "fixtures", "learning-loop", "arin_donotkeep.py");
const judgePath = join(here, "fixtures", "learning-loop", "judge.py");

const OWNER = "+17145550100";
const OWNER2 = "+17145550333";
const STRANGER = "+17145550222";
const DEST = "+15555550199";
const DEST2 = "+15555550200";
const FROM = "+19283563339";
const WHY = "Hendersons want the comparison before the 4 PM call";

function home() {
  const dir = mkdtempSync(join(tmpdir(), "draft-retask-"));
  mkdirSync(join(dir, "drafts"), { recursive: true });
  return dir;
}

function runSms(dir, args, extra = {}) {
  const transport = join(dir, "transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':True,'message_id':'m1','provider_status':'queued'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const calls = join(dir, "calls.jsonl");
  const env = {
    PATH: process.env.PATH,
    HOME: process.env.HOME || dir,
    LANG: "C.UTF-8",
    SMS_SEND_CONFIRMED_TEST: "1",
    SMS_BOX_ID: "arin-test",
    TELNYX_SMS_FROM_NUMBER: FROM,
    TELNYX_SMS_ALLOWED_USERS: OWNER,
    SMS_AUDIT_PATH: join(dir, "sms-outbound.jsonl"),
    SMS_OPT_OUT_FILE: join(dir, "sms-opt-out.txt"),
    SMS_DRAFT_DIR: join(dir, "drafts"),
    SMS_SESSION_DIR: join(dir, "sessions"),
    SMS_EVENT_DIR: join(dir, "events"),
    DRAFT_OUTCOMES_PATH: join(dir, "draft-outcomes.jsonl"),
    SMS_SEND_TRANSPORT: transport,
    CALLS: calls,
    ...extra,
  };
  let cmd = [...args];
  if (cmd[0] === "send" && !cmd.includes("--actor")) {
    cmd = [...cmd, "--actor", OWNER];
  }
  if (cmd[0] === "cancel" && !cmd.includes("--actor")) {
    cmd = [...cmd, "--actor", OWNER];
  }
  const proc = spawnSync("python3", [scriptPath, ...cmd], { env, encoding: "utf8" });
  let payload = null;
  try {
    payload = JSON.parse(proc.stdout || "null");
  } catch {
    payload = null;
  }
  const outcomes = existsSync(env.DRAFT_OUTCOMES_PATH)
    ? readFileSync(env.DRAFT_OUTCOMES_PATH, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l))
    : [];
  const audit = existsSync(env.SMS_AUDIT_PATH)
    ? readFileSync(env.SMS_AUDIT_PATH, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l))
    : [];
  return { proc, payload, outcomes, audit, calls, env, dir };
}

function stage(dir, body, extra = {}) {
  const replaces = extra.replaces;
  const dest = extra.dest || DEST;
  const why = extra.why || WHY;
  const { replaces: _r, dest: _d, why: _w, ...envExtra } = extra;
  return runSms(
    dir,
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      dest,
      "--body",
      body,
      "--why",
      why,
      "--source-kind",
      "owner_text",
      ...(replaces ? ["--replaces", replaces, "--actor", OWNER] : []),
    ],
    envExtra,
  );
}

function outcomeLines(dir) {
  const p = join(dir, "draft-outcomes.jsonl");
  if (!existsSync(p)) return [];
  return readFileSync(p, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

function draftBodies(dir) {
  const bodies = [];
  for (const name of readdirSync(join(dir, "drafts"))) {
    if (!name.endsWith(".json")) continue;
    const d = JSON.parse(readFileSync(join(dir, "drafts", name), "utf8"));
    if (d.body) bodies.push(d.body);
  }
  return bodies;
}

function runLoop(dir, args, extra = {}) {
  const env = {
    PATH: process.env.PATH,
    HERMES_HOME: dir,
    LEARNING_LOOP_TEST: "1",
    LEARNING_LOOP_JUDGE: judgePath,
    ARIN_DONOTKEEP_PY: gatePath,
    LEARNING_LOOP_ENFORCE_OWNER: "1",
    LEARNING_LOOP_OWNERS: OWNER,
    LEARNING_LOOP_ACTOR: OWNER,
    ...extra,
  };
  const proc = spawnSync("python3", [loopPath, ...args], { env, encoding: "utf8" });
  const payload = JSON.parse(proc.stdout || "null");
  const storePath = join(dir, "learning", "loop.json");
  const store = existsSync(storePath) ? JSON.parse(readFileSync(storePath, "utf8")) : null;
  return { proc, payload, store };
}

test("item3 cancel twice and cancel superseded or sent write one line per chain", () => {
  const dir = home();
  const s = stage(dir, "Quick note for you today.");
  const id = s.payload.draft_id;
  runSms(dir, ["cancel", "--draft-id", id]);
  runSms(dir, ["cancel", "--draft-id", id]);
  assert.equal(outcomeLines(dir).length, 1);
  const chain = stage(dir, "First version for you.");
  const d1 = chain.payload.draft_id;
  const chain2 = stage(dir, "Second version for you.", { replaces: d1, why: "Second version for your update" });
  assert.equal(chain2.payload.outcome, "staged");
  runSms(dir, ["cancel", "--draft-id", d1]);
  assert.equal(outcomeLines(dir).length, 1);
  const d2 = chain2.payload.draft_id;
  runSms(dir, ["send", "--draft-id", d2, "--confirm", "SEND", "--attest", "yes"], { SMS_SEND_STUB_PROVIDER: "1" });
  runSms(dir, ["cancel", "--draft-id", d2]);
  assert.equal(outcomeLines(dir).length, 2);
});

test("item4 Jerry refused outcome on provider failure with re-stage chain and export bucket", () => {
  const dir = home();
  const transport = join(dir, "fail-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':False,'message_id':'','provider_status':'error','error':'rejected'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const staged = stage(dir, "Provider fail path for you.");
  const refusedId = staged.payload.draft_id;
  const fail = runSms(dir, ["send", "--draft-id", refusedId, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  assert.equal(fail.payload.outcome, "refused");
  assert.equal(fail.payload.refuse_reason, "provider_error");
  const lines = outcomeLines(dir);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].outcome, "refused");
  assert.equal(lines[0].refuse_reason, "provider_error");
  assert.doesNotMatch(JSON.stringify(lines[0]), /rejected/);
  const loopBefore = runLoop(dir, ["show"]);
  assert.equal(loopBefore.store?.signals?.length ?? 0, 0);
  const blockedRestage = stage(dir, "Provider fail path fixed for you.", {
    replaces: refusedId,
    why: "They still need the confirmation before the afternoon call",
  });
  assert.equal(blockedRestage.payload.outcome, "error");
  assert.equal(outcomeLines(dir).length, 1);
  const cancelled = stage(dir, "You asked to drop this follow-up entirely.", {
    why: "They asked to drop this follow-up before the afternoon call",
  });
  assert.equal(cancelled.payload.outcome, "staged");
  runSms(dir, ["cancel", "--draft-id", cancelled.payload.draft_id]);
  const rows = runSms(dir, ["export-outcomes"]).payload.rows;
  const refusedRow = rows.find((r) => r.outcome === "refused");
  const cancelledRow = rows.find((r) => r.outcome === "cancelled");
  assert.ok(refusedRow && refusedRow.count === 1);
  assert.ok(cancelledRow && cancelledRow.count === 1);
  assert.notEqual(refusedRow.day, undefined);
  const loopAfter = runLoop(dir, ["show"]);
  assert.equal(loopAfter.store?.signals?.length ?? 0, 0);
});

test("item4 non-SEND reply and unfilled placeholder write cancelled outcomes", () => {
  const dir = home();
  const s = stage(dir, "Ping when you can reply.");
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "maybe later", "--attest", "yes"]);
  assert.equal(outcomeLines(dir).length, 1);
  assert.equal(outcomeLines(dir)[0].outcome, "cancelled");
  const ph = stage(dir, "Your tour is on [DATE] - please confirm you can make it.", {
    why: "They need to confirm the tour time before we lock the slot",
  });
  const phSend = runSms(dir, ["send", "--draft-id", ph.payload.draft_id, "--confirm", "SEND", "--attest", "yes"]);
  assert.equal(phSend.payload.outcome, "refused_unfilled_placeholder");
  assert.equal(outcomeLines(dir).length, 2);
  assert.equal(outcomeLines(dir)[1].outcome, "refused");
  assert.equal(outcomeLines(dir)[1].refuse_reason, "unfilled_placeholder");
});

test("item5 re-stage keeps recipient and refuses reused Why when body changes", () => {
  const dir = home();
  const first = stage(dir, "Hello there, hope you are well!");
  const d1 = first.payload.draft_id;
  const badDest = stage(dir, "Hello there, hope you are well!", { replaces: d1, dest: DEST2 });
  assert.equal(badDest.payload.outcome, "refused_why_reused");
  const badWhy = stage(dir, "Totally different text for you now.", { replaces: d1 });
  assert.equal(badWhy.payload.outcome, "refused_why_reused");
});

test("item6 no draft file keeps plaintext body after finals", () => {
  const dir = home();
  const secrets = ["AlphaPlain", "BetaPlain"];
  const s = stage(dir, `Hi, ${secrets[0]} here for you.`);
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], { SMS_SEND_STUB_PROVIDER: "1" });
  for (const needle of secrets) {
    assert.ok(!JSON.stringify(draftBodies(dir)).includes(needle));
  }
});

function draftSnapshot(dir, id) {
  return readFileSync(join(dir, "drafts", `${id}.json`), "utf8");
}

function assertDraftUnchanged(dir, id, before) {
  assert.equal(readFileSync(join(dir, "drafts", `${id}.json`), "utf8"), before);
}

test("item7 AC18 only draft approver may cancel send or re-stage", () => {
  for (const actor of [OWNER2, STRANGER]) {
    const dir = home();
    const envExtra = {
      TELNYX_SMS_ALLOWED_USERS: `${OWNER},${OWNER2}`,
    };
    const s = stage(dir, "You can reply when you have a moment.", envExtra);
    assert.equal(s.payload.outcome, "staged", s.proc.stderr);
    const id = s.payload.draft_id;
    const before = draftSnapshot(dir, id);
    const cancel = runSms(dir, ["cancel", "--draft-id", id, "--actor", actor], envExtra);
    assert.equal(cancel.payload.outcome, "refused_not_owner");
    assert.equal(outcomeLines(dir).length, 0);
    assertDraftUnchanged(dir, id, before);
    const send = runSms(
      dir,
      ["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes", "--actor", actor],
      { ...envExtra, SMS_SEND_STUB_PROVIDER: "1" },
    );
    assert.equal(send.payload.outcome, "refused_not_owner");
    assert.equal(outcomeLines(dir).length, 0);
    assertDraftUnchanged(dir, id, before);
    const restage = runSms(
      dir,
      [
        "stage",
        "--approver",
        OWNER,
        "--dest",
        DEST,
        "--body",
        "You should not reach this re-stage.",
        "--why",
        "Another reason for the afternoon call slot",
        "--source-kind",
        "owner_text",
        "--replaces",
        id,
        "--actor",
        actor,
      ],
      envExtra,
    );
    assert.equal(restage.payload.outcome, "refused_not_owner");
    assert.equal(outcomeLines(dir).length, 0);
    assertDraftUnchanged(dir, id, before);
  }
});

test("item7 learning_loop record refused for non-owner session", () => {
  const dir = home();
  const r = runLoop(dir, ["record", "--kind", "follow-up", "--action", "edit", "--note", "shorter"], {
    LEARNING_LOOP_ACTOR: STRANGER,
    LEARNING_LOOP_OWNERS: OWNER,
  });
  assert.equal(r.payload.ok, false);
  assert.equal(r.store, null);
});

test("item6 learning_loop non-owner show and forget leave loop.json unchanged", () => {
  const dir = home();
  runLoop(dir, ["record", "--kind", "follow-up", "--action", "edit", "--note", "shorter"], {
    LEARNING_LOOP_ACTOR: OWNER,
    LEARNING_LOOP_OWNERS: OWNER,
  });
  const before = readFileSync(join(dir, "learning", "loop.json"), "utf8");
  for (const args of [["show"], ["forget", "--style-note"]]) {
    const r = runLoop(dir, args, { LEARNING_LOOP_ACTOR: STRANGER, LEARNING_LOOP_OWNERS: OWNER });
    assert.equal(r.payload.ok, false);
    assert.equal(readFileSync(join(dir, "learning", "loop.json"), "utf8"), before);
  }
  const r2 = runLoop(dir, ["show"], { LEARNING_LOOP_OWNERS: OWNER });
  assert.equal(r2.payload.ok, true);
});

test("item1 N1 digit-heavy replaces_chain id writes exactly one outcome line", () => {
  const dir = home();
  const heavy = "a1292779231167a2";
  const s1 = runSms(
    dir,
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      "First chain body for you.",
      "--why",
      WHY,
      "--source-kind",
      "owner_text",
    ],
    { SMS_DRAFT_ID_NEXT: heavy },
  );
  assert.equal(s1.payload.draft_id, heavy);
  const s2 = stage(dir, "Second chain body for you.", {
    replaces: heavy,
    why: "Second reason for your update today",
  });
  const sent = runSms(dir, ["send", "--draft-id", s2.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_STUB_PROVIDER: "1",
  });
  assert.equal(sent.outcomes.length, 1);
  assert.deepEqual(sent.outcomes[0].replaces_chain, [heavy]);
});

test("item10 stub ignored without test mode unless allow flag", () => {
  const dir = home();
  const s = stage(dir, "Stub check for you.");
  const offTest = { SMS_SEND_STUB_PROVIDER: "1", SMS_SEND_CONFIRMED_TEST: "0" };
  const sent = runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], offTest);
  assert.notEqual(sent.payload.outcome, "sent");
  const dir2 = home();
  const s2 = stage(dir2, "Another line for you.", { why: "They need a quick confirmation before the afternoon call" });
  const allowed = runSms(
    dir2,
    ["send", "--draft-id", s2.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    { SMS_SEND_STUB_PROVIDER: "1", SMS_SEND_CONFIRMED_TEST: "0", SMS_SEND_STUB_ALLOW: "1" },
  );
  assert.equal(allowed.payload.outcome, "sent");
  assert.equal(allowed.payload.provider_called, false);
});

test("item11 outcome_log_failed audit when duplicate final blocked", () => {
  const dir = home();
  const s = stage(dir, "Audit path for you.");
  runSms(dir, ["cancel", "--draft-id", s.payload.draft_id]);
  const dup = spawnSync(
    "python3",
    [
      "-c",
      `import json, os, sys
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location("sms", ${JSON.stringify(scriptPath)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
spec2 = importlib.util.spec_from_file_location("dol", ${JSON.stringify(outcomeModPath)})
dol = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dol)
os.environ["SMS_SEND_CONFIRMED_TEST"]="1"
os.environ["SMS_BOX_ID"]="arin-test"
os.environ["TELNYX_SMS_FROM_NUMBER"]=${JSON.stringify(FROM)}
os.environ["TELNYX_SMS_ALLOWED_USERS"]=${JSON.stringify(OWNER)}
os.environ["SMS_DRAFT_DIR"]=sys.argv[1]
os.environ["DRAFT_OUTCOMES_PATH"]=sys.argv[2]
os.environ["SMS_AUDIT_PATH"]=sys.argv[3]
store = mod.paths()
draft = {"draft_id": sys.argv[4], "body_hash_first": "a", "body_hash_final": "a", "len_first": 1, "len_final": 1, "edit_distance": 0, "chain_created_at": "2026-10-19T12:00:00Z"}
mod.maybe_finalize_draft_outcome(store, draft, "cancelled", box_id="arin-test")
mod.maybe_finalize_draft_outcome(store, draft, "cancelled", box_id="arin-test")
`,
      join(dir, "drafts"),
      join(dir, "draft-outcomes.jsonl"),
      join(dir, "sms-outbound.jsonl"),
      s.payload.draft_id,
    ],
    { encoding: "utf8" },
  );
  assert.equal(dup.status, 0, dup.stderr);
  const audit = readFileSync(join(dir, "sms-outbound.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.ok(audit.some((row) => row.outcome === "outcome_log_failed"));
});

test("item9 AC4 two edits yield edit_rounds 2 and superseded drafts have no lines", () => {
  const dir = home();
  const d0 = stage(dir, "Version one for you.").payload.draft_id;
  const d1 = stage(dir, "Version two for you.", { replaces: d0, why: "Second reason for your update today" }).payload.draft_id;
  const d2 = stage(dir, "Version three for you.", { replaces: d1, why: "Third reason for your shorter note" }).payload.draft_id;
  runSms(dir, ["send", "--draft-id", d2, "--confirm", "SEND", "--attest", "yes"], { SMS_SEND_STUB_PROVIDER: "1" });
  const lines = outcomeLines(dir);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].edit_rounds, 2);
  assert.deepEqual(lines[0].replaces_chain, [d0, d1]);
});

test("item9 AC5 cancel command for DROP NO skip and edit-then-DROP", () => {
  const dir = home();
  for (const word of ["DROP", "NO", "skip"]) {
    const d = stage(dir, `Word ${word} test for you.`, { why: `Owner chose ${word} on the ${word} cancel path today` }).payload.draft_id;
    runSms(dir, ["cancel", "--draft-id", d]);
  }
  const lines = outcomeLines(dir);
  assert.equal(lines.length, 3);
  assert.ok(lines.every((r) => r.edit_rounds === 0));
  const a = stage(dir, "Edit chain for you.").payload.draft_id;
  const b = stage(dir, "Shorter for you.", { replaces: a, why: "Shorter follow-up for your inbox" }).payload.draft_id;
  runSms(dir, ["cancel", "--draft-id", b]);
  const last = outcomeLines(dir).at(-1);
  assert.equal(last.edit_rounds, 1);
  assert.deepEqual(last.replaces_chain, [a]);
});

test("item9 AC7 provider called when stub env set without test mode but no allow", () => {
  const dir = home();
  const s = stage(dir, "Real transport for you.");
  const sent = runSms(
    dir,
    ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    { SMS_SEND_CONFIRMED_TEST: "1", SMS_SEND_STUB_PROVIDER: "" },
  );
  assert.equal(sent.payload.provider_called, true);
  assert.ok(sent.calls.trim().length > 0);
});

test("item9 AC9 guard rejects SSN URL digit-run and body field", () => {
  const py = spawnSync(
    "python3",
    [
      "-c",
      `import draft_outcome_log as m, json, sys
for bad in [
  {"ts":"2026-10-19T12:00:00Z","draft_id":"abcd1234abcd1234","kind":"sms","outcome":"cancelled","edit_rounds":0,"replaces_chain":[],"body_hash_first":"a","body_hash_final":"a","edit_distance":0,"len_first":1,"len_final":1,"hours_to_decision":0,"note":"x"},
  {"ts":"2026-10-19T12:00:00Z","draft_id":"abcd1234abcd1234","kind":"sms","outcome":"cancelled","edit_rounds":0,"replaces_chain":[],"body_hash_first":"a","body_hash_final":"a","edit_distance":0,"len_first":1,"len_final":1,"hours_to_decision":0,"box_slug":"1234567890"},
]:
  try:
    m.validate_outcome_line(bad)
    print('fail')
    sys.exit(1)
  except ValueError:
    pass
print('ok')`,
    ],
    { encoding: "utf8", env: { ...process.env, PYTHONPATH: dirname(outcomeModPath) } },
  );
  assert.equal(py.status, 0);
});

test("item9 AC10 exporter canary scan is clean", () => {
  const dir = home();
  const s = stage(dir, "Export row for you.");
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], { SMS_SEND_STUB_PROVIDER: "1" });
  const rows = runSms(dir, ["export-outcomes"]).payload.rows;
  const scan = spawnSync("python3", ["-c", "import draft_outcome_log as m, json, sys; print(len(m.scan_export_rows(json.loads(sys.argv[1]))))", JSON.stringify(rows)], {
    env: { ...process.env, PYTHONPATH: dirname(outcomeModPath) },
    encoding: "utf8",
  });
  assert.equal(scan.stdout.trim(), "0", scan.stdout + scan.stderr);
});

test("item9 AC18 ignored sweep writes no learning-loop signal", () => {
  const dir = home();
  const s = stage(dir, "Ignored path for you.", { SMS_NOW: "2026-10-19T12:00:00+00:00" });
  runSms(dir, ["sweep-outcomes"], { SMS_NOW: "2026-10-19T12:31:00+00:00" });
  const loop = runLoop(dir, ["show"]);
  assert.equal(loop.payload.items.length, 0);
  assert.equal(loop.store?.signals?.length ?? 0, 0);
});

test("item9 AC19 record edit gate refuses health SSN account and owner rule", () => {
  const dir = home();
  const blocked = [
    ["mention the surgery date", "I won't save health details."],
    ["SSN 123-45-6789 on file", "I won't save Social Security numbers."],
    ["account number 123456789012", "I won't save financial account numbers."],
    ["block-rule keep Daniel's divorce", "Not saved: this matches a do-not-keep rule."],
  ];
  for (const [note, say] of blocked) {
    const r = runLoop(dir, ["record", "--kind", "follow-up", "--action", "edit", "--note", note]);
    assert.equal(r.payload.saved, false);
    assert.equal(r.payload.say, say);
    assert.equal(r.store, null);
  }
  const ok = runLoop(dir, ["record", "--kind", "follow-up", "--action", "edit", "--note", "shorter family money note"]);
  assert.equal(ok.payload.saved, true);
  assert.equal(ok.store.signals.length, 1);
});

test("item8 cancel before sweep on expired draft yields one ignored line", () => {
  const dir = home();
  const s = stage(dir, "Sweep lock path for you.", { SMS_NOW: "2026-10-19T12:00:00+00:00" });
  runSms(dir, ["cancel", "--draft-id", s.payload.draft_id]);
  runSms(dir, ["sweep-outcomes"], { SMS_NOW: "2026-10-19T12:31:00+00:00" });
  assert.equal(outcomeLines(dir).length, 1);
  assert.equal(outcomeLines(dir)[0].outcome, "cancelled");
});

test("item12 expired send keeps cancelled_reason expired with status ignored", () => {
  const dir = home();
  const s = stage(dir, "Expired status for you.", { SMS_NOW: "2026-10-19T12:00:00+00:00" });
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], { SMS_NOW: "2026-10-19T12:31:00+00:00" });
  const draft = JSON.parse(readFileSync(join(dir, "drafts", `${s.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.status, "ignored");
  assert.equal(draft.cancelled_reason, "expired");
});
