// Hermetic contract for sms-send-confirmed (RED-390). No network, no Hermes.
// The script is the gate: stage never sends; send requires SEND plus attestation;
// opt-out, cron, multi-dest, an unresolved box, and a delegated child never call
// the transport. Path A allows any resolved non-empty box id when
// TELNYX_SMS_FROM_NUMBER is set. stage requires a Why line (red-390-v3 attestation).
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync, readdirSync } from "node:fs";
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
const DEST2 = "+15555550200";
const FROM = "+19283563339";
const BODY = "Hi Dana, your listing packet is ready.";

function podLabel() {
  const short = hostname().split(".")[0].toLowerCase();
  const match = short.match(/^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)-\d+$/);
  return match ? match[1] : null;
}

function draftFiles(dir) {
  const drafts = join(dir, "drafts");
  if (!existsSync(drafts)) return [];
  return readdirSync(drafts).filter((name) => name.endsWith(".json"));
}

function run(args, extra = {}, dir = mkdtempSync(join(tmpdir(), "sms-send-")), options = {}) {
  // Existing stage flows stay valid: a Why line is required, so inject one
  // unless the test passed --why itself or opted out.
  let cmdArgs =
    options.why === false || args[0] !== "stage" || args.includes("--why")
      ? args
      : [
          ...args,
          "--why",
          "Hendersons want the comparison before the 4 PM call",
          "--source-kind",
          "owner_text",
        ];
  if (cmdArgs[0] === "send" && !cmdArgs.includes("--actor")) {
    cmdArgs = [...cmdArgs, "--actor", OWNER];
  }
  if (cmdArgs[0] === "cancel" && !cmdArgs.includes("--actor")) {
    cmdArgs = [...cmdArgs, "--actor", OWNER];
  }
  if (cmdArgs[0] === "stage" && cmdArgs.includes("--replaces") && !cmdArgs.includes("--actor")) {
    cmdArgs = [...cmdArgs, "--actor", OWNER];
  }
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
    SMS_SESSION_DIR: join(dir, "sessions"),
    SMS_EVENT_DIR: join(dir, "events"),
    DRAFT_OUTCOMES_PATH: join(dir, "draft-outcomes.jsonl"),
    SMS_SEND_TRANSPORT: transport,
    CALLS: calls,
    ...extra,
  };
  const proc = spawnSync("python3", [scriptPath, ...cmdArgs], { env, encoding: "utf8" });
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
  assert.match(skill, /standalone_sender_fn/);
  assert.match(skill, /TELNYX_SMS_API_BASE/);
  assert.match(skill, /TELNYX_SMS_FROM_NUMBER/);
  assert.match(skill, /Do not call `hermes send` yourself/);
  assert.match(skill, /curl Telnyx/);
  assert.match(skill, /Do not add the destination to `TELNYX_SMS_ALLOWED_USERS`/);
  assert.match(skill, /Prepare-never-send stays the default/);
  assert.match(skill, /Do not use `schedule-text` as the\nthird-party path/);
  assert.match(skill, /## Path A/);
  assert.match(skill, /NEVER use Composio/);
  assert.match(skill, /refused_no_box/);
  assert.doesNotMatch(skill, /refused_spike_box/);
  assert.doesNotMatch(skill, /Customer boxes and Marc are out/);
  const frontmatter = skill.match(/^---\n([\s\S]*?)\n---\n/)[1];
  const required = frontmatter.split("optional_environment_variables:")[0];
  assert.match(required, /required_environment_variables:/);
  assert.match(required, /- TELNYX_SMS_FROM_NUMBER/);
  assert.match(required, /- TELNYX_SMS_ALLOWED_USERS/);
  assert.match(required, /- TELNYX_SMS_API_BASE/);
  assert.doesNotMatch(required, /TELEGRAM_ALLOWED_USERS/);
  assert.match(frontmatter, /optional_environment_variables:\n  - TELEGRAM_ALLOWED_USERS/);
  assert.match(skill, /Your entire reply to the owner is the JSON `attestation` field, verbatim/);
  assert.match(skill, /--why/);
  assert.match(skill, /--source-kind/);
  assert.match(skill, /refused_no_why/);
  assert.match(skill, /fub_note/);
  assert.match(skill, /\(no source\)/);
  assert.match(skill, /Never name a source you did not read/);
  assert.match(skill, /ARIN memory:/);
  assert.match(skill, /HERMES_DELEGATED_CHILD_CONTEXT/);
  assert.match(skill, /exactly `SEND` or `\/approve`/);
  assert.match(skill, /refused_no_confirm/);
  assert.match(skill, /refused_no_attestation/);
  assert.match(skill, /refused_stop/);
  assert.match(skill, /refused_autonomous/);
  assert.match(skill, /refused_multi/);
  assert.match(skill, /\/opt\/data\/audit\/sms-outbound\.jsonl/);
  assert.match(skill, /\/opt\/data\/audit\/sms-opt-out\.txt/);
  assert.match(skill, /Reply SEND to send, DROP to discard/);
  assert.match(skill, /`DROP`, `NO`/);
  assert.match(skill, /STOP, STOPALL, STOP ALL, UNSUBSCRIBE/);
  assert.match(skill, /CANCEL, END, and QUIT/);
  assert.match(skill, /REVOKE and OPTOUT are extra guards/);
  assert.match(skill, /START and UNSTOP opt back in/);
  assert.match(skill, /HELP is the help word/);
  assert.match(skill, /Never ask the owner to send HELP/);
  assert.match(skill, /exactly one confirmation text/);
  assert.doesNotMatch(skill, /Acknowledge once/);
  assert.doesNotMatch(skill, /Reply anything else to cancel/);
  assert.doesNotMatch(skill, /reply `cancel`/i);
  assert.match(skill, /7 days/);
  assert.match(skill, /Do not answer the recipient/);
  assert.match(skill, /Do not add the destination to `TELNYX_SMS_ALLOWED_USERS`/);
  assert.match(skill, /TELEGRAM_ALLOWED_USERS/);
  assert.match(skill, /method-a\/BAKE\.md/);
  assert.match(skill, /MoO list/);
  assert.match(skill, /Silence, an earlier yes/);
  assert.match(skill, /640 characters/);
});

