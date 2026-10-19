// RED-596 draft outcome log + AC7 stub provider. Hermetic; fictional 555 numbers only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const scriptPath = join(root, "skills", "sms-send-confirmed", "scripts", "sms_send_confirmed.py");
const outcomeModPath = join(root, "skills", "sms-send-confirmed", "scripts", "draft_outcome_log.py");

const OWNER = "+17145550100";
const DEST = "+15555550199";
const FROM = "+19283563339";
const WHY = "Hendersons want the comparison before the 4 PM call";

const OUTCOME_KEYS = new Set([
  "ts",
  "draft_id",
  "kind",
  "outcome",
  "edit_rounds",
  "replaces_chain",
  "body_hash_first",
  "body_hash_final",
  "edit_distance",
  "len_first",
  "len_final",
  "hours_to_decision",
]);

function home() {
  const dir = mkdtempSync(join(tmpdir(), "draft-outcome-"));
  mkdirSync(join(dir, "drafts"), { recursive: true });
  return dir;
}

function runSms(dir, args, extra = {}) {
  const transport = join(dir, "transport.py");
  writeFileSync(
    transport,
    [
      "#!/usr/bin/env python3",
      "import json, os, sys",
      "req = json.load(sys.stdin)",
      "with open(os.environ['CALLS'], 'a', encoding='utf-8') as fh:",
      "    fh.write(json.dumps(req) + '\\n')",
      "json.dump({'success': True, 'message_id': 'msg_test_1', 'provider_status': 'queued'}, sys.stdout)",
      "",
    ].join("\n"),
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
  const proc = spawnSync("python3", [scriptPath, ...args], { env, encoding: "utf8" });
  let payload = null;
  try {
    payload = JSON.parse(proc.stdout || "null");
  } catch {
    payload = null;
  }
  const outcomes = existsSync(env.DRAFT_OUTCOMES_PATH)
    ? readFileSync(env.DRAFT_OUTCOMES_PATH, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l))
    : [];
  const callsMade = existsSync(calls) ? readFileSync(calls, "utf8").trim() : "";
  return { proc, payload, outcomes, callsMade, env, dir };
}

function stage(dir, body, extra = {}) {
  const replaces = extra.replaces;
  const why = extra.why || WHY;
  const { replaces: _drop, why: _why, ...envExtra } = extra;
  return runSms(
    dir,
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      body,
      "--why",
      why,
      "--source-kind",
      "owner_text",
      ...(replaces ? ["--replaces", replaces] : []),
    ],
    envExtra,
  );
}

function readDraft(dir, draftId) {
  return JSON.parse(readFileSync(join(dir, "drafts", `${draftId}.json`), "utf8"));
}

test("sent as is writes one outcome line with stubbed provider_called false", () => {
  const dir = home();
  const staged = stage(dir, "Hi from ARIN at example.com desk.");
  assert.equal(staged.payload.outcome, "staged");
  const draftId = staged.payload.draft_id;
  const sent = runSms(
    dir,
    ["send", "--draft-id", draftId, "--confirm", "SEND", "--attest", "yes"],
    { SMS_SEND_STUB_PROVIDER: "1" },
  );
  assert.equal(sent.proc.status, 0, sent.proc.stderr);
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(sent.payload.provider_called, false);
  assert.equal(sent.callsMade, "");
  assert.equal(sent.outcomes.length, 1);
  assert.equal(sent.outcomes[0].outcome, "sent_as_is");
  assert.equal(sent.outcomes[0].edit_rounds, 0);
  assert.equal(sent.outcomes[0].kind, "sms");
});

