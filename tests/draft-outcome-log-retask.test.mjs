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
const OWNER_TG = "424242";
const UNMAPPED_TG = "888888";
const OWNER_IDENTITIES = `${OWNER}|tg:${OWNER_TG}`;
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
    SMS_TURN_OWNER_E164: OWNER,
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

test("item7 AC18 cross-channel actor map and three refusal classes", () => {
  const envExtra = {
    TELNYX_SMS_ALLOWED_USERS: `${OWNER},${OWNER2}`,
    TELEGRAM_ALLOWED_USERS: `${OWNER_TG},${UNMAPPED_TG}`,
    ARIN_OWNER_IDENTITIES: OWNER_IDENTITIES,
  };
  const dir = home();
  const s = stage(dir, "Hi Dana, you can reply when you have a moment.", envExtra);
  const id = s.payload.draft_id;
  const before = draftSnapshot(dir, id);
  const tgSend = runSms(
    dir,
    ["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes", "--actor", OWNER_TG],
    { ...envExtra, SMS_SEND_STUB_PROVIDER: "1", TG_TURN_OWNER_ID: OWNER_TG },
  );
  assert.equal(tgSend.payload.outcome, "sent");
  const dir2 = home();
  const s2 = stage(dir2, "Hi Dana, SMS text path should still send.", envExtra);
  const id2 = s2.payload.draft_id;
  const smsSend = runSms(
    dir2,
    ["send", "--draft-id", id2, "--confirm", "SEND", "--attest", "yes", "--actor", OWNER],
    { ...envExtra, SMS_SEND_STUB_PROVIDER: "1" },
  );
  assert.equal(smsSend.payload.outcome, "sent");
  const dirTgCancel = home();
  const stagedTg = stage(dirTgCancel, "Hi Dana, cancel path via telegram.", envExtra);
  const tgCancel = runSms(
    dirTgCancel,
    ["cancel", "--draft-id", stagedTg.payload.draft_id, "--actor", OWNER_TG],
    envExtra,
  );
  assert.equal(tgCancel.payload.outcome, "cancelled");
  const dir3 = home();
  const s3 = stage(dir3, "Hi Dana, refusal path for you.", envExtra);
  const id3 = s3.payload.draft_id;
  const before3 = draftSnapshot(dir3, id3);
  for (const actor of [OWNER2, UNMAPPED_TG, STRANGER]) {
    const cancel = runSms(dir3, ["cancel", "--draft-id", id3, "--actor", actor], envExtra);
    assert.equal(cancel.payload.outcome, "refused_not_owner");
    assert.equal(outcomeLines(dir3).length, 0);
    assertDraftUnchanged(dir3, id3, before3);
    const send = runSms(
      dir3,
      ["send", "--draft-id", id3, "--confirm", "SEND", "--attest", "yes", "--actor", actor],
      { ...envExtra, SMS_SEND_STUB_PROVIDER: "1" },
    );
    assert.equal(send.payload.outcome, "refused_not_owner");
    assert.equal(outcomeLines(dir3).length, 0);
    assertDraftUnchanged(dir3, id3, before3);
    const restage = runSms(
      dir3,
      [
        "stage",
        "--approver",
        OWNER,
        "--dest",
        DEST,
        "--body",
        "Hi Dana, should not re-stage.",
        "--why",
        "Another reason for the afternoon call slot",
        "--source-kind",
        "owner_text",
        "--replaces",
        id3,
        "--actor",
        actor,
      ],
      envExtra,
    );
    assert.equal(restage.payload.outcome, "refused_not_owner");
    assert.equal(outcomeLines(dir3).length, 0);
    assertDraftUnchanged(dir3, id3, before3);
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

test("closing opt-out at SEND writes refused opted_out", () => {
  const dir = home();
  const s = stage(dir, "Hi Dana, quick note before the call.");
  writeFileSync(join(dir, "sms-opt-out.txt"), `${DEST}\n`);
  const sent = runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"]);
  assert.equal(sent.payload.outcome, "refused_stop");
  const lines = outcomeLines(dir);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].outcome, "refused");
  assert.equal(lines[0].refuse_reason, "opted_out");
});

test("closing over-length at SEND writes refused over_length", () => {
  const dir = home();
  const body = `Hi Dana, ${"A".repeat(60)}`;
  const s = stage(dir, body, { SMS_MAX_BODY_CHARS: "200" });
  const sent = runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_MAX_BODY_CHARS: "10",
  });
  assert.equal(sent.payload.outcome, "error");
  assert.equal(sent.payload.refuse_reason, "over_length");
  const lines = outcomeLines(dir);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].refuse_reason, "over_length");
});