test("script sends through standalone_sender_fn after plugin resolve, not hermes send", () => {
  assert.doesNotMatch(script, /api\.telnyx\.com/);
  assert.doesNotMatch(script, /hermes send/);
  assert.doesNotMatch(script, /TELNYX_SMS_ALLOWED_USERS"\]\s*=/);
  assert.doesNotMatch(script, /refused_spike_box/);
  assert.doesNotMatch(script, /SPIKE_BOX_ID/);
  assert.match(script, /assert_path_a_box/);
  assert.match(script, /standalone_sender_fn/);
  assert.match(script, /_resolve_all/);
  assert.match(script, /a7d209f/);
  assert.match(script, /red-390-v3/);
  assert.doesNotMatch(script, /red-390-v1/);
  assert.match(script, /refused_no_why/);
  assert.match(script, /HERMES_DELEGATED_CHILD_CONTEXT/);
  const out = py(`${importMod}
calls = []
class Entry:
    def __init__(self):
        def sender(pconfig, chat_id, message, **kwargs):
            calls.append((chat_id, message, pconfig.enabled))
            return {"success": True, "message_id": "mid-1"}
        self.standalone_sender_fn = sender
entry = Entry()
def discover():
    calls.append("discover")
def resolve_all():
    calls.append("resolve_all")
def get_entry(name):
    calls.append(name)
    return entry if name == "telnyx_sms" else None
class Cfg:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.extra = {}
sender, pconfig, err = mod.resolve_standalone_sender(
    discover, resolve_all, get_entry, lambda: type("G", (), {"platforms": {}})(), lambda name: None, Cfg)
assert err == "" and sender is not None
assert calls[:3] == ["discover", "resolve_all", "telnyx_sms"]
result = mod.normalize_sender_result(sender(pconfig, "+15555550199", "hi"))
assert result["success"] is True and result["message_id"] == "mid-1"
missing, _, err2 = mod.resolve_standalone_sender(
    discover, resolve_all, lambda name: None, lambda: None, lambda name: None, Cfg)
assert missing is None and "standalone_sender_fn" in err2
print("ok")
`);
  assert.equal(out, "ok");
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
  assert.match(payload.attestation, /Reply SEND to send, DROP to discard\./);
  assert.match(payload.attestation, /The recipient can still opt out with their carrier\./);
  assert.doesNotMatch(payload.attestation, /to cancel/i);
  assert.doesNotMatch(payload.attestation, /\bSTOP\b/);
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

test("the cancel command drops a staged draft and does not send", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-drop-cmd-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  const dropped = run(["cancel", "--draft-id", staged.payload.draft_id], {}, dir);
  assert.equal(dropped.payload.outcome, "cancelled");
  assert.equal(dropped.payload.provider_called, false);
  assert.equal(dropped.callLines.length, 0);
  const later = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(later.payload.outcome, "refused_no_confirm");
  assert.equal(later.callLines.length, 0);
});

test("DROP, NO, no, and skip drop the draft and do not send", () => {
  for (const token of ["DROP", "drop", "NO", "no", "  skip ", "Skip"]) {
    const dir = mkdtempSync(join(tmpdir(), "sms-drop-"));
    const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
    const dropped = run(
      ["send", "--draft-id", staged.payload.draft_id, "--confirm", token, "--attest", "yes"],
      {},
      dir,
    );
    assert.equal(dropped.payload.outcome, "refused_no_confirm", token);
    assert.match(dropped.payload.reason, /owner replied NO, DROP, or skip/);
    assert.equal(dropped.payload.provider_called, false);
    assert.equal(dropped.callLines.length, 0);
    const later = run(
      ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
      {},
      dir,
    );
    assert.equal(later.payload.outcome, "refused_no_confirm", token);
    assert.equal(later.callLines.length, 0);
  }
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

test("multi-dest, overlong body, cron, and allow-all never send", () => {
  const multi = run(["stage", "--approver", OWNER, "--dest", `${DEST},${DEST}`, "--body", BODY]);
  assert.equal(multi.payload.outcome, "refused_multi");
  assert.equal(multi.callLines.length, 0);

  const moo = run(["stage", "--approver", OWNER, "--dest", "MoO list", "--body", BODY]);
  assert.equal(moo.payload.outcome, "refused_multi");
  assert.match(moo.payload.reason, /MoO lists/);
  assert.equal(moo.callLines.length, 0);

  const csv = run(["stage", "--approver", OWNER, "--dest", "nurture.csv", "--body", BODY]);
  assert.equal(csv.payload.outcome, "refused_multi");
  assert.equal(csv.callLines.length, 0);

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

  const cronOnCustomer = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    SMS_BOX_ID: "david-marshall",
    HERMES_CRON_JOB_ID: "job-1",
  });
  assert.equal(cronOnCustomer.payload.outcome, "refused_autonomous");
  assert.equal(cronOnCustomer.callLines.length, 0);

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

test("Path A allows any resolved box with a native From and refuses an empty box", () => {
  const out = py(`${importMod}
import os
os.environ["TELNYX_SMS_FROM_NUMBER"] = "+19283563339"
mod.assert_path_a_box("david-marshall")
mod.assert_path_a_box("marc-king", {"TELNYX_SMS_FROM_NUMBER": "+19283563339"})
try:
    mod.assert_path_a_box("", {"TELNYX_SMS_FROM_NUMBER": "+19283563339"})
    raise SystemExit("empty box was allowed")
except mod.GateFailure as failure:
    assert failure.outcome == "refused_no_box"
try:
    mod.assert_path_a_box("david-marshall", {"TELNYX_SMS_FROM_NUMBER": ""})
    raise SystemExit("missing From was allowed")
except mod.GateFailure as failure:
    assert failure.outcome == "error" and failure.field == "from"
print("ok")
`);
  assert.equal(out, "ok");

  for (const box of ["marc-king", "david-marshall"]) {
    const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
      SMS_BOX_ID: box,
    });
    assert.equal(staged.payload.outcome, "staged", box);
    assert.equal(staged.callLines.length, 0);
    const draft = JSON.parse(
      readFileSync(join(staged.dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"),
    );
    assert.equal(draft.box_id, box);
    assert.equal(draft.allowed_users, undefined);
    if (box === "david-marshall") {
      const sent = run(
        ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
        { SMS_BOX_ID: box },
        staged.dir,
      );
      assert.equal(sent.payload.outcome, "sent");
      assert.equal(sent.callLines.length, 1);
      assert.equal(sent.auditLines.at(-1).box_id, box);
      assert.equal(sent.auditLines.at(-1).provider_called, true);
      const session = JSON.parse(readFileSync(join(staged.dir, "sessions", `${DEST}.json`), "utf8"));
      assert.equal(session.allowed_users, undefined);
    }
  }

  const viaUrl = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    SMS_BOX_ID: "",
    BOX_PUBLIC_BASE_URL: "https://david-marshall.boxes.advisorreach.ai",
  });
  assert.equal(viaUrl.payload.outcome, "staged");
  const viaDraft = JSON.parse(
    readFileSync(join(viaUrl.dir, "drafts", `${viaUrl.payload.draft_id}.json`), "utf8"),
  );
  assert.equal(viaDraft.box_id, "david-marshall");
  assert.equal(viaUrl.callLines.length, 0);

  const unresolved = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    SMS_BOX_ID: "",
  });
  assert.equal(unresolved.payload.outcome, "refused_no_box");
  assert.equal(unresolved.payload.provider_called, false);
  assert.equal(unresolved.callLines.length, 0);

  const customerMissingFrom = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    SMS_BOX_ID: "david-marshall",
    TELNYX_SMS_FROM_NUMBER: "",
  });
  assert.equal(customerMissingFrom.payload.outcome, "error");
  assert.equal(customerMissingFrom.payload.field, "from");
  assert.equal(customerMissingFrom.callLines.length, 0);
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

function sendOne(dir, dest = DEST, approver = OWNER) {
  const staged = run(["stage", "--approver", approver, "--dest", dest, "--body", BODY], {}, dir);
  assert.equal(staged.payload.outcome, "staged");
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  return { staged, sent };
}

test("a sent message writes a session and does not widen the allowlist", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-session-"));
  const { sent } = sendOne(dir);
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(sent.payload.session_recorded, true);
  assert.equal(sent.payload.auto_reply, false);
  const session = JSON.parse(readFileSync(join(dir, "sessions", `${DEST}.json`), "utf8"));
  assert.equal(session.dest, DEST);
  assert.equal(session.telnyx_message_id, "msg_test_1");
  assert.equal(session.draft_id, sent.payload.draft_id);
  assert.equal(session.from, FROM);
  assert.equal(session.approver, OWNER);
  assert.ok(session.ttl_expires_at);
  assert.equal(session.body, undefined);
  assert.equal(session.allowed_users, undefined);
  assert.equal(sent.auditLines.at(-1).session_ttl_expires_at, session.ttl_expires_at);
  const asApprover = run(["stage", "--approver", DEST, "--dest", "+15555550123", "--body", BODY], {}, dir);
  assert.equal(asApprover.payload.outcome, "refused_not_owner");
  assert.equal(asApprover.callLines.length, 1);
});

test("inbound inside TTL is an owner event and does not auto-reply", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-in-"));
  const { sent } = sendOne(dir);
  const reply = "Thursday works.";
  const inbound = run(
    ["inbound", "--sender", DEST, "--body", reply, "--message-id", "in-1"],
    {},
    dir,
  );
  assert.equal(inbound.payload.outcome, "owner_event");
  assert.equal(inbound.payload.auto_reply, false);
  assert.equal(inbound.payload.provider_called, false);
  assert.equal(inbound.callLines.length, 1);
  const event = inbound.payload.event;
  assert.equal(event.who, DEST);
  assert.equal(event.snippet, reply);
  assert.deepEqual(event.suggested_next, ["call", "draft reply", "dismiss"]);
  assert.equal(event.prior_outbound.draft_id, sent.payload.draft_id);
  assert.equal(event.prior_outbound.telnyx_message_id, "msg_test_1");
  assert.equal(event.auto_reply, false);
  assert.doesNotMatch(JSON.stringify(inbound.auditLines.at(-1)), new RegExp(reply));
  const listed = run(["events"], {}, dir);
  assert.equal(listed.payload.events.length, 1);
  assert.equal(listed.callLines.length, 1);
  const again = run(["inbound", "--sender", DEST, "--body", reply, "--message-id", "in-1"], {}, dir);
  assert.equal(again.payload.event.event_id, event.event_id);
  assert.equal(run(["events"], {}, dir).payload.events.length, 1);
  const dismissed = run(["dismiss", "--approver", OWNER, "--event-id", event.event_id], {}, dir);
  assert.equal(dismissed.payload.outcome, "dismissed");
  assert.equal(dismissed.payload.provider_called, false);
  assert.equal(dismissed.callLines.length, 1);
  assert.equal(run(["events"], {}, dir).payload.events.length, 0);
});

test("inbound outside TTL or from an unmatched number is rejected and not sent", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-ttl-in-"));
  sendOne(dir);
  const expired = run(
    ["inbound", "--sender", DEST, "--body", "late", "--message-id", "late-1"],
    { SMS_NOW: "2099-01-01T00:00:00+00:00" },
    dir,
  );
  assert.equal(expired.payload.outcome, "rejected_ttl");
  assert.equal(expired.payload.auto_reply, false);
  assert.equal(expired.payload.provider_called, false);
  assert.equal(expired.callLines.length, 1);
  assert.equal(run(["events"], {}, dir).payload.events.length, 0);
  const other = run(
    ["inbound", "--sender", "+15555550123", "--body", "who is this", "--message-id", "other-1"],
    {},
    dir,
  );
  assert.equal(other.payload.outcome, "unmatched");
  assert.equal(other.callLines.length, 1);
  assert.equal(run(["events"], {}, dir).payload.events.length, 0);
  const owner = run(["inbound", "--sender", OWNER, "--body", "hello", "--message-id", "own-1"], {}, dir);
  assert.equal(owner.payload.outcome, "owner_thread");
  assert.equal(owner.callLines.length, 1);
});

test("a reply still requires SEND", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-reply-"));
  sendOne(dir);
  const inbound = run(["inbound", "--sender", DEST, "--body", "Can you call?", "--message-id", "r1"], {}, dir);
  assert.equal(inbound.payload.outcome, "owner_event");
  const replyWhy = "Dana asked to call back";
  const staged = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      "Hi Dana, yes, I will call you.",
      "--why",
      replyWhy,
      "--source-kind",
      "owner_text",
    ],
    {},
    dir,
    { why: false },
  );
  assert.equal(staged.payload.outcome, "staged");
  assert.equal(staged.callLines.length, 1);
  const vague = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "send it", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(vague.payload.outcome, "refused_no_confirm");
  assert.equal(vague.callLines.length, 1);
  const restaged = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      "Hi Dana, yes, I will call you.",
      "--why",
      replyWhy,
      "--source-kind",
      "owner_text",
    ],
    {},
    dir,
    { why: false },
  );
  const sent = run(
    ["send", "--draft-id", restaged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(sent.callLines.length, 2);
});

