// RED-740: exercise today's CLI gate without changing it or sharing PR #70's file.
// Synthetic 555 numbers, isolated files, frozen time, built-in stub; no transport.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const script = join(dirname(fileURLToPath(import.meta.url)), "..", "skills",
  "sms-send-confirmed", "scripts", "sms_send_confirmed.py");
const OWNER = "+12025550100";
const OTHER_OWNER = "+12025550101";
const DEST_A = "+12025550102";
const DEST_B = "+12025550103";
const FROM = "+12025550104";
const BODY_A = "Hi Dana, your showing is tomorrow at 10.";
const BODY_B = "Hi Dana, your showing is tomorrow at 11.";
const WHY_A = "Dana's showing is tomorrow at 10";
const WHY_B = "Dana's showing moved to 11 tomorrow";
const NOW = "2026-10-22T12:00:00+00:00";

function rows(path) {
  return existsSync(path)
    ? readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
    : [];
}

function outbound(audit) {
  // Stub sends report provider_called:false too: that flag alone proves nothing.
  return audit.filter((row) => row.outcome === "sent" || row.provider_called === true || row.telnyx_message_id);
}

function harness(t) {
  const dir = mkdtempSync(join(tmpdir(), "red740-sms-gate-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const auditPath = join(dir, "sms-outbound.jsonl");
  const outcomesPath = join(dir, "draft-outcomes.jsonl");
  const drafts = join(dir, "drafts");
  const env = {
    PATH: process.env.PATH,
    ...(process.platform === "win32" ? { SystemRoot: process.env.SystemRoot } : {}),
    HOME: dir,
    USERPROFILE: dir,
    TMPDIR: dir,
    TEMP: dir,
    TMP: dir,
    LANG: "C.UTF-8",
    PYTHONIOENCODING: "utf-8",
    PYTHONDONTWRITEBYTECODE: "1",
    SMS_SEND_CONFIRMED_TEST: "1",
    SMS_SEND_STUB_PROVIDER: "1",
    SMS_BOX_ID: "red740-synthetic",
    TELNYX_SMS_FROM_NUMBER: FROM,
    TELNYX_SMS_ALLOWED_USERS: `${OWNER},${OTHER_OWNER}`,
    SMS_TURN_OWNER_E164: OWNER,
    SMS_DRAFT_DIR: drafts,
    SMS_AUDIT_PATH: auditPath,
    DRAFT_OUTCOMES_PATH: outcomesPath,
    SMS_OPT_OUT_FILE: join(dir, "opt-out.txt"),
    SMS_SESSION_DIR: join(dir, "sessions"),
    SMS_EVENT_DIR: join(dir, "events"),
    SMS_NOW: NOW,
    DRAFT_OUTCOME_NOW: NOW,
  };

  function run(args, extra = {}) {
    const before = rows(auditPath);
    const proc = spawnSync("python3", [script, ...args], {
      env: { ...env, ...extra }, encoding: "utf8", timeout: 15_000,
    });
    assert.ifError(proc.error);
    assert.equal(proc.signal, null, proc.stderr);
    const payload = JSON.parse(proc.stdout);
    const audit = rows(auditPath);
    return { proc, payload, audit, addedAudit: audit.slice(before.length), outcomes: rows(outcomesPath) };
  }

  function stage({ body = BODY_A, why = WHY_A, dest = DEST_A, approver = OWNER, replaces } = {}) {
    const result = run(["stage", "--approver", approver, "--dest", dest,
      "--body", body, "--why", why, "--source-kind", "owner_text",
      ...(replaces ? ["--replaces", replaces, "--actor", OWNER] : [])]);
    assert.equal(result.proc.status, 0, JSON.stringify(result.payload));
    assert.equal(result.payload.outcome, "staged");
    assert.equal(result.payload.provider_called, false);
    assert.equal(outbound(result.addedAudit).length, 0);
    assert.match(result.payload.attestation, /Reply SEND to confirm/);
    return result.payload;
  }

  function send(id, { confirm = "SEND", actor = OWNER, env: extra = {} } = {}) {
    return run(["send", "--draft-id", id, "--confirm", confirm, "--attest", "yes", "--actor", actor], extra);
  }

  function draft(id) {
    return JSON.parse(readFileSync(join(drafts, `${id}.json`), "utf8"));
  }

  return { run, stage, send, draft };
}

function refused(result, code) {
  assert.deepEqual({
    status: result.proc.status,
    outcome: result.payload.outcome,
    provider_called: result.payload.provider_called,
    outbound: outbound(result.addedAudit),
  }, {
    status: code === "error" ? 1 : 2,
    outcome: code,
    provider_called: false,
    outbound: [],
  }, JSON.stringify(result.payload));
}

function sent(result, id, dest, body) {
  assert.equal(result.proc.status, 0, JSON.stringify(result.payload));
  assert.equal(result.payload.outcome, "sent");
  assert.equal(result.payload.provider_called, false);
  assert.equal(result.payload.provider_status, "stubbed");
  const digest = createHash("sha256").update(`${dest}\0${body}`).digest("hex").slice(0, 16);
  assert.equal(result.payload.telnyx_message_id, `stub-${digest}`);
  assert.equal(result.payload.draft_id, id);
  assert.equal(result.payload.dest, dest);
  assert.equal(result.payload.from, FROM);
  assert.equal(outbound(result.addedAudit).length, 1);
  const row = outbound(result.addedAudit)[0];
  assert.equal(row.draft_id, id);
  assert.equal(row.dest, dest);
  assert.equal(row.body_hash, createHash("sha256").update(body).digest("hex"));
  assert.equal(row.provider_called, false);
  assert.equal(row.provider_status, "stubbed");
}

test("AC1: SEND tied to cancelled draft A cannot send later draft B", (t) => {
  const h = harness(t);
  const a = h.stage();
  const cancelled = h.run(["cancel", "--draft-id", a.draft_id, "--actor", OWNER]);
  assert.equal(cancelled.payload.outcome, "cancelled");
  const b = h.stage({ body: "Hi Lee, your showing is tomorrow at 2.",
    why: "Lee's showing is tomorrow at 2", dest: DEST_B });
  assert.notEqual(a.draft_id, b.draft_id);
  refused(h.send(a.draft_id), "refused_no_confirm");
  assert.equal(h.draft(b.draft_id).status, "pending");
  sent(h.send(b.draft_id), b.draft_id, DEST_B, "Hi Lee, your showing is tomorrow at 2.");
});

for (const [label, body, why] of [["restage", BODY_A, WHY_A], ["edit", BODY_B, WHY_B]]) {
  test(`AC1: stage --replaces (${label}) invalidates the old SEND id`, (t) => {
    const h = harness(t);
    const a = h.stage();
    const b = h.stage({ body, why, replaces: a.draft_id });
    assert.notEqual(a.draft_id, b.draft_id);
    assert.equal(b.replaces, a.draft_id);
    assert.equal(h.draft(a.draft_id).status, "superseded");
    refused(h.send(a.draft_id), "refused_no_confirm");
    assert.equal(h.draft(b.draft_id).status, "pending");
    assert.equal(h.draft(b.draft_id).body, body);
    sent(h.send(b.draft_id), b.draft_id, DEST_A, body); // Fresh SEND for B only.
  });
}

test("AC2: exact SEND succeeds once through the stub; duplicate adds no outbound line", (t) => {
  const h = harness(t);
  const a = h.stage();
  sent(h.send(a.draft_id), a.draft_id, DEST_A, BODY_A);
  const again = h.send(a.draft_id);
  refused(again, "refused_duplicate");
  assert.equal(outbound(again.audit).length, 1);
  assert.equal(again.outcomes.length, 1);
  assert.equal(again.outcomes[0].outcome, "sent_as_is");
});

for (const confirm of ["do it", "ok", "yes", "sure", "send it", "Send!", "SEND please", "👍"]) {
  test(`AC5: ${JSON.stringify(confirm)} cannot approve, including a later retry`, (t) => {
    const h = harness(t);
    const a = h.stage();
    refused(h.send(a.draft_id, { confirm }), "refused_no_confirm");
    refused(h.send(a.draft_id), "refused_no_confirm");
  });
}

test("AC5: exact SEND is a positive control in the same hermetic harness", (t) => {
  const h = harness(t);
  const a = h.stage();
  sent(h.send(a.draft_id, { confirm: "SEND" }), a.draft_id, DEST_A, BODY_A);
});

test("stale approval: default 30-minute window expires at frozen +31 minutes", (t) => {
  const h = harness(t);
  const a = h.stage();
  assert.equal(Date.parse(a.expires_at) - Date.parse(NOW), 30 * 60 * 1000);
  const late = h.send(a.draft_id, { env: { SMS_NOW: "2026-10-22T12:31:00+00:00",
    DRAFT_OUTCOME_NOW: "2026-10-22T12:31:00+00:00" } });
  refused(late, "refused_no_confirm");
  assert.match(late.payload.reason, /confirmation window expired/);
  assert.equal(h.draft(a.draft_id).status, "ignored");
});

test("wrong token: nonexistent well-formed id cannot select the pending draft", (t) => {
  const h = harness(t);
  const a = h.stage();
  const missing = a.draft_id === "0000000000000000" ? "1111111111111111" : "0000000000000000";
  const result = h.send(missing);
  refused(result, "error");
  assert.equal(result.payload.field, "draft_id");
  assert.match(result.payload.reason, /draft was not found/);
  assert.equal(h.draft(a.draft_id).status, "pending");
});

for (const id of ["not-a-draft", "../0000000000000000", "0123456789abcdeg", "0123456789abcdef0", ""]) {
  test(`wrong token: malformed id ${JSON.stringify(id)} is refused`, (t) => {
    const h = harness(t);
    const a = h.stage();
    const result = h.send(id);
    refused(result, "error");
    assert.equal(result.payload.field, "draft_id");
    assert.match(result.payload.reason, /draft id is not valid/);
    assert.equal(h.draft(a.draft_id).status, "pending");
  });
}

test("wrong token: a valid id belonging to another owner's draft is refused", (t) => {
  const h = harness(t);
  const other = h.stage({ approver: OTHER_OWNER });
  refused(h.send(other.draft_id), "refused_not_owner");
  assert.equal(h.draft(other.draft_id).status, "pending");
});

// The script accepts identity markers, not a session/source object. These pin
// mismatched markers; the TODOs below cover origins with no trusted owner marker.
for (const [label, turn] of [
  ["A2A peer", "a2a:red740-peer"],
  ["group", "group:red740-thread"],
  ["multiparty", `${OWNER},${OTHER_OWNER}`],
]) {
  test(`wrong channel: ${label} turn marker cannot impersonate the owner`, (t) => {
    const h = harness(t);
    const a = h.stage();
    refused(h.send(a.draft_id, { env: { SMS_TURN_OWNER_E164: turn } }), "refused_not_owner");
    assert.equal(h.draft(a.draft_id).status, "pending");
  });
}

for (const [name, value] of [
  ["HERMES_DELEGATED_CHILD_CONTEXT", "1"],
  ["HERMES_CRON_JOB_ID", "red740-synthetic-job"],
  ["HERMES_CRON_JOB_NAME", "red740-synthetic-cron"],
  ["HERMES_CRON_AUTO_DELIVER_PLATFORM", "telnyx_sms"],
  ["HERMES_CRON_AUTO_DELIVER_CHAT_ID", OWNER],
]) {
  test(`wrong channel: ${name} refuses SEND even with the owner's actor`, (t) => {
    const h = harness(t);
    const a = h.stage();
    refused(h.send(a.draft_id, { env: { [name]: value } }), "refused_autonomous");
    assert.equal(h.draft(a.draft_id).status, "pending");
  });
}

for (const origin of ["A2A", "group", "multiparty"]) {
  test(`wrong channel: ${origin} origin without a trusted SMS owner turn must refuse`, {
    todo: "GAP RED-692: the script has no origin input; in test mode a missing SMS_TURN_OWNER_E164 bypasses the turn check. This CLI fixture cannot prove production session-origin rejection.",
  }, (t) => {
    const h = harness(t);
    const a = h.stage();
    // Model the script boundary of a non-owner-text session: no box-set marker.
    // Do not invent an origin environment variable that this gate never reads.
    refused(h.send(a.draft_id, { env: { SMS_TURN_OWNER_E164: "" } }), "refused_not_owner");
  });
}