test("closing pending_blocks refuses a second open draft", () => {
  const dir = home();
  stage(dir, "Hi Dana, first pending draft for you.");
  const second = stage(dir, "Hi Dana, second should be refused.");
  assert.equal(second.payload.outcome, "refused_multi");
  assert.equal(outcomeLines(dir).length, 0);
});

test("closing provider_no_id cannot be re-sent or re-staged", () => {
  const dir = home();
  const transport = join(dir, "no-id-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':True,'message_id':'','provider_status':'accepted'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const s = stage(dir, "No id path for you.");
  const id = s.payload.draft_id;
  const fail = runSms(dir, ["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  assert.equal(fail.payload.refuse_reason, "provider_no_id");
  const resend = runSms(dir, ["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes"]);
  assert.notEqual(resend.payload.outcome, "sent");
  const restage = stage(dir, "No id path fixed for you.", { replaces: id, why: "Still need them to confirm before the call" });
  assert.equal(restage.payload.outcome, "error");
});

test("closing missing --actor fails closed on send", () => {
  const dir = home();
  const s = stage(dir, "Actor required on send.");
  const base = runSms(dir, ["export-outcomes"]).env;
  const proc = spawnSync("python3", [scriptPath, "send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    env: base,
    encoding: "utf8",
  });
  assert.notEqual(proc.status, 0);
});

test("closing refused placeholder re-stage then SEND links chain", () => {
  const dir = home();
  const ph = stage(dir, "Your tour is on [DATE] - please confirm.", {
    why: "They need to confirm the tour time before we lock the slot",
  });
  const refused = runSms(dir, ["send", "--draft-id", ph.payload.draft_id, "--confirm", "SEND", "--attest", "yes"]);
  assert.equal(refused.payload.outcome, "refused_unfilled_placeholder");
  const fixed = stage(dir, "Your tour is on Tuesday - please confirm.", {
    replaces: ph.payload.draft_id,
    why: "They confirmed Tuesday works before we lock the slot",
  });
  const sent = runSms(dir, ["send", "--draft-id", fixed.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_STUB_PROVIDER: "1",
  });
  assert.equal(sent.payload.outcome, "sent");
  const line = outcomeLines(dir).at(-1);
  assert.deepEqual(line.replaces_chain, [ph.payload.draft_id]);
});

test("closing edit_distance is first body to sent body across rounds", () => {
  const dir = home();
  const b0 = "Hi Dana, the key is under the mat.";
  const b1 = "Hi Dana, the key is in the lockbox.";
  const b2 = "Hi Dana, use code 4491 on the lockbox.";
  const d0 = stage(dir, b0).payload.draft_id;
  const d1 = stage(dir, b1, { replaces: d0, why: "Second reason for your shorter update today" }).payload.draft_id;
  const d2 = stage(dir, b2, { replaces: d1, why: "Third reason for your final wording today" }).payload.draft_id;
  runSms(dir, ["send", "--draft-id", d2, "--confirm", "SEND", "--attest", "yes"], { SMS_SEND_STUB_PROVIDER: "1" });
  const dist = spawnSync(
    "python3",
    ["-c", "import draft_outcome_log as m; import sys; print(m.edit_distance(sys.argv[1], sys.argv[2]))", b0, b2],
    { encoding: "utf8", env: { ...process.env, PYTHONPATH: dirname(outcomeModPath) } },
  );
  const expected = Number(dist.stdout.trim());
  const line = outcomeLines(dir)[0];
  assert.equal(line.edit_distance, expected);
  const roundSum = spawnSync(
    "python3",
    [
      "-c",
      `import draft_outcome_log as m, sys
a,b,c = sys.argv[1], sys.argv[2], sys.argv[3]
print(m.edit_distance(a,b)+m.edit_distance(b,c))`,
      b0,
      b1,
      b2,
    ],
    { encoding: "utf8", env: { ...process.env, PYTHONPATH: dirname(outcomeModPath) } },
  );
  const summed = Number(roundSum.stdout.trim());
  assert.ok(summed > expected, `expected first-to-final ${expected} < summed rounds ${summed}`);
});

test("closing refused_recent_provider_failure blocks duplicate fresh stage", () => {
  const dir = home();
  const body = "Hi Dana, duplicate guard body for you.";
  const transport = join(dir, "ambig-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':False,'message_id':'','provider_status':'error','error':'timeout'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const s = stage(dir, body);
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  const dup = stage(dir, body);
  assert.equal(dup.payload.outcome, "refused_recent_provider_failure");
  assert.equal(
    dup.payload.reason,
    "Your last text to this person may still go through, so I didn't queue a duplicate",
  );
  assert.equal(outcomeLines(dir).length, 1);
});

test("closing definitive provider rejected exempts duplicate stage", () => {
  const dir = home();
  const body = "Hi Dana, retry after definitive reject.";
  const transport = join(dir, "rejected-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':False,'message_id':'','provider_status':'rejected','error':'blocked'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const s = stage(dir, body);
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  const again = stage(dir, body, { why: "They still need the same note before the afternoon call" });
  assert.equal(again.payload.outcome, "staged");
});

test("closing provider not_sent exempts duplicate stage", () => {
  const dir = home();
  const body = "Hi Dana, retry after not sent locally.";
  const transport = join(dir, "not-sent-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':False,'message_id':'','provider_status':'not_sent','error':'local'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const s = stage(dir, body);
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  const again = stage(dir, body, { why: "They still need the same note before the afternoon call" });
  assert.equal(again.payload.outcome, "staged");
});

test("closing double-send guard blocks re-stage back to original body", () => {
  const dir = home();
  const bodyX = "Hi Dana, bypass guard original body.";
  const bodyY = "Hi Dana, bypass guard alternate body.";
  const transport = join(dir, "ambig-bypass-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':False,'message_id':'','provider_status':'error','error':'timeout'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const s = stage(dir, bodyX);
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  const mid = stage(dir, bodyY, { why: "They asked for a shorter alternate wording before the call" });
  assert.equal(mid.payload.outcome, "staged");
  const back = stage(dir, bodyX, {
    replaces: mid.payload.draft_id,
    why: "They want the original wording back before the call",
  });
  assert.equal(back.payload.outcome, "refused_recent_provider_failure");
  assert.equal(outcomeLines(dir).length, 1);
});

test("closing double-send guard recheck refuses send before provider", () => {
  const dir = home();
  const body = "Hi Dana, send-time guard recheck body.";
  const transport = join(dir, "ambig-send-transport.py");
  writeFileSync(
    transport,
    "#!/usr/bin/env python3\nimport json,sys\njson.dump({'success':False,'message_id':'','provider_status':'error','error':'timeout'},sys.stdout)\n",
  );
  chmodSync(transport, 0o755);
  const s = stage(dir, body);
  const id = s.payload.draft_id;
  runSms(dir, ["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  const path = join(dir, "drafts", `${id}.json`);
  const revived = JSON.parse(readFileSync(path, "utf8"));
  revived.status = "pending";
  revived.body = body;
  writeFileSync(path, `${JSON.stringify(revived, null, 2)}\n`);
  const retry = runSms(dir, ["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_TRANSPORT: transport,
    SMS_SEND_STUB_PROVIDER: "",
  });
  assert.equal(retry.payload.outcome, "refused_recent_provider_failure");
  const callLog = existsSync(retry.calls) ? readFileSync(retry.calls, "utf8").trim() : "";
  assert.equal(callLog.length, 0);
  const after = JSON.parse(readFileSync(path, "utf8"));
  assert.equal(after.status, "pending");
});

test("closing AC8 edit_distance survives send refused then re-stage and send", () => {
  const dir = home();
  const a = "Hi Dana, first draft [PRICE] here.";
  const b = "Hi Dana, second draft beta text here.";
  const s = stage(dir, a);
  const refused = runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"]);
  assert.equal(refused.payload.outcome, "refused_unfilled_placeholder");
  const dist = spawnSync(
    "python3",
    ["-c", "import draft_outcome_log as m, sys; print(m.edit_distance(sys.argv[1], sys.argv[2]))", a, b],
    { encoding: "utf8", env: { ...process.env, PYTHONPATH: dirname(outcomeModPath) } },
  );
  const expected = Number(dist.stdout.trim());
  const s2 = stage(dir, b, {
    replaces: s.payload.draft_id,
    why: "They supplied the missing detail before we lock the slot",
  });
  assert.equal(s2.payload.outcome, "staged");
  runSms(dir, ["send", "--draft-id", s2.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
    SMS_SEND_STUB_PROVIDER: "1",
  });
  const line = outcomeLines(dir).find((row) => row.outcome === "sent_as_is" || row.outcome === "sent_after_edit" || row.outcome === "sent");
  assert.ok(line);
  assert.equal(line.edit_distance, expected);
});

test("closing RED-700 send and re-stage refuse wrong box SMS turn owner", () => {
  const envExtra = { TELNYX_SMS_ALLOWED_USERS: `${OWNER},${OWNER2}`, SMS_TURN_OWNER_E164: OWNER };
  const dirSend = home();
  const s = stage(dirSend, "Hi Dana, turn owner binding for send.", envExtra);
  const wrongSend = runSms(
    dirSend,
    ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes", "--actor", OWNER2],
    envExtra,
  );
  assert.equal(wrongSend.payload.outcome, "refused_not_owner");
  const dirRestage = home();
  const ph = stage(dirRestage, "Hi Dana, meet at [TIME] today.", {
    why: "They need the time before we lock the slot",
  });
  runSms(dirRestage, ["send", "--draft-id", ph.payload.draft_id, "--confirm", "SEND", "--attest", "yes"]);
  const badRestage = runSms(
    dirRestage,
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      "Hi Dana, meet at noon today.",
      "--why",
      "Noon works before we lock the slot",
      "--source-kind",
      "owner_text",
      "--replaces",
      ph.payload.draft_id,
      "--actor",
      OWNER2,
    ],
    envExtra,
  );
  assert.equal(badRestage.payload.outcome, "refused_not_owner");
});

test("closing error-only provider payloads arm the guard (503 timeout partial)", () => {
  const body = "Hi Dana, error-only guard arms on this body.";
  for (const err of [
    "503 Service Unavailable",
    "upstream timeout waiting for Telnyx",
    "partial multipart send: segment 2 failed",
  ]) {
    const dir = home();
    const transport = join(dir, "err-only-transport.py");
    writeFileSync(
      transport,
      `#!/usr/bin/env python3\nimport json,sys\njson.dump({'error':${JSON.stringify(err)}},sys.stdout)\n`,
    );
    chmodSync(transport, 0o755);
    const norm = spawnSync(
      "python3",
      [
        "-c",
        `import importlib.util, sys
spec = importlib.util.spec_from_file_location("sms", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
r = mod.normalize_sender_result({"error": sys.argv[2]})
print(r["provider_status"])`,
        scriptPath,
        err,
      ],
      { encoding: "utf8" },
    );
    assert.equal(norm.stdout.trim(), "error", err);
    const s = stage(dir, body);
    runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], {
      SMS_SEND_TRANSPORT: transport,
      SMS_SEND_STUB_PROVIDER: "",
    });
    const dup = stage(dir, body, { why: "They still need the same note before the afternoon call" });
    assert.equal(dup.payload.outcome, "refused_recent_provider_failure", err);
  }
});

test("closing refused draft allows only one re-stage", () => {
  const dir = home();
  const ph = stage(dir, "Hi Dana, meet at [TIME] today.", { why: "They need the time before we lock the slot" });
  runSms(dir, ["send", "--draft-id", ph.payload.draft_id, "--confirm", "SEND", "--attest", "yes"]);
  const once = stage(dir, "Hi Dana, meet at noon today.", {
    replaces: ph.payload.draft_id,
    why: "Noon works before we lock the slot",
  });
  assert.equal(once.payload.outcome, "staged");
  const twice = stage(dir, "Hi Dana, meet at one today.", {
    replaces: ph.payload.draft_id,
    why: "One pm works before we lock the slot",
  });
  assert.equal(twice.payload.outcome, "error");
});

test("item12 expired send keeps cancelled_reason expired with status ignored", () => {
  const dir = home();
  const s = stage(dir, "Expired status for you.", { SMS_NOW: "2026-10-19T12:00:00+00:00" });
  runSms(dir, ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes"], { SMS_NOW: "2026-10-19T12:31:00+00:00" });
  const draft = JSON.parse(readFileSync(join(dir, "drafts", `${s.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.status, "ignored");
  assert.equal(draft.cancelled_reason, "expired");
});

function prodEnv(dir, extra = {}) {
  // Test mode OFF: SMS_SEND_CONFIRMED_TEST is cleared; stub carrier needs SMS_SEND_STUB_ALLOW.
  const rt = join(dir, "rt.env");
  const pe = join(dir, "proc.environ");
  writeFileSync(rt, "");
  writeFileSync(pe, "");
  return {
    SMS_SEND_CONFIRMED_TEST: "",
    SMS_SEND_STUB_PROVIDER: "1",
    SMS_SEND_STUB_ALLOW: "1",
    SMS_RUNTIME_ENV_FILE: rt,
    SMS_PROC_ENVIRON: pe,
    SMS_TURN_OWNER_E164: "",
    ...extra,
  };
}

test("W7 mapped Telegram SEND requires the box-set TG_TURN_OWNER_ID (test mode off)", () => {
  const base = {
    TELEGRAM_ALLOWED_USERS: `${OWNER_TG},${UNMAPPED_TG}`,
    ARIN_OWNER_IDENTITIES: OWNER_IDENTITIES,
  };
  const cases = [
    // [label, TG_TURN_OWNER_ID, actor, expected]
    ["owner Telegram turn", OWNER_TG, `tg:${OWNER_TG}`, "sent"],
    ["owner Telegram turn bare id", OWNER_TG, OWNER_TG, "sent"],
    ["execute_code: no Telegram turn", "", `tg:${OWNER_TG}`, "refused_not_owner"],
    ["turn from another Telegram id", UNMAPPED_TG, `tg:${OWNER_TG}`, "refused_not_owner"],
    ["unmapped id on its own turn", UNMAPPED_TG, `tg:${UNMAPPED_TG}`, "refused_not_owner"],
  ];
  for (const [label, tgTurn, actor, expected] of cases) {
    const dir = home();
    const s = stage(dir, "Hi Dana, Telegram turn binding check.", base);
    assert.equal(s.payload.outcome, "staged", label);
    const before = draftSnapshot(dir, s.payload.draft_id);
    const r = runSms(
      dir,
      ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes", "--actor", actor],
      prodEnv(dir, { ...base, TG_TURN_OWNER_ID: tgTurn }),
    );
    assert.equal(r.payload.outcome, expected, label);
    if (expected !== "sent") {
      assert.equal(outcomeLines(dir).length, 0, label);
      assertDraftUnchanged(dir, s.payload.draft_id, before);
    }
  }
});

test("W7 mapped Telegram SEND without TG_TURN_OWNER_ID is refused even in test mode", () => {
  const envExtra = {
    TELEGRAM_ALLOWED_USERS: OWNER_TG,
    ARIN_OWNER_IDENTITIES: OWNER_IDENTITIES,
    SMS_SEND_STUB_PROVIDER: "1",
  };
  const dir = home();
  const s = stage(dir, "Hi Dana, model-run Telegram send.", envExtra);
  const r = runSms(
    dir,
    ["send", "--draft-id", s.payload.draft_id, "--confirm", "SEND", "--attest", "yes", "--actor", `tg:${OWNER_TG}`],
    envExtra,
  );
  assert.equal(r.payload.outcome, "refused_not_owner");
  assert.equal(outcomeLines(dir).length, 0);
});

test("W7 mapped Telegram re-stage stays refused on a real owner Telegram turn", () => {
  const envExtra = {
    TELEGRAM_ALLOWED_USERS: OWNER_TG,
    ARIN_OWNER_IDENTITIES: OWNER_IDENTITIES,
  };
  const dir = home();
  const s = stage(dir, "Hi Dana, Telegram re-stage stays blocked.", envExtra);
  const r = runSms(
    dir,
    [
      "stage", "--approver", OWNER, "--dest", DEST, "--body", "Hi Dana, Telegram edit.",
      "--why", "They wanted a shorter note before the call", "--source-kind", "owner_text",
      "--replaces", s.payload.draft_id, "--actor", `tg:${OWNER_TG}`,
    ],
    prodEnv(dir, { ...envExtra, TG_TURN_OWNER_ID: OWNER_TG }),
  );
  assert.equal(r.payload.outcome, "refused_not_owner");
});