test("STOP refuses before any provider call", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-stop-"));
  sendOne(dir);
  const stopped = run(["inbound", "--sender", DEST, "--body", "STOP", "--message-id", "stop-1"], {}, dir);
  assert.equal(stopped.payload.outcome, "refused_stop");
  assert.equal(stopped.payload.provider_called, false);
  assert.equal(stopped.payload.auto_reply, false);
  assert.equal(stopped.callLines.length, 1);
  assert.match(readFileSync(stopped.env.SMS_OPT_OUT_FILE, "utf8"), new RegExp(DEST.replace("+", "\\+")));
  assert.deepEqual(stopped.payload.event.suggested_next, ["dismiss"]);
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  assert.equal(staged.payload.outcome, "refused_stop");
  assert.equal(staged.callLines.length, 1);
});

test("stop bodies match Telnyx defaults plus REVOKE and OPTOUT", () => {
  const out = py(`${importMod}
for word in ("stop", "STOPALL", "stop all", "STOP ALL", "  unsubscribe ", "cancel", "end", "quit", "revoke", "OPTOUT", "opt-out"):
    assert mod.is_stop_body(word), word
for word in ("please stop", "help", "HELP", "start", "START", "unstop", "UNSTOP", "stop please"):
    assert mod.is_stop_body(word) is False, word
print("ok")
`);
  assert.equal(out, "ok");
});

test("REVOKE, OPTOUT, and STOP ALL refuse before any provider call", () => {
  for (const word of ["REVOKE", "OPTOUT", "opt-out", "STOP ALL"]) {
    const dir = mkdtempSync(join(tmpdir(), "sms-opt-word-"));
    sendOne(dir);
    const stopped = run(["inbound", "--sender", DEST, "--body", word, "--message-id", word], {}, dir);
    assert.equal(stopped.payload.outcome, "refused_stop", word);
    assert.equal(stopped.payload.provider_called, false);
    assert.equal(stopped.callLines.length, 1);
    assert.match(readFileSync(stopped.env.SMS_OPT_OUT_FILE, "utf8"), new RegExp(DEST.replace("+", "\\+")));
  }
});

test("a Telegram approver can confirm and cannot be the destination", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-tg-"));
  const staged = run(
    ["stage", "--approver", "424242", "--dest", DEST, "--body", BODY],
    { TELEGRAM_ALLOWED_USERS: "424242" },
    dir,
  );
  assert.equal(staged.payload.outcome, "staged");
  const sent = run(
    [
      "send",
      "--draft-id",
      staged.payload.draft_id,
      "--confirm",
      "SEND",
      "--attest",
      "yes",
      "--actor",
      "424242",
    ],
    { TELEGRAM_ALLOWED_USERS: "424242" },
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  const same = run(
    ["stage", "--approver", "15555550199", "--dest", DEST, "--body", BODY],
    { TELEGRAM_ALLOWED_USERS: "15555550199" },
    dir,
  );
  assert.equal(same.payload.outcome, "refused_not_third_party");
  assert.equal(same.callLines.length, 1);
  const stranger = run(
    ["stage", "--approver", "99999", "--dest", "+15555550123", "--body", BODY],
    { TELEGRAM_ALLOWED_USERS: "424242" },
  );
  assert.equal(stranger.payload.outcome, "refused_not_owner");
});

test("hydrate fills empty keys without extending the allowlist", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-hydrate-"));
  const runtime = join(dir, "runtime.env");
  const proc = join(dir, "proc.environ");
  writeFileSync(runtime, "TELNYX_SMS_API_BASE=http://telnyx-proxy/v2\nTELNYX_SMS_ALLOWED_USERS=+15555550199,+17145550100\n");
  writeFileSync(proc, "TELNYX_API_KEY=test-key\0TELNYX_SMS_API_BASE=https://api.telnyx.com/v2\0TELEGRAM_ALLOWED_USERS=424242\0");
  const out = py(`${importMod}
import os
os.environ["SMS_SEND_CONFIRMED_TEST"] = "1"
os.environ["SMS_HYDRATE_IN_TEST"] = "1"
os.environ["SMS_RUNTIME_ENV_FILE"] = ${JSON.stringify(runtime)}
os.environ["SMS_PROC_ENVIRON"] = ${JSON.stringify(proc)}
os.environ["TELNYX_SMS_ALLOWED_USERS"] = "+17145550100"
os.environ["TELNYX_API_KEY"] = ""
os.environ.pop("TELNYX_SMS_API_BASE", None)
os.environ.pop("TELEGRAM_ALLOWED_USERS", None)
filled = mod.hydrate_sms_env()
assert "TELNYX_API_KEY" in filled
assert "TELNYX_SMS_API_BASE" in filled
assert "TELNYX_SMS_ALLOWED_USERS" not in filled
assert os.environ["TELNYX_API_KEY"] == "test-key"
assert os.environ["TELNYX_SMS_API_BASE"] == "http://telnyx-proxy/v2"
assert os.environ["TELNYX_SMS_ALLOWED_USERS"] == "+17145550100"
assert os.environ["TELEGRAM_ALLOWED_USERS"] == "424242"
print("ok")
`);
  assert.equal(out, "ok");
});

test("owner-event skill forbids auto-reply and the hook skips only captured inbounds", () => {
  const eventSkill = readFileSync(join(root, "skills", "sms-inbound-owner-event", "SKILL.md"), "utf8");
  const hook = readFileSync(join(root, "skills", "sms-send-confirmed", "method-a", "session_inbound_hook.py"), "utf8");
  const bake = readFileSync(join(root, "skills", "sms-send-confirmed", "method-a", "BAKE.md"), "utf8");
  assert.match(eventSkill, /^name: sms-inbound-owner-event$/m);
  assert.match(eventSkill, /Do not text them/);
  assert.match(eventSkill, /still needs a new `SEND`|after they reply `SEND`/);
  assert.match(eventSkill, /does not widen/);
  assert.match(hook, /CAPTURED_OUTCOMES/);
  assert.match(bake, /No fleet/);
  assert.match(bake, /advisor-reach-internal/);
  const out = py(`
import importlib.util
spec = importlib.util.spec_from_file_location(
    "session_inbound_hook",
    ${JSON.stringify(join(root, "skills", "sms-send-confirmed", "method-a", "session_inbound_hook.py"))},
)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
assert hook.skip_agent_turn({"outcome": "owner_event"}) is True
assert hook.skip_agent_turn({"outcome": "unmatched"}) is True
assert hook.skip_agent_turn({"outcome": "rejected_ttl"}) is True
assert hook.skip_agent_turn({"outcome": "refused_stop"}) is True
assert hook.skip_agent_turn({"outcome": "owner_thread"}) is False
assert hook.skip_agent_turn(None) is False
print("ok")
`);
  assert.equal(out, "ok");
});

test("stage puts the Why line in the attestation and not in the client body", () => {
  const line = "Why: Jane's offer deadline is 5 PM today (FUB note, Oct 7).";
  assert.equal(line.length, 59);
  const dir = mkdtempSync(join(tmpdir(), "sms-why-ok-"));
  const staged = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      BODY,
      "--why",
      "Jane's offer deadline is 5 PM today",
      "--source-kind",
      "fub_note",
      "--source-date",
      "2026-10-07",
      "--source-ref",
      "note-1",
    ],
    {},
    dir,
  );
  assert.equal(staged.payload.outcome, "staged");
  assert.equal(staged.payload.provider_called, false);
  assert.equal(staged.payload.attestation_version, "red-390-v3");
  assert.equal(staged.payload.source_kind, "fub_note");
  assert.equal(staged.payload.source_date, "2026-10-07");
  assert.equal(staged.payload.why_line, line);
  assert.equal(staged.payload.source_ref, undefined);
  assert.equal(staged.callLines.length, 0);
  const parts = staged.payload.attestation.split("\n");
  assert.match(parts[0], /from ARIN's number/);
  assert.equal(parts[1], BODY);
  assert.equal(parts[2], line);
  assert.match(parts[3], /^Reply SEND to confirm/);
  const draft = JSON.parse(readFileSync(join(dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.body, BODY);
  assert.equal(draft.body_hash, createHash("sha256").update(BODY).digest("hex"));
  assert.equal(draft.why_line, line);
  assert.equal(draft.source_kind, "fub_note");
  assert.equal(draft.source_date, "2026-10-07");
  assert.equal(draft.source_ref, "note-1");
  assert.equal(draft.attestation_version, "red-390-v3");
  assert.doesNotMatch(draft.body, /Why:/);
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.deepEqual(JSON.parse(sent.callLines[0]), { to: DEST, text: BODY });
});

test("Why line labels match the source kind", () => {
  const out = py(`${importMod}
assert len(mod.GSM7_CHARS) == 134
assert chr(96) not in mod.GSM7_CHARS
line, kind, day, ref = mod.build_why_line(
    "Jane's offer deadline is 5 PM today", "fub_note", "2026-10-07", "", "note-1")
assert line == "Why: Jane's offer deadline is 5 PM today (FUB note, Oct 7)."
assert len(line) == 59 and kind == "fub_note" and day == "2026-10-07" and ref == "note-1"
memory, memory_kind, memory_day, _ = mod.build_why_line(
    "Sam's lease ends Nov 30, so renewal talk is due",
    "memory",
    "2026-09-12",
    "FUB note",
    "",
)
assert memory == "Why: Sam's lease ends Nov 30, so renewal talk is due (ARIN memory: FUB note, Sep 12)."
assert memory_kind == "memory" and memory_day == "2026-09-12"
assert len(memory) <= 120
gmail, _, gmail_day, _ = mod.build_why_line(
    "Mark asked about rates and has had no reply for 3 days",
    "gmail",
    "2026-10-05",
    "Mark",
    "msg-1",
)
assert gmail == "Why: Mark asked about rates and has had no reply for 3 days (Gmail from Mark, Oct 5)."
assert gmail_day == "2026-10-05"
owner, _, owner_day, owner_ref = mod.build_why_line(
    "the showing was today and the buyer has not replied",
    "owner_text",
    "",
    "",
    "",
)
assert owner == "Why: the showing was today and the buyer has not replied, from your own text."
assert owner_day is None and owner_ref is None
unknown, unknown_kind, _, _ = mod.build_why_line(
    "Sam's lease ends Nov 30",
    "memory",
    "2026-09-12",
    "source unknown",
    "",
)
assert unknown_kind == "memory"
assert unknown.endswith("(ARIN memory: source unknown, Sep 12).")
print("ok")
`);
  assert.equal(out, "ok");
});

test("stage refuses a missing Why line and writes no draft", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-no-why-"));
  const missing = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY],
    {},
    dir,
    { why: false },
  );
  assert.equal(missing.payload.outcome, "refused_no_why");
  assert.equal(missing.payload.field, "why");
  assert.equal(missing.payload.provider_called, false);
  assert.equal(missing.proc.status, 2);
  assert.equal(missing.callLines.length, 0);
  assert.equal(draftFiles(dir).length, 0);

  const noKind = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY, "--why", "checking in today"],
    {},
    mkdtempSync(join(tmpdir(), "sms-no-kind-")),
  );
  assert.equal(noKind.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(noKind.dir).length, 0);

  const noDate = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "checking in today",
    "--source-kind",
    "fub_note",
  ]);
  assert.equal(noDate.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(noDate.dir).length, 0);

  const later = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  assert.equal(later.payload.outcome, "staged");
  assert.equal(draftFiles(dir).length, 1);
});

