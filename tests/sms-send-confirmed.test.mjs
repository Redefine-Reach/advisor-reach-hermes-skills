// Hermetic contract for sms-send-confirmed (RED-390 PR1). No network, no Hermes.
// The script is the gate: stage never sends; send requires SEND plus attestation;
// opt-out, cron, multi-dest, and a non-spike box never call the transport.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir, hostname } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const skillPath = join(root, "skills", "sms-send-confirmed", "SKILL.md");
const scriptPath = join(root, "skills", "sms-send-confirmed", "scripts", "sms_send_confirmed.py");
const skill = readFileSync(skillPath, "utf8");
const script = readFileSync(scriptPath, "utf8");

const OWNER = "+17145550100";
const DEST = "+15555550199";
const FROM = "+19283563339";
const BODY = "The listing packet is ready.";

function podLabel() {
  const short = hostname().split(".")[0].toLowerCase();
  const match = short.match(/^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)-\d+$/);
  return match ? match[1] : null;
}

function run(args, extra = {}, dir = mkdtempSync(join(tmpdir(), "sms-send-"))) {
  const calls = join(dir, "calls.jsonl");
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
  mkdirSync(join(dir, "drafts"), { recursive: true });
  const env = {
    PATH: process.env.PATH,
    HOME: process.env.HOME || dir,
    LANG: "C.UTF-8",
    SMS_SEND_CONFIRMED_TEST: "1",
    SMS_BOX_ID: "advisor-reach-internal",
    TELNYX_SMS_FROM_NUMBER: FROM,
    TELNYX_SMS_ALLOWED_USERS: OWNER,
    SMS_AUDIT_PATH: join(dir, "sms-outbound.jsonl"),
    SMS_OPT_OUT_FILE: join(dir, "sms-opt-out.txt"),
    SMS_DRAFT_DIR: join(dir, "drafts"),
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
  const callLines = existsSync(calls) ? readFileSync(calls, "utf8").trim().split("\n").filter(Boolean) : [];
  const auditPath = env.SMS_AUDIT_PATH;
  const auditLines = existsSync(auditPath)
    ? readFileSync(auditPath, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line))
    : [];
  return { proc, payload, callLines, auditLines, dir, env };
}

function py(code) {
  const proc = spawnSync("python3", ["-c", code], {
    env: { ...process.env, PYTHONPATH: root },
    encoding: "utf8",
  });
  assert.equal(proc.status, 0, proc.stderr);
  return proc.stdout.trim();
}

const importMod = `
import importlib.util
spec = importlib.util.spec_from_file_location("sms_send_confirmed", ${JSON.stringify(scriptPath)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
`;