test("sent after one edit links replaces_chain and edit_rounds 1", () => {
  const dir = home();
  const first = stage(dir, "Hello there, hope you are well!");
  const draft1 = first.payload.draft_id;
  const second = stage(dir, "Hey friend", {
    replaces: draft1,
    why: "They want a warmer shorter hello before the comparison call",
  });
  assert.equal(second.payload.replaces, draft1);
  const draft2 = second.payload.draft_id;
  assert.equal(readDraft(dir, draft2).replaces, draft1);
  const sent = runSms(
    dir,
    ["send", "--draft-id", draft2, "--confirm", "SEND", "--attest", "yes"],
    { SMS_SEND_STUB_PROVIDER: "1" },
  );
  assert.equal(sent.outcomes.length, 1);
  assert.equal(sent.outcomes[0].outcome, "sent_after_edit");
  assert.equal(sent.outcomes[0].edit_rounds, 1);
  assert.deepEqual(sent.outcomes[0].replaces_chain, [draft1]);
});

test("owner drop writes cancelled with audit refused_no_confirm preserved", () => {
  const dir = home();
  const staged = stage(dir, "Ping when you can.");
  const draftId = staged.payload.draft_id;
  const dropped = runSms(dir, ["send", "--draft-id", draftId, "--confirm", "DROP", "--attest", "yes"]);
  assert.equal(dropped.payload.outcome, "refused_no_confirm");
  const outcomesPath = join(dir, "draft-outcomes.jsonl");
  const droppedOutcomes = readFileSync(outcomesPath, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
  assert.equal(droppedOutcomes.length, 1);
  assert.equal(droppedOutcomes[0].outcome, "cancelled");
  const audit = readFileSync(join(dir, "sms-outbound.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.ok(audit.some((row) => row.outcome === "refused_no_confirm"));
});

test("expired pending draft becomes ignored on sweep with frozen clock", () => {
  const dir = home();
  const staged = stage(dir, "Still waiting on your reply.", { SMS_NOW: "2026-10-19T12:00:00+00:00" });
  const draftId = staged.payload.draft_id;
  const later = runSms(dir, ["sweep-outcomes"], { SMS_NOW: "2026-10-19T12:31:00+00:00" });
  assert.equal(later.payload.ignored, 1);
  const swept = readFileSync(join(dir, "draft-outcomes.jsonl"), "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
  assert.equal(swept.length, 1);
  assert.equal(swept[0].outcome, "ignored");
  const file = readDraft(dir, draftId);
  assert.notEqual(file.status, "pending");
});

test("outcome lines match schema and never-contains guard rejects canary leakage", () => {
  const dir = home();
  const canaryName = "Zephyr Canari";
  const staged = stage(dir, `Hi ${canaryName}, call 555-010-0199 or email you@example.com`);
  const sent = runSms(
    dir,
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    { SMS_SEND_STUB_PROVIDER: "1" },
  );
  const line = sent.outcomes[0];
  for (const key of OUTCOME_KEYS) assert.ok(key in line, key);
  const blob = JSON.stringify(line);
  assert.doesNotMatch(blob, /example\.com/i);
  assert.doesNotMatch(blob, /555/);
  assert.doesNotMatch(blob, new RegExp(canaryName, "i"));
  assert.match(line.draft_id, /^[0-9a-f]{16}$/);

  const bad = { ...line, dest: "+15555550199" };
  const guard = spawnSync(
    "python3",
    [
      "-c",
      "import json, sys; import draft_outcome_log as m; m.validate_outcome_line(json.loads(sys.argv[1]))",
      JSON.stringify(bad),
    ],
    { encoding: "utf8", env: { ...process.env, PYTHONPATH: dirname(outcomeModPath) } },
  );
  assert.notEqual(guard.status, 0);
});

test("exporter emits only day box kind outcome count", () => {
  const dir = home();
  const staged = stage(dir, "Quick check-in.");
  runSms(
    dir,
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    { SMS_SEND_STUB_PROVIDER: "1" },
  );
  const exported = runSms(dir, ["export-outcomes"]);
  assert.equal(exported.proc.status, 0);
  for (const row of exported.payload.rows) {
    assert.deepEqual(new Set(Object.keys(row)), new Set(["day", "box", "kind", "outcome", "count"]));
  }
  const blob = JSON.stringify(exported.payload.rows);
  assert.doesNotMatch(blob, /draft_id/);
  assert.doesNotMatch(blob, /body_hash/);
});