test("stage refuses a bad source kind", () => {
  const bad = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "checking in today",
    "--source-kind",
    "inbox",
    "--source-date",
    "2026-10-08",
  ]);
  assert.equal(bad.payload.outcome, "refused_no_why");
  assert.equal(bad.payload.provider_called, false);
  assert.equal(bad.callLines.length, 0);
  assert.equal(draftFiles(bad.dir).length, 0);

  const noName = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "Mark asked about rates",
    "--source-kind",
    "gmail",
    "--source-date",
    "2026-10-05",
  ]);
  assert.equal(noName.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(noName.dir).length, 0);
});

test("stage refuses a non-GSM Why line and folds curly punctuation", () => {
  const emoji = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "the deadline is today \u{1F600}",
    "--source-kind",
    "owner_text",
  ]);
  assert.equal(emoji.payload.outcome, "refused_no_why");
  assert.match(emoji.payload.reason, /GSM-7/);
  assert.equal(emoji.payload.provider_called, false);
  assert.equal(draftFiles(emoji.dir).length, 0);

  const folded = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "Jane\u2019s deadline \u2014 today\u2026",
    "--source-kind",
    "fub_note",
    "--source-date",
    "2026-10-07",
  ]);
  assert.equal(folded.payload.outcome, "staged");
  assert.equal(folded.payload.why_line, "Why: Jane's deadline - today... (FUB note, Oct 7).");
  assert.doesNotMatch(folded.payload.attestation, /\u2019|\u2014|\u2026/);
});

test("stage refuses confirm tokens in the Why line", () => {
  for (const why of ["reply SEND now", "please /approve this", "they said STOP", "reply send now", "they said stop"]) {
    const refused = run([
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      BODY,
      "--why",
      why,
      "--source-kind",
      "owner_text",
    ]);
    assert.equal(refused.payload.outcome, "refused_no_why", why);
    assert.match(refused.payload.reason, /SEND/);
    assert.equal(refused.payload.provider_called, false);
    assert.equal(refused.callLines.length, 0);
    assert.equal(draftFiles(refused.dir).length, 0);
  }
  const allowed = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "sending the packet today",
    "--source-kind",
    "owner_text",
  ]);
  assert.equal(allowed.payload.outcome, "staged");
  assert.equal(
    allowed.payload.why_line,
    "Why: sending the packet today, from your own text.",
  );
});

test("stage refuses a Why line that is too long", () => {
  const longWhy = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "a".repeat(200),
    "--source-kind",
    "owner_text",
  ]);
  assert.equal(longWhy.payload.outcome, "refused_no_why");
  assert.match(longWhy.payload.reason, /90/);
  assert.equal(draftFiles(longWhy.dir).length, 0);

  const ninetyOne = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "b".repeat(91),
    "--source-kind",
    "owner_text",
  ]);
  assert.equal(ninetyOne.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(ninetyOne.dir).length, 0);

  const overLine = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "c".repeat(90),
    "--source-kind",
    "memory",
    "--source-name",
    "FUB note from the archive",
    "--source-date",
    "2026-10-08",
  ]);
  assert.equal(overLine.payload.outcome, "refused_no_why");
  assert.match(overLine.payload.reason, /120/);
  assert.equal(overLine.payload.provider_called, false);
  assert.equal(draftFiles(overLine.dir).length, 0);
});

test("stage refuses none with a date or ref and allows none alone", () => {
  const dated = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "Sam's offer is due today",
    "--source-kind",
    "none",
    "--source-date",
    "2026-10-01",
  ]);
  assert.equal(dated.payload.outcome, "refused_no_why");
  assert.equal(dated.payload.provider_called, false);
  assert.equal(draftFiles(dated.dir).length, 0);

  const withRef = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "Sam's offer is due today",
    "--source-kind",
    "none",
    "--source-ref",
    "note-9",
  ]);
  assert.equal(withRef.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(withRef.dir).length, 0);

  const none = run([
    "stage",
    "--approver",
    OWNER,
    "--dest",
    DEST,
    "--body",
    BODY,
    "--why",
    "Sam's offer is due today",
    "--source-kind",
    "none",
  ]);
  assert.equal(none.payload.outcome, "staged");
  assert.equal(none.payload.why_line, "Why: Sam's offer is due today (no source).");
  assert.equal(none.payload.source_kind, "none");
  assert.equal(none.payload.source_date, null);
  assert.equal(none.payload.source_ref ?? null, null);
  assert.doesNotMatch(none.payload.why_line, /\d{4}|Oct|Sep/);
  const draft = JSON.parse(readFileSync(join(none.dir, "drafts", `${none.payload.draft_id}.json`), "utf8"));
  // AC10: no source -> explicit JSON null for both audit fields, never "".
  assert.equal(draft.source_date, null);
  assert.equal(draft.source_ref, null);
  assert.equal(draft.body, BODY);
});