test("skill routes third-party SMS through confirm, the pinned adapter, and the script", () => {
  assert.match(skill, /^name: sms-send-confirmed$/m);
  assert.match(skill, /Text one third party an SMS from this box's Telnyx number/);
  assert.match(skill, /team-telnyx\/telnyx-hermes-sms` @ `a7d209f`/);
  assert.match(skill, /hermes send --to telnyx_sms:<E\.164>/);
  assert.match(skill, /TELNYX_SMS_FROM_NUMBER/);
  assert.match(skill, /Do not call `hermes send` yourself/);
  assert.match(skill, /curl Telnyx/);
  assert.match(skill, /Do not add the destination to `TELNYX_SMS_ALLOWED_USERS`/);
  assert.match(skill, /Prepare-never-send stays the default/);
  assert.match(skill, /schedule-text/);
  assert.match(skill, /advisor-reach-internal/);
  assert.match(skill, /Your entire reply to the owner is the JSON `attestation` field, verbatim/);
  assert.match(skill, /exactly `SEND` or `\/approve`/);
  assert.match(skill, /refused_no_confirm/);
  assert.match(skill, /refused_no_attestation/);
  assert.match(skill, /refused_stop/);
  assert.match(skill, /refused_autonomous/);
  assert.match(skill, /refused_multi/);
  assert.match(skill, /\/opt\/data\/audit\/sms-outbound\.jsonl/);
  assert.match(skill, /\/opt\/data\/audit\/sms-opt-out\.txt/);
  assert.match(skill, /Never tell the owner to reply `Stop` or `STOP`/);
  assert.match(skill, /Session routing for recent destinations is a follow-up \(A2\)/);
  assert.match(skill, /640 characters/);
});

test("script does not call Telnyx itself and does not take a From override", () => {
  assert.doesNotMatch(script, /api\.telnyx\.com/);
  assert.match(script, /telnyx_sms:/);
  assert.match(script, /a7d209f/);
  const argv = py(`${importMod}
print("\\n".join(mod.build_hermes_argv("+15555550199", "/tmp/body.txt")))
`);
  assert.match(argv, /^hermes\nsend\n--to\ntelnyx_sms:\+15555550199\n--json\n--file\n\/tmp\/body.txt$/);
  assert.doesNotMatch(argv, /--from/);
});

test("pod hostname identifies the box and cannot be overridden", () => {
  const out = py(`${importMod}
assert mod.box_id_from_hostname("advisor-reach-internal-0") == "advisor-reach-internal"
assert mod.box_id_from_hostname("marc-king-0") == "marc-king"
assert mod.box_id_from_hostname("advisor-reach-cos-pilot-0") == "advisor-reach-cos-pilot"
assert mod.box_id_from_hostname("cursor") is None
assert mod.resolve_box_id("marc-king-0", {
    "SMS_BOX_ID": "advisor-reach-internal",
    "BOX_PUBLIC_BASE_URL": "https://advisor-reach-internal.boxes.advisorreach.ai",
}) == "marc-king"
assert mod.resolve_box_id("cursor", {
    "BOX_PUBLIC_BASE_URL": "https://advisor-reach-internal.boxes.advisorreach.ai",
    "SMS_BOX_ID": "marc-king",
}) == "advisor-reach-internal"
print("ok")
`);
  assert.equal(out, "ok");
});

test("stage shows attestation and does not send", () => {
  assert.equal(podLabel(), null, "CLI tests assume this host is not a customer pod");
  const { payload, callLines, auditLines } = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
  ]);
  assert.equal(payload.ok, true);
  assert.equal(payload.outcome, "staged");
  assert.equal(payload.provider_called, false);
  assert.equal(payload.from, FROM);
  assert.equal(payload.dest, DEST);
  assert.match(payload.attestation, /from ARIN's number \(\+19283563339\) to \+15555550199/);
  assert.match(payload.attestation, /Reply SEND to confirm you authorize this one message/);
  assert.match(payload.attestation, new RegExp(BODY));
  assert.equal(callLines.length, 0);
  assert.equal(auditLines.length, 0);
});

test("send without attestation does not call Telnyx and can be retried once", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-attest-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  const refused = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "no"],
    {},
    dir,
  );
  assert.equal(refused.payload.outcome, "refused_no_attestation");
  assert.equal(refused.payload.provider_called, false);
  assert.equal(refused.callLines.length, 0);
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(sent.payload.telnyx_message_id, "msg_test_1");
  assert.equal(sent.payload.provider_status, "queued");
  assert.equal(sent.payload.from, FROM);
  assert.equal(sent.callLines.length, 1);
  const request = JSON.parse(sent.callLines[0]);
  assert.deepEqual(request, { to: DEST, text: BODY });
  assert.equal(sent.auditLines.length, 2);
  const row = sent.auditLines[1];
  for (const key of [
    "approver",
    "approved_at",
    "dest",
    "from",
    "body_hash",
    "body_len",
    "telnyx_message_id",
    "provider_status",
    "outcome",
  ]) {
    assert.ok(row[key], key);
  }
  assert.equal(row.approver, OWNER);
  assert.equal(row.dest, DEST);
  assert.equal(row.from, FROM);
  assert.equal(row.outcome, "sent");
  assert.equal(row.telnyx_message_id, "msg_test_1");
  assert.equal(row.provider_called, true);
  assert.doesNotMatch(JSON.stringify(row), new RegExp(BODY));
  const again = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(again.payload.outcome, "refused_duplicate");
  assert.equal(again.callLines.length, 1);
});

test("/approve is the same confirm token", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-approve-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", "(555) 555-0198", "--body", BODY], {}, dir);
  assert.equal(staged.payload.dest, "+15555550198");
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "/approve", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(JSON.parse(sent.callLines[0]).to, "+15555550198");
});

test("a non-SEND reply cancels and does not send", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-cancel-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  const refused = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "yes send it", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(refused.payload.outcome, "refused_no_confirm");
  assert.equal(refused.callLines.length, 0);
  const later = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(later.payload.outcome, "refused_no_confirm");
  assert.equal(later.callLines.length, 0);
});

test("opt-out is refused before the provider, including a number added after stage", () => {
  const blocked = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY],
    {},
  );
  writeFileSync(blocked.env.SMS_OPT_OUT_FILE, `# local deny\n${DEST}\n`);
  const denied = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, blocked.dir);
  assert.equal(denied.payload.outcome, "refused_stop");
  assert.equal(denied.callLines.length, 0);
  assert.equal(denied.auditLines.at(-1).outcome, "refused_stop");
  assert.equal(denied.auditLines.at(-1).provider_called, false);

  const fresh = mkdtempSync(join(tmpdir(), "sms-opt-later-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, fresh);
  writeFileSync(staged.env.SMS_OPT_OUT_FILE, `${DEST}\n`);
  const refused = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    fresh,
  );
  assert.equal(refused.payload.outcome, "refused_stop");
  assert.equal(refused.callLines.length, 0);
});

test("deny records a number without sending", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-deny-"));
  const recorded = run(["deny", "--approver", OWNER, "--dest", "5555550197"], {}, dir);
  assert.equal(recorded.payload.outcome, "opt_out_recorded");
  assert.equal(recorded.callLines.length, 0);
  assert.match(readFileSync(recorded.env.SMS_OPT_OUT_FILE, "utf8"), /\+15555550197/);
  const staged = run(["stage", "--approver", OWNER, "--dest", "+15555550197", "--body", BODY], {}, dir);
  assert.equal(staged.payload.outcome, "refused_stop");
});

test("multi-dest, overlong body, cron, allow-all, and a foreign box never send", () => {
  const multi = run(["stage", "--approver", OWNER, "--dest", `${DEST},${DEST}`, "--body", BODY]);
  assert.equal(multi.payload.outcome, "refused_multi");
  assert.equal(multi.callLines.length, 0);

  const longBody = "x".repeat(641);
  const long = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", longBody]);
  assert.equal(long.payload.outcome, "refused_multi");
  assert.equal(long.callLines.length, 0);

  const cron = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    HERMES_CRON_JOB_ID: "job-1",
  });
  assert.equal(cron.payload.outcome, "refused_autonomous");
  assert.equal(cron.callLines.length, 0);

  const allowAll = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    TELNYX_SMS_ALLOW_ALL_USERS: "true",
  });
  assert.equal(allowAll.payload.outcome, "refused_autonomous");

  const marc = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    SMS_BOX_ID: "marc-king",
  });
  assert.equal(marc.payload.outcome, "refused_spike_box");
  assert.equal(marc.callLines.length, 0);

  const ownerThread = run(["stage", "--approver", OWNER, "--dest", OWNER, "--body", BODY]);
  assert.equal(ownerThread.payload.outcome, "refused_not_third_party");
  assert.equal(ownerThread.callLines.length, 0);
});

