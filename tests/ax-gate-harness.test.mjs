// RED-782: long-lived synthetic SEND refusal matrix, discovered by the CI glob.
// Reuse RED-740 verbatim, including its positive controls and documented TODOs.
import "./sms-send-gate-regression.test.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const script = join(dirname(fileURLToPath(import.meta.url)), "..", "skills",
  "email-send-confirmed", "scripts", "email_send_confirmed.py");
const OWNER = "+12025550100";
const BODY = "The synthetic listing packet is ready.";

function rows(path) {
  return existsSync(path)
    ? readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
    : [];
}

function emailHarness(t) {
  const dir = mkdtempSync(join(tmpdir(), "red782-email-gate-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const drafts = join(dir, "drafts");
  const calls = join(dir, "calls.jsonl");
  const audit = join(dir, "email-outbound.jsonl");
  const transport = join(dir, "transport.py");
  // Same transport contract as email-send-confirmed.test.mjs. Any invocation is
  // recorded independently of provider_called; no credentials or network exist.
  writeFileSync(transport, [
    "#!/usr/bin/env python3",
    "import json, os, sys",
    "request = json.load(sys.stdin)",
    "with open(os.environ['CALLS'], 'a', encoding='utf-8') as fh:",
    "    fh.write(json.dumps(request) + '\\n')",
    "json.dump({'success': True, 'message_id': 'red782-synthetic', 'provider_status': 'stubbed'}, sys.stdout)",
    "",
  ].join("\n"));
  chmodSync(transport, 0o755);
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
    EMAIL_SEND_CONFIRMED_TEST: "1",
    EMAIL_NOW: "2026-10-23T12:00:00+00:00",
    EMAIL_DRAFT_DIR: drafts,
    EMAIL_AUDIT_PATH: audit,
    EMAIL_SEND_TRANSPORT: transport,
    CALLS: calls,
    SMS_BOX_ID: "red782-synthetic",
    TELNYX_SMS_ALLOWED_USERS: OWNER,
  };

  function run(args, extra = {}) {
    const proc = spawnSync("python3", [script, ...args], {
      env: { ...env, ...extra }, encoding: "utf8", timeout: 15_000,
    });
    assert.ifError(proc.error);
    assert.equal(proc.signal, null, proc.stderr);
    assert.equal(proc.stderr, "");
    return { proc, payload: JSON.parse(proc.stdout), calls: rows(calls), audit: rows(audit) };
  }

  function stage() {
    const result = run(["stage", "--approver", OWNER, "--to", "dana@example.com",
      "--subject", "Synthetic listing packet", "--body", BODY,
      "--from-account", "advisor@example.com", "--connected-account", "ca_red782_synthetic",
      "--why", "you asked for the listing packet today", "--source-kind", "owner_text",
      "--source-date", "2026-10-23"]);
    assert.equal(result.proc.status, 0, JSON.stringify(result.payload));
    assert.equal(result.payload.outcome, "staged");
    assert.equal(result.payload.provider_called, false);
    assert.match(result.payload.attestation, /Reply SEND to confirm/);
    assert.deepEqual(result.calls, []);
    assert.deepEqual(result.audit, []);
    const draft = readDraft(result.payload.draft_id);
    assert.equal(draft.status, "pending");
    assert.equal(draft.body, BODY);
    return draft;
  }

  function readDraft(id) {
    return JSON.parse(readFileSync(join(drafts, `${id}.json`), "utf8"));
  }

  return {
    run, stage, readDraft,
    draftIds: () => existsSync(drafts) ? readdirSync(drafts).filter((name) => name.endsWith(".json")) : [],
    send: (id, extra = {}) => run(["send", "--draft-id", id, "--confirm", "SEND", "--attest", "yes"], extra),
  };
}

function refused(result, outcome) {
  assert.equal(result.proc.status, outcome === "error" ? 1 : 2, JSON.stringify(result.payload));
  assert.equal(result.payload.ok, false);
  assert.equal(result.payload.outcome, outcome);
  assert.equal(result.payload.provider_called, false);
  assert.deepEqual(result.calls, []);
  assert.equal(result.audit.length, 1);
  assert.equal(result.audit[0].outcome, outcome);
  assert.equal(result.audit[0].provider_called, false);
  assert.ok(!result.audit[0].provider_message_id);
}

test("RED-782 AC2: email SEND with no staged draft refuses without calling the provider", (t) => {
  const h = emailHarness(t);
  const result = h.send("0000000000000000");
  refused(result, "error");
  assert.equal(result.payload.field, "draft_id");
  assert.match(result.payload.reason, /draft was not found/);
  assert.deepEqual(h.draftIds(), []);
});

test("RED-782 AC2: nonexistent email id cannot select another pending draft", (t) => {
  const h = emailHarness(t);
  const draft = h.stage();
  const missing = draft.draft_id === "0000000000000000" ? "1111111111111111" : "0000000000000000";
  const result = h.send(missing);
  refused(result, "error");
  assert.equal(result.payload.field, "draft_id");
  assert.match(result.payload.reason, /draft was not found/);
  assert.deepEqual(h.readDraft(draft.draft_id), draft);
});

for (const [name, value] of [
  ["HERMES_CRON_JOB_ID", "red782-synthetic-job"],
  ["HERMES_CRON_JOB_NAME", "red782-synthetic-cron"],
  ["HERMES_CRON_AUTO_DELIVER_PLATFORM", "telnyx_sms"],
  ["HERMES_CRON_AUTO_DELIVER_CHAT_ID", OWNER],
  ["HERMES_DELEGATED_CHILD_CONTEXT", "1"],
]) {
  test(`RED-782 AC3: ${name} cannot confirm an owner-staged email`, (t) => {
    const h = emailHarness(t);
    const draft = h.stage();
    const result = h.send(draft.draft_id, { [name]: value });
    refused(result, "refused_autonomous");
    assert.match(result.payload.reason, name === "HERMES_DELEGATED_CHILD_CONTEXT" ? /delegated child/ : /scheduled and standing jobs/);
    assert.deepEqual(h.readDraft(draft.draft_id), draft); // Pending and wholly unchanged.
  });
}

test("RED-782 AC4: side-job cannot send", {
  skip: "DEFERRED RED-624: side-job gate coverage awaits the send-script work.",
}, () => {});