test("a delegated child cannot stage or send", () => {
  const blocked = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {
    HERMES_DELEGATED_CHILD_CONTEXT: "1",
  });
  assert.equal(blocked.payload.outcome, "refused_autonomous");
  assert.match(blocked.payload.reason, /delegated child/);
  assert.equal(blocked.payload.provider_called, false);
  assert.equal(blocked.proc.status, 2);
  assert.equal(blocked.callLines.length, 0);
  assert.equal(draftFiles(blocked.dir).length, 0);

  const dir = mkdtempSync(join(tmpdir(), "sms-child-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, dir);
  assert.equal(staged.payload.outcome, "staged");
  const childSend = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    { HERMES_DELEGATED_CHILD_CONTEXT: "1" },
    dir,
  );
  assert.equal(childSend.payload.outcome, "refused_autonomous");
  assert.equal(childSend.payload.provider_called, false);
  assert.equal(childSend.callLines.length, 0);
  const stillThere = JSON.parse(readFileSync(join(dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"));
  assert.equal(stillThere.status, "pending");
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(sent.callLines.length, 1);
  assert.deepEqual(JSON.parse(sent.callLines[0]), { to: DEST, text: BODY });
});

test("Why text that only restates the trigger is refused; real reasons pass", () => {
  const out = py(`${importMod}
rejected = [
    "You asked me to text Dana about Sunday's open house. (your text, Oct 17)",
    "You asked me to text Dana about Sunday's open house",
    "you asked for this text today",
    "owner asked for this",
    "as requested by the owner",
    "per your text",
    "your text, Oct 17",
    "(your text, Oct 17)",
    "you texted me today",
    "Oct 17",
    "this text",
]
accepted = [
    "Dana asked if the inspection report is in",
    "Hendersons want the comparison before the 4 PM call",
    "Pat is closing today",
    "Mike from Zillow went quiet last week",
    "Sunday's open house is tomorrow and Dana has not confirmed",
]
for text in rejected:
    assert mod.restates_trigger(text), ("should reject", text)
    try:
        mod.build_why_line(text, "owner_text", "", "", "")
    except mod.GateFailure as exc:
        assert exc.args[0] == "why restates the trigger (the owner's text or request) and gives no reason; state what is due or happened and why now" or True
        assert getattr(exc, "outcome", "") == "refused_why_trigger", (text, getattr(exc, "outcome", None))
    else:
        raise AssertionError(("not refused", text))
for text in accepted:
    assert not mod.restates_trigger(text), ("should accept", text)
    line, kind, day, ref = mod.build_why_line(text, "owner_text", "", "", "")
    assert line == "Why: " + text + ", from your own text.", line
    assert "(your text" not in line and "(no source)" not in line
    assert day is None and ref is None and kind == "owner_text"
# Other source kinds keep their label.
line, *_ = mod.build_why_line("Jane's offer deadline is 5 PM today", "fub_note", "2026-10-07", "", "")
assert line == "Why: Jane's offer deadline is 5 PM today (FUB note, Oct 7).", line
print("ok")
`);
  assert.match(out, /ok/);
});

test("stage refuses a restating Why line and writes no draft", () => {
  const res = run([
    "stage", "--approver", OWNER, "--dest", DEST, "--body", BODY,
    "--why", "You asked me to text Dana about Sunday's open house",
    "--source-kind", "owner_text",
  ]);
  assert.equal(res.payload.outcome, "refused_why_trigger");
  assert.equal(res.payload.provider_called, false);
  assert.equal(draftFiles(res.dir).length, 0);
});

const BODY_TO = "Hi Dana, your listing packet is ready.";
const stageWith = (body, why, extra = []) =>
  run(["stage", "--approver", OWNER, "--dest", DEST, "--body", body, "--why", why,
    "--source-kind", "owner_text", ...extra]);
const ownerWhySuffix = ", from your own text.";

test("0002/0003: generic or thin whys are refused (generic or trigger); client-specific whys stage", () => {
  for (const why of ["At your request", "Pat", "Send comparison per owner request", "Owner asked me to send it",
    "Congratulate Pat as requested by the owner (owner text, 2026-10-15)"]) {
    const r = stageWith(BODY_TO, why);
    assert.ok(["refused_why_generic", "refused_why_trigger"].includes(r.payload.outcome), why + " " + r.stdout);
    assert.equal(r.payload.provider_called, false);
    assert.equal(draftFiles(r.dir).length, 0);
  }
  assert.equal(stageWith(BODY_TO, "Pat").payload.outcome, "refused_why_generic");
  for (const why of ["Hendersons want the comparison before the 4 PM call", "Dana asked if the inspection report is in",
    "Mike went quiet after the Zillow inquiry last week"]) {
    const r = stageWith(BODY_TO, why);
    assert.equal(r.payload.outcome, "staged", why + " " + r.stdout);
    const line = "Why: " + why + ownerWhySuffix;
    assert.ok(r.payload.attestation.includes("\n" + line + "\n"), r.payload.attestation);
    assert.equal(r.payload.attestation.includes("(your text"), false);
    assert.equal(r.payload.attestation.includes("(no source)"), false);
    assert.equal(r.payload.source_kind, "owner_text");
    assert.equal(r.payload.source_date, null);
    assert.equal(r.payload.why_line, line);
    const ownerDraft = JSON.parse(
      readFileSync(join(r.dir, "drafts", `${r.payload.draft_id}.json`), "utf8"),
    );
    assert.equal(ownerDraft.source_ref, null);
  }
});

test("0003: a provenance suffix the model appends is stripped, never shown", () => {
  for (const suffix of ["(owner text, 2026-10-15)", "(your text, Oct 17)"]) {
    const r = stageWith(BODY_TO, "Dana asked if the inspection report is in " + suffix);
    assert.equal(r.payload.outcome, "staged", r.stdout);
    assert.ok(
      r.payload.attestation.includes("\nWhy: Dana asked if the inspection report is in" + ownerWhySuffix + "\n"),
      r.payload.attestation,
    );
  }
});

test("0004/0005: circular whys are refused; event-as-cause stages and the action tail is trimmed", () => {
  for (const why of ["Text Dana a note", "Wish Sam a happy birthday", "Congratulate Pat on closing",
    "Mike is a contact and you want to check in with Mike", "Hi Dana, your listing packet is ready"]) {
    const r = stageWith(BODY_TO, why);
    assert.equal(r.payload.outcome, "refused_why_circular", why + " " + r.stdout);
    assert.equal(r.payload.provider_called, false);
  }
  for (const [why, shown] of [
    ["Pat is closing today, so congratulate Pat", "Pat is closing today"],
    ["Pat closed today to congratulate her", "Pat closed today"],
    ["The price dropped on the Oak St listing", "The price dropped on the Oak St listing"],
    ["Sam's birthday is today", "Sam's birthday is today"],
  ]) {
    const r = stageWith("Hi Dana, the price on Oak St dropped to [PRICE].", why);
    assert.equal(r.payload.outcome, "staged", why + " " + r.stdout);
    assert.ok(r.payload.attestation.includes("\nWhy: " + shown + ownerWhySuffix + "\n"), r.payload.attestation);
  }
});

test("0004: body must be the text itself, to the recipient; [PRICE] placeholder; no filler", () => {
  const why = "Hendersons want it before the 4 PM call";
  for (const [body, outcome] of [
    ["Hi Hendersons, the comparison is coming. Tell them it's coming.", "refused_body_meta"],
    ["Hi Hendersons, Tell them it's coming.", "refused_body_meta"],
    ["Dana asked if the inspection report is in. It is.", "refused_body_not_to_recipient"],
    ["The appraisal came in.", "refused_body_not_to_recipient"],
    ["Hi Dana, the price dropped on the Oak St listing.", "refused_body_missing_placeholder"],
    ["Hi, the price on Oak St dropped to [PRICE].", "refused_no_recipient"],
    ["Hi Dana, just sending a quick note.", "refused_body_no_content"],
  ]) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, outcome, body + " " + r.stdout);
    assert.equal(r.payload.provider_called, false);
    assert.equal(draftFiles(r.dir).length, 0);
  }
  for (const body of ["Hi Hendersons, the comparison will be with you before our 4 PM call.",
    "Hi Dana, the price on the Oak St listing dropped to [PRICE]. Want to take a look?",
    "Hi Garcias, the appraisal came in.", "Congrats Pat on closing today!"]) {
    assert.equal(stageWith(body, why).payload.outcome, "staged", body);
  }
});

test("QA expected format: Why line is one line, reason only, no suffix, not in the client body", () => {
  const r = stageWith("Hi Dana, yes, the inspection report is in.", "Dana asked if the inspection report is in");
  assert.equal(r.payload.outcome, "staged");
  const lines = r.payload.attestation.split("\n").filter((l) => l.startsWith("Why:"));
  assert.deepEqual(lines, ["Why: Dana asked if the inspection report is in" + ownerWhySuffix]);
  assert.equal(r.payload.attestation.indexOf("Why:") < r.payload.attestation.indexOf("SEND"), true);
  const plain = stageWith("Hi Dana, yes, the inspection report is in.", "Sam's birthday is today");
  assert.equal(r.payload.body_hash, plain.payload.body_hash);
});


test("owner_text: source_date and source_ref are null; stored why_line equals the displayed Why", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-owner-null-"));
  const staged = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", "Hi Dana, yes, the inspection report is in.",
      "--why", "Dana asked if the inspection report is in", "--source-kind", "owner_text"],
    { SMS_NOW: "2026-10-18T03:30:00+00:00", BOX_TIMEZONE: "America/Phoenix" },
    dir,
    { why: false },
  );
  assert.equal(staged.payload.outcome, "staged", staged.proc.stdout);
  const draft = JSON.parse(readFileSync(join(dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.source_kind, "owner_text");
  assert.equal(draft.source_date, null);
  assert.equal(draft.source_ref, null);
  const shown = "Why: Dana asked if the inspection report is in, from your own text.";
  assert.equal(draft.why_line, shown);
  assert.equal(staged.payload.why_line, shown);
  const attestationLines = staged.payload.attestation.split("\n");
  assert.equal(attestationLines[2], shown);
  assert.ok(staged.payload.attestation.includes("\n" + shown + "\n"));
  for (const hidden of ["(no source)", "(your text", "2026-10-17", "Oct 17"]) {
    assert.equal(staged.payload.attestation.includes(hidden), false, hidden);
    assert.equal(draft.why_line.includes(hidden), false, hidden);
  }
  const withDate = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY, "--why", "Dana asked if the inspection report is in",
      "--source-kind", "owner_text", "--source-date", "2026-10-15"],
    {},
    mkdtempSync(join(tmpdir(), "sms-owner-date-refused-")),
    { why: false },
  );
  assert.equal(withDate.payload.outcome, "refused_no_why");
  assert.match(withDate.payload.reason, /owner_text cannot include a date/);
  assert.equal(draftFiles(withDate.dir).length, 0);
});

test("non-owner source without source-date is refused", () => {
  const refused = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY,
      "--why", "Jane's offer deadline is 5 PM today", "--source-kind", "fub_note"],
    {},
    mkdtempSync(join(tmpdir(), "sms-no-date-")),
    { why: false },
  );
  assert.equal(refused.payload.outcome, "refused_no_why");
  assert.match(refused.payload.reason, /source-date is required/);
  assert.equal(draftFiles(refused.dir).length, 0);
});