test("a corrupt opt-out line fails closed", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-bad-opt-"));
  const first = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  writeFileSync(first.env.SMS_OPT_OUT_FILE, "not-a-phone\n");
  const refused = run(["stage", "--approver", OWNER, "--dest", "+15555550196", "--body", BODY], {}, dir);
  assert.equal(refused.payload.outcome, "error");
  assert.match(refused.payload.reason, /opt-out list/);
  assert.equal(refused.callLines.length, 0);
});

test("an expired draft does not send", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-ttl-"));
  const staged = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY],
    { SMS_DRAFT_TTL_SECONDS: "0" },
    dir,
  );
  const refused = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    { SMS_DRAFT_TTL_SECONDS: "0" },
    dir,
  );
  assert.equal(refused.payload.outcome, "refused_no_confirm");
  assert.match(refused.payload.reason, /expired/);
  assert.equal(refused.callLines.length, 0);
});

test("a non-owner and a missing From are refused", () => {
  const stranger = run(["stage", "--approver", "+15555550111", "--dest", DEST, "--body", BODY]);
  assert.equal(stranger.payload.outcome, "refused_not_owner");
  assert.equal(stranger.callLines.length, 0);
  const missingFrom = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    TELNYX_SMS_FROM_NUMBER: "",
  });
  assert.equal(missingFrom.payload.outcome, "error");
  assert.equal(missingFrom.payload.field, "from");
  assert.equal(missingFrom.callLines.length, 0);
});

test("argparse rejects a From override", () => {
  const { proc, callLines } = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--from",
    "+19999999999",
  ]);
  assert.notEqual(proc.status, 0);
  assert.equal(callLines.length, 0);
});