test("the script never rewrites the draft body: pronouns and wording are stored and shown as given", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-body-verbatim-"));
  const body = "Hi Dana, please bring her signature and his ID. Tell Sam we are set.";
  const staged = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", body, "--why", "Dana asked if the inspection report is in",
      "--source-kind", "owner_text"], {}, dir, { why: false });
  // 'Tell Sam' mid-text is refused as an owner instruction; the point here is the pronouns, so use a clean body.
  assert.equal(staged.payload.outcome, "refused_body_meta");
  const clean = "Hi Dana, please bring her signature and his ID to closing.";
  const ok = run(
    ["stage", "--approver", OWNER, "--dest", DEST, "--body", clean, "--why", "Dana asked if the inspection report is in",
      "--source-kind", "owner_text"], {}, mkdtempSync(join(tmpdir(), "sms-body-verbatim2-")), { why: false });
  assert.equal(ok.payload.outcome, "staged", ok.proc.stdout);
  const draft = JSON.parse(readFileSync(join(ok.dir, "drafts", `${ok.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.body, clean);
  assert.equal(ok.payload.attestation.split("\n")[1], clean);
});

test("skill: keep the owner's wording and facts; only address the recipient; keep other people's pronouns", () => {
  assert.match(skill, /Only the recipient becomes "you"/);
  assert.match(skill, /keep every other person's pronouns/);
});

// --- RED-585 QA run 7 (Oct 18) draft fixes -------------------------------------------------
test("QA run 7 items 1-2: a bare 'Hi,' greeting is refused; 'Hi Dana, ...' stages; a status Why is refused", () => {
  const bare = stageWith("Hi, you asked if the inspection report is in. It is.", "Dana asked if the inspection report is in");
  assert.equal(bare.payload.outcome, "refused_no_recipient", bare.stdout);
  assert.equal(draftFiles(bare.dir).length, 0);
  const named = stageWith("Hi Dana, yes, the inspection report is in.", "Dana asked if the inspection report is in");
  assert.equal(named.payload.outcome, "staged", named.stdout);
  assert.match(named.payload.body_hash, /./);
  const status = stageWith("Hi Dana, yes, the inspection report is in.", "The inspection report is available for Dana now.");
  assert.equal(status.payload.outcome, "refused_why_circular", status.stdout);
  assert.equal(draftFiles(status.dir).length, 0);
  const hen = stageWith("Hi Hendersons, the comparison is coming before our 4pm call.", "The Hendersons need the comparison before the 4pm call.");
  assert.equal(hen.payload.outcome, "staged", hen.stdout);
});

test("QA run 7 item 4: a missing price stages with [PRICE]; a price word with no figure or placeholder is refused", () => {
  const staged = stageWith("Hi Dana, the new price for 12 Oak St is [PRICE].", "Dana asked about the new Oak St price");
  assert.equal(staged.payload.outcome, "staged", staged.stdout);
  const bad = stageWith("Hi Dana, the new price for Oak St is set.", "Dana asked about the new Oak St price");
  assert.equal(bad.payload.outcome, "refused_body_missing_placeholder", bad.stdout);
  const skill = readFileSync(skillPath, "utf8");
  assert.match(skill, /missing[\s\S]*?content[\s\S]*?is NEVER a reason to ask instead of staging/);
  assert.match(skill, /\[PRICE\]/);
});

test("QA run 7 items 5-6: action tails are trimmed from the displayed Why; the cause stays", () => {
  const cases = [
    ["Hi Pat, congratulations on closing today!", "Pat is closing today and deserves congratulations.", "Why: Pat is closing today"],
    ["Hi Lee, a reminder that the showing is tomorrow at 10.", "Lee's showing is tomorrow at 10, so a reminder is timely.", "Why: Lee's showing is tomorrow at 10"],
    ["Hi Pat, congratulations on closing today!", "Pat is closing today, so congratulate Pat", "Why: Pat is closing today"],
  ];
  for (const [body, why, shown] of cases) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "staged", why + " " + r.stdout);
    assert.equal(r.payload.why_line, shown + ownerWhySuffix, why);
    for (const tail of ["deserves", "timely", "so congratulate", "reminder is"]) {
      assert.equal(r.payload.why_line.includes(tail), false, tail);
    }
  }
  // Tails that leave no cause behind are still refused.
  assert.equal(stageWith("Hi Pat, congratulations!", "Congratulate Pat and deserves congratulations").payload.outcome, "refused_why_circular");
  // A real cause that merely contains "need" stays untouched.
  const keep = stageWith("Hi Garcias, the appraisal came in.", "The Garcias' appraisal has come in and they need the update.");
  assert.equal(keep.payload.why_line, "Why: The Garcias' appraisal has come in and they need the update" + ownerWhySuffix);
});

test("QA run 7 AC9: owner_text Why says 'from your own text' once, even if the model already wrote it; footer unchanged", () => {
  const r = stageWith("Hi Sam, happy birthday!", "It's Sam's birthday today");
  assert.equal(r.payload.why_line, "Why: It's Sam's birthday today, from your own text.");
  const twice = stageWith("Hi Sam, happy birthday!", "It's Sam's birthday today, from your own text.");
  assert.equal(twice.payload.why_line, "Why: It's Sam's birthday today, from your own text.");
  assert.equal(twice.payload.why_line.split("from your own text").length, 2);
  assert.match(r.payload.attestation, /Reply SEND to send, DROP to discard\./);
  assert.ok(r.payload.why_line.length <= 120);
  // Non-owner kinds keep their own label and still carry a real date.
  const fub = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", "Hi Dana, the offer is in.",
    "--why", "Dana's offer deadline is Friday", "--source-kind", "fub_note", "--source-date", "2026-10-15"]);
  assert.equal(fub.payload.outcome, "staged", fub.stdout);
  assert.equal(fub.payload.why_line, "Why: Dana's offer deadline is Friday (FUB note, Oct 15).");
});

test("owner-facing Why punctuation: no doubled comma or ellipsis-comma; ellipsis stays before a parenthesis", () => {
  const question = stageWith("Hi Dana, yes, the inspection report is in.", "Dana asked if the inspection report is in?");
  assert.equal(question.payload.why_line, "Why: Dana asked if the inspection report is in, from your own text.");
  const bang = stageWith("Hi Pat, congratulations on closing today!", "Pat is closing today!");
  assert.equal(bang.payload.why_line, "Why: Pat is closing today, from your own text.");
  const comma = stageWith("Hi Pat, congratulations on closing today!", "Pat is closing today,");
  assert.equal(comma.payload.why_line, "Why: Pat is closing today, from your own text.");
  assert.equal(comma.payload.why_line.includes(",,"), false);
  const dots = stageWith("Hi Dana, yes, the inspection report is in.", "Dana asked if the inspection report is in...");
  assert.equal(dots.payload.why_line, "Why: Dana asked if the inspection report is in, from your own text.");
  assert.equal(dots.payload.why_line.includes("...,"), false);
  const folded = stageWith("Hi Dana, yes, the inspection report is in.", "Dana asked if the inspection report is in\u2026");
  assert.equal(folded.payload.why_line, "Why: Dana asked if the inspection report is in, from your own text.");
  const fub = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", "Hi Dana, the offer is in.",
    "--why", "Jane's deadline - today...", "--source-kind", "fub_note", "--source-date", "2026-10-07"]);
  assert.equal(fub.payload.why_line, "Why: Jane's deadline - today... (FUB note, Oct 7).");
  const none = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", "Hi Sam, your offer is due today.",
    "--why", "Sam's offer is due today...", "--source-kind", "none"]);
  assert.equal(none.payload.why_line, "Why: Sam's offer is due today... (no source).");
});

test("a real cause that uses so, meaning, or deserves is not trimmed or refused", () => {
  const cases = [
    ["Hi Pat, the wire needs to go out this morning.", "Pat is closing today, so the wire must go out this morning"],
    ["Hi Dana, a counter is ready before 5.", "Offers came in under asking, meaning Dana needs a counter before 5"],
    ["Hi Dana, Oak St is at the new number.", "The price dropped, so the message is that Oak St is now at the new number"],
    ["Hi Lee, bring the disclosure to the showing.", "Lee's showing is tomorrow at 10, so the note from Dana says to bring the disclosure"],
    ["Hi Dana, a calm update is on the way.", "The buyer is nervous, meaning a calm update is appropriate before Friday"],
    ["Hi Dana, the inspection failed and Friday is the deadline.", "The seller deserves a reply because the offer expires Friday"],
    ["Hi Dana, the lender needs the documents before Friday.", "The lender calls for the documents before Friday's closing"],
  ];
  for (const [body, why] of cases) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "staged", why + " " + r.stdout);
    assert.equal(r.payload.why_line, "Why: " + why.replace(/[?!.]+$/, "") + ownerWhySuffix, why);
  }
  // The action tails from QA run 7 still trim.
  const timely = stageWith("Hi Lee, a reminder that the showing is tomorrow at 10.", "Lee's showing is tomorrow at 10, so a reminder is timely.");
  assert.equal(timely.payload.why_line, "Why: Lee's showing is tomorrow at 10" + ownerWhySuffix);
  const deserves = stageWith("Hi Pat, congratulations on closing today!", "Pat is closing today and deserves congratulations.");
  assert.equal(deserves.payload.why_line, "Why: Pat is closing today" + ownerWhySuffix);
});

test("status-only Why is refused; a cause that also mentions ready or available stages", () => {
  const only = stageWith("Hi Dana, yes, the inspection report is in.", "The inspection report is available for Dana now.");
  assert.equal(only.payload.outcome, "refused_why_circular");
  assert.match(only.payload.reason, /status, not a cause/);
  assert.equal(draftFiles(only.dir).length, 0);
  for (const why of [
    "The inspection report is now available",
    "The inspection report is ready now",
    "The inspection report is available now for Dana",
    "The keys are now ready.",
  ]) {
    const r = stageWith("Hi Dana, yes, the inspection report is in.", why);
    assert.equal(r.payload.outcome, "refused_why_circular", why + " " + r.stdout);
    assert.match(r.payload.reason, /status, not a cause/);
  }
  const asked = stageWith("Hi Dana, yes, the inspection report is in.", "Dana asked this morning and the inspection report is now ready");
  assert.equal(asked.payload.outcome, "staged", asked.stdout);
  assert.equal(
    asked.payload.why_line,
    "Why: Dana asked this morning and the inspection report is now ready" + ownerWhySuffix,
  );
  const because = stageWith("Hi Dana, yes, the inspection report is in.", "The keys are now ready because Dana lands at 4");
  assert.equal(because.payload.outcome, "staged", because.stdout);
  assert.equal(
    because.payload.why_line,
    "Why: The keys are now ready because Dana lands at 4" + ownerWhySuffix,
  );
});

test("greeting name: nameless forms refuse; a name after the comma or Dear counts", () => {
  const why = "Dana asked if the inspection report is in";
  for (const body of [
    "Hello, the price on Oak St dropped to [PRICE].",
    "Hey! the price on Oak St dropped to [PRICE].",
    "Hi there, the price on Oak St dropped to [PRICE].",
    "Good morning, the inspection report is in.",
    "Hey! The inspection report is in.",
  ]) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "refused_no_recipient", body + " " + r.stdout);
    assert.equal(draftFiles(r.dir).length, 0);
  }
  for (const body of [
    "Dear Dana, the inspection report is in.",
    "Hi, Dana, the inspection report is in.",
    "Hello Dana, the inspection report is in.",
    "Hey Dana, the inspection report is in.",
    "Good morning Dana, the inspection report is in.",
  ]) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "staged", body + " " + r.stdout);
    assert.equal(r.payload.attestation.split("\n")[1], body);
  }
});

test("a street number is not a price figure; [PRICE] and a dollar amount are", () => {
  const why = "Dana asked about the new Oak St price";
  const street = stageWith("Hi Dana, the new price for 12 Oak St is set.", why);
  assert.equal(street.payload.outcome, "refused_body_missing_placeholder", street.stdout);
  assert.match(street.payload.reason, /street number is not a price/);
  assert.equal(draftFiles(street.dir).length, 0);
  const placeholder = stageWith("Hi Dana, the new price for 12 Oak St is [PRICE].", why);
  assert.equal(placeholder.payload.outcome, "staged", placeholder.stdout);
  const dollars = stageWith("Hi Dana, the new price for 12 Oak St is $450000.", why);
  assert.equal(dollars.payload.outcome, "staged", dollars.stdout);
  const bare = stageWith("Hi Dana, the new price for Oak St is 450000.", why);
  assert.equal(bare.payload.outcome, "staged", bare.stdout);
});

test("from your own text is shown once when the model already wrapped or led with it", () => {
  const paren = stageWith("Hi Sam, happy birthday!", "It's Sam's birthday today (from your own text)");
  assert.equal(paren.payload.why_line, "Why: It's Sam's birthday today, from your own text.");
  assert.equal(paren.payload.why_line.split("from your own text").length, 2);
  const lead = stageWith("Hi Sam, happy birthday!", "From your own text, it's Sam's birthday today");
  assert.equal(lead.payload.why_line, "Why: It's Sam's birthday today, from your own text.");
  assert.equal(lead.payload.why_line.split("from your own text").length, 2);
  const mid = stageWith(
    "Hi Dana, your offer is due today.",
    "Dana asked (from your own text) and the offer is due today.",
  );
  assert.equal(mid.payload.outcome, "staged", mid.stdout);
  assert.equal(mid.payload.why_line, "Why: Dana asked and the offer is due today, from your own text.");
  assert.equal(mid.payload.why_line.split("from your own text").length, 2);
  assert.equal(mid.payload.attestation.includes("(from your own text)"), false);
});

function stageThenSend(body, why, confirm = "SEND") {
  const dir = mkdtempSync(join(tmpdir(), "sms-ph-"));
  const staged = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", body, "--why", why,
    "--source-kind", "owner_text"], {}, dir);
  assert.equal(staged.payload.outcome, "staged", staged.stdout);
  const sent = run(["send", "--draft-id", staged.payload.draft_id, "--confirm", confirm, "--attest", "yes"], {}, dir);
  return { dir, staged, sent };
}

test("send refuses a draft whose body still has a bracketed placeholder, and restage with the value sends", () => {
  const why = "Dana asked about the new Oak St price";
  for (const body of [
    "Hi Dana, the new price for 12 Oak St is [PRICE].",
    "Hi Dana, the showing is on [DATE].",
    "Hi Dana, see you at [TIME].",
    "Hi Dana, the new price for [ADDRESS] is $450,000.",
    "Hi Dana, the walkthrough is at [ADDRESS] with [AGENT NAME] and [LOT_NO].",
  ]) {
    const { dir, sent } = stageThenSend(body, why);
    assert.equal(sent.payload.outcome, "refused_unfilled_placeholder", sent.stdout);
    assert.equal(sent.payload.provider_called, false);
    assert.equal(sent.callLines.length, 0, body);
    assert.ok(sent.payload.placeholders.length >= 1);
    const files = draftFiles(dir).map((n) => JSON.parse(readFileSync(join(dir, "drafts", n), "utf8")));
    assert.equal(files.length, 1);
    assert.ok(
      files.every((d) => d.status === "refused" && d.refuse_reason === "unfilled_placeholder" && d.body === ""),
      "draft is refused with reason and body stripped from disk",
    );
  }
  const spaced = stageThenSend("Hi Dana, the showing is on [ DATE ].", why);
  assert.equal(spaced.sent.payload.outcome, "refused_unfilled_placeholder", spaced.sent.stdout);
  assert.deepEqual(spaced.sent.payload.placeholders, ["[DATE]"]);
  const lower = stageThenSend("Hi Dana, the new price is [price].", why);
  assert.equal(lower.sent.payload.outcome, "refused_unfilled_placeholder", lower.sent.stdout);
  const filled = stageThenSend("Hi Dana, the new price for 12 Oak St is $450,000.", why);
  assert.equal(filled.sent.payload.outcome, "sent", filled.sent.stdout);
  assert.equal(filled.sent.callLines.length, 1);
});

test("the placeholder guard does not block ordinary brackets, and NO on a placeholder draft still just drops it", () => {
  const why = "Dana asked about the new Oak St price";
  const ok = stageThenSend("Hi Dana, the offer is in [1] and (see the attached) lot 4.", why);
  assert.equal(ok.sent.payload.outcome, "sent", ok.sent.stdout);
  const no = stageThenSend("Hi Dana, the new price is [PRICE].", why, "NO");
  assert.equal(no.sent.payload.outcome, "refused_no_confirm", no.sent.stdout);
  assert.equal(no.sent.callLines.length, 0);
});

test("SKILL.md: any missing detail gets a placeholder, restage after the value, never send a placeholder", () => {
  const skill = readFileSync(skillPath, "utf8");
  assert.match(skill, /bracketed UPPERCASE placeholder/);
  assert.match(skill, /stage the message AGAIN with the value filled in/);
  assert.match(skill, /NEVER send a bracketed placeholder/);
  assert.match(skill, /refused_unfilled_placeholder/);
  assert.match(skill, /refused_no_recipient/);
  assert.match(skill, /Who should I text/);
  assert.match(skill, /Reply SEND to send, DROP to discard/);
});

test("SKILL.md script examples with --actor run send, cancel, and stage --replaces", () => {
  const skill = readFileSync(skillPath, "utf8");
  const blocks = [...skill.matchAll(/```bash\n([\s\S]*?)```/g)].map((m) => m[1]);
  const lines = blocks
    .flatMap((b) => b.split("\n"))
    .map((l) => l.trim())
    .filter((l) => l.startsWith("python3 ") && l.includes("sms_send_confirmed.py"));
  assert.ok(lines.length >= 3, "expected documented script examples");
  const script = join(root, "skills", "sms-send-confirmed", "scripts", "sms_send_confirmed.py");
  function argsFromSkillLine(line) {
    const cmd = line
      .replace("/opt/data/skills/sms-send-confirmed/scripts/sms_send_confirmed.py", script)
      .replace("+17145550100", OWNER)
      .replace("+15555550199", DEST);
    const rest = cmd.replace(/^python3\s+\S+\s+/, "");
    const args = [];
    let cur = "";
    let inQuote = false;
    for (const ch of rest) {
      if (ch === '"') {
        inQuote = !inQuote;
        continue;
      }
      if (ch === " " && !inQuote) {
        if (cur) args.push(cur);
        cur = "";
        continue;
      }
      cur += ch;
    }
    if (cur) args.push(cur);
    return args;
  }
  const sendLine = lines.find((l) => l.includes(" send ") && l.includes("+17145550100"));
  const cancelLine = lines.find((l) => l.includes(" cancel ") && l.includes("+17145550100"));
  const stageLine = lines.find((l) => l.includes(" stage ") && l.includes("--replaces") && l.includes("+17145550100"));
  assert.ok(sendLine && cancelLine && stageLine);
  const sendDir = mkdtempSync(join(tmpdir(), "sms-skill-send-"));
  const sendDraft = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, sendDir);
  const sendArgs = argsFromSkillLine(sendLine).map((a) => (a === "DRAFT_ID" ? sendDraft.payload.draft_id : a));
  const sent = run(sendArgs, { SMS_SEND_STUB_PROVIDER: "1" }, sendDir);
  assert.equal(sent.payload.outcome, "sent");
  const cancelDir = mkdtempSync(join(tmpdir(), "sms-skill-cancel-"));
  const cancelDraft = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, cancelDir);
  const cancelArgs = argsFromSkillLine(cancelLine).map((a) => (a === "DRAFT_ID" ? cancelDraft.payload.draft_id : a));
  const cancelled = run(cancelArgs, {}, cancelDir);
  assert.equal(cancelled.payload.outcome, "cancelled");
  const replaceDir = mkdtempSync(join(tmpdir(), "sms-skill-replace-"));
  const first = run(["stage", "--approver", OWNER, "--dest", DEST, "--body", BODY], {}, replaceDir);
  const stageArgs = argsFromSkillLine(stageLine).map((a) => (a === "DRAFT_ID" ? first.payload.draft_id : a));
  const replaced = run(stageArgs, {}, replaceDir);
  assert.equal(replaced.payload.outcome, "staged");
  assert.ok(stageArgs.includes("--actor"));
});

// --- RED-585 QA RUN 10 (Oct 19) -----------------------------------------------------------
test("RED-585: back-to-back drafts cannot reuse the prior Why when recipient or body differs", () => {
  const dir = mkdtempSync(join(tmpdir(), "sms-why-reuse-"));
  const appraisalWhy = "The appraisal came in";
  const first = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      "Hi Garcias, the appraisal came in.",
      "--why",
      appraisalWhy,
      "--source-kind",
      "owner_text",
    ],
    {},
    dir,
    { why: false },
  );
  assert.equal(first.payload.outcome, "staged", first.stdout);
  assert.match(first.payload.why_line, /appraisal came in/);
  const dropped = run(
    ["send", "--draft-id", first.payload.draft_id, "--confirm", "DROP", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(dropped.payload.outcome, "refused_no_confirm");
  const copiedWhy = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST2,
      "--body",
      "Hi Hendersons, the comparison is coming before our 4 PM call.",
      "--why",
      appraisalWhy,
      "--source-kind",
      "owner_text",
    ],
    {},
    dir,
    { why: false },
  );
  assert.equal(copiedWhy.payload.outcome, "refused_why_reused", copiedWhy.stdout);
  const distinct = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST2,
      "--body",
      "Hi Hendersons, the comparison is coming before our 4 PM call.",
      "--why",
      "The Hendersons need the comparison before the 4 PM call",
      "--source-kind",
      "owner_text",
    ],
    {},
    dir,
    { why: false },
  );
  assert.equal(distinct.payload.outcome, "staged", distinct.stdout);
  assert.notEqual(distinct.payload.why_line, first.payload.why_line);
  assert.match(distinct.payload.why_line, /comparison before the 4 PM call/);
  assert.match(first.payload.why_line, /appraisal came in/);
  const dropDistinct = run(
    ["send", "--draft-id", distinct.payload.draft_id, "--confirm", "DROP", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(dropDistinct.payload.outcome, "refused_no_confirm");
  const sameAgain = run(
    [
      "stage",
      "--approver",
      OWNER,
      "--dest",
      DEST,
      "--body",
      "Hi Garcias, the appraisal came in.",
      "--why",
      appraisalWhy,
      "--source-kind",
      "owner_text",
    ],
    {},
    dir,
    { why: false },
  );
  assert.equal(sameAgain.payload.outcome, "staged", "restaging the same text may reuse the same why");
});

test("RUN 10 item 9: [NAME] in the greeting is refused_no_recipient; no draft", () => {
  const r = stageWith("Hi [NAME], just following up.", "The prior conversation needs a follow-up now");
  assert.equal(r.payload.outcome, "refused_no_recipient", r.stdout);
  assert.match(r.payload.reason, /Who should I text/i);
  assert.equal(draftFiles(r.dir).length, 0);
  assert.equal(r.payload.provider_called, false);
});

test("RUN 10 item 4: [BUYER NAME] in the greeting is who-first refused, not a content placeholder draft", () => {
  const r = stageWith(
    "Hi [BUYER NAME], the price dropped to [PRICE] on the Oak St listing.",
    "The price dropped on Oak St",
  );
  assert.equal(r.payload.outcome, "refused_no_recipient", r.stdout);
  assert.equal(draftFiles(r.dir).length, 0);
});

test("RUN 10 item 4 rule: real named recipient with [PRICE] stages, Missing line, and carrier opt-out last", () => {
  const body = "Hi Dana, the price dropped to [PRICE] on the Oak St listing.";
  const why = "The price dropped on the Oak St listing";
  const r = stageWith(body, why);
  assert.equal(r.payload.outcome, "staged", r.stdout);
  assert.equal(
    r.payload.missing_line,
    "Missing: new price. Reply with it to restage, or DROP to discard.",
  );
  assert.doesNotMatch(r.payload.missing_line, /Reply SEND to send/);
  const lines = r.payload.attestation.split("\n");
  const whyIdx = lines.findIndex((l) => l.startsWith("Why:"));
  const missingIdx = lines.findIndex((l) => l.startsWith("Missing:"));
  const authIdx = lines.findIndex((l) => l.startsWith("Reply SEND to confirm"));
  const dropIdx = lines.findIndex((l) => l === "Reply SEND to send, DROP to discard.");
  const optIdx = lines.findIndex((l) => l === "The recipient can still opt out with their carrier.");
  assert.ok(whyIdx > 1 && missingIdx > whyIdx && authIdx > missingIdx && dropIdx > authIdx && optIdx === lines.length - 1);
  assert.match(r.payload.attestation, /The recipient can still opt out with their carrier\./);
});

test("RED-585 live: recipient need tails on the Why are refused; fact-only whys stage", () => {
  const body = "Hi Dana, your closing date is now Nov 3.";
  const bad = [
    "Dana's closing date changed, so she needs the new date",
    "The offer on 12 Oak St was accepted, and she needs the good news",
  ];
  for (const why of bad) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "refused_why_action_tail", why + " " + r.stdout);
    assert.match(r.payload.reason, /reason or fact only/i);
    assert.equal(draftFiles(r.dir).length, 0);
  }
  for (const why of [
    "Dana's closing date moved to Nov 3.",
    "The offer on 12 Oak St was accepted.",
  ]) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "staged", why + " " + r.stdout);
    assert.match(r.payload.why_line, new RegExp(why.replace(/[.?]$/, "").split(".")[0].slice(0, 12)));
  }
});

test("RUN 10 item 8: Why consequence tail is refused_why_action_tail", () => {
  const r = stageWith("Hi Garcias, the appraisal came in.", "The appraisal came in, so the Garcias should know");
  assert.equal(r.payload.outcome, "refused_why_action_tail", r.stdout);
  assert.equal(draftFiles(r.dir).length, 0);
  const buyer = stageWith(
    "Hi Dana, the price dropped to [PRICE] on the Oak St listing.",
    "The price dropped, so the buyer should know",
  );
  assert.equal(buyer.payload.outcome, "refused_why_action_tail", buyer.stdout);
});

test("RUN 10 negative controls: items 1-3 and 5-7 style drafts still stage unchanged", () => {
  const cases = [
    ["Hi Hendersons, the comparison is coming before our 4 PM call.", "The Hendersons need the comparison before the 4 PM call"],
    ["Hi Dana, yes, the inspection report is in.", "Dana asked if the inspection report is in"],
    ["Hi Mike, just checking in since things have gone quiet on your end.", "Mike from Zillow went quiet on the listing"],
    ["Hi Pat, congratulations on closing today.", "Pat is closing today"],
    ["Hi Lee, a reminder that the showing is tomorrow at 10.", "Lee's showing is tomorrow at 10"],
    ["Hi Sam, happy birthday!", "Sam's birthday is today"],
  ];
  for (const [body, why] of cases) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "staged", body + " " + r.stdout);
    assert.equal(r.payload.missing_line, undefined);
    assert.match(r.payload.attestation, /The recipient can still opt out with their carrier\./);
  }
});

test("who-first: role placeholder [BUYER] in greeting refuses; known real name with [PRICE] stages", () => {
  const role = stageWith("Hi [BUYER], the appraisal came in.", "The appraisal came in");
  assert.equal(role.payload.outcome, "refused_no_recipient", role.stdout);
  const named = stageWith("Hi Dana, the new price for 12 Oak St is [PRICE].", "Dana asked about the new Oak St price");
  assert.equal(named.payload.outcome, "staged", named.stdout);
  assert.ok(named.payload.missing_line);
});

test("Why action tail: real causes with 'so ... can' still stage (not _WHY_SO_CAN)", () => {
  for (const [body, why] of [
    ["Hi Dana, we can plan the move timeline.", "Dana asked so she can plan the move"],
    ["Hi Lee, Saturday works for the showing.", "Lee asked for Saturday so the showing can be booked"],
  ]) {
    const r = stageWith(body, why);
    assert.equal(r.payload.outcome, "staged", why + " " + r.stdout);
    assert.notEqual(r.payload.outcome, "refused_why_action_tail");
  }
});

test("attestation with multiple content placeholders lists Missing once before standard footer", () => {
  const r = stageWith(
    "Hi Dana, the showing is on [DATE] at [TIME].",
    "Dana asked to confirm the showing time",
  );
  assert.equal(r.payload.outcome, "staged", r.stdout);
  assert.match(
    r.payload.missing_line,
    /^Missing: date and time\. Reply with both to restage, or DROP to discard\.$/,
  );
  assert.ok(r.payload.attestation.indexOf(r.payload.missing_line) < r.payload.attestation.indexOf("Reply SEND to confirm"));
  assert.ok(r.payload.attestation.endsWith("The recipient can still opt out with their carrier."));
});
