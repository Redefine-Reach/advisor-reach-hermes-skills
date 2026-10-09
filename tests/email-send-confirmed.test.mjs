// Hermetic contract for email-send-confirmed. No network, no Hermes, no Composio.
// The script is the gate: stage never sends; send requires SEND plus attestation;
// cron, a delegated child, a missing Why line, and a multi-recipient never call
// the transport. The transport stands in for GMAIL_SEND_EMAIL.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const skillPath = join(root, "skills", "email-send-confirmed", "SKILL.md");
const scriptPath = join(root, "skills", "email-send-confirmed", "scripts", "email_send_confirmed.py");
const skill = readFileSync(skillPath, "utf8");
const script = readFileSync(scriptPath, "utf8");

const OWNER = "+17145550100";
const TO = "jane@example.com";
const FROM_ACCOUNT = "advisor@example.com";
const CONNECTED = "ca_test_work";
const SUBJECT = "Listing packet";
const BODY = "The listing packet is ready.";
const SECRET = "super-secret-composio-key";

function draftFiles(dir) {
  const drafts = join(dir, "drafts");
  if (!existsSync(drafts)) return [];
  return readdirSync(drafts).filter((name) => name.endsWith(".json"));
}

function run(args, extra = {}, dir = mkdtempSync(join(tmpdir(), "email-send-")), options = {}) {
  const cmdArgs =
    options.why === false || args[0] !== "stage" || args.includes("--why")
      ? args
      : [
          ...args,
          "--why",
          "you asked for this email today",
          "--source-kind",
          "owner_text",
          "--source-date",
          "2026-10-08",
        ];
  const calls = join(dir, "calls.jsonl");
  const transport = join(dir, "transport.py");
  writeFileSync(
    transport,
    [
      "#!/usr/bin/env python3",
      "import json, os, sys",
      "req = json.load(sys.stdin)",
      "if os.environ.get('COMPOSIO_API_KEY'):",
      "    req['leaked'] = True",
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
    EMAIL_SEND_CONFIRMED_TEST: "1",
    SMS_BOX_ID: "advisor-reach-internal",
    TELNYX_SMS_ALLOWED_USERS: OWNER,
    EMAIL_AUDIT_PATH: join(dir, "email-outbound.jsonl"),
    EMAIL_DRAFT_DIR: join(dir, "drafts"),
    EMAIL_SEND_TRANSPORT: transport,
    CALLS: calls,
    COMPOSIO_API_KEY: SECRET,
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
  const auditPath = env.EMAIL_AUDIT_PATH;
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
spec = importlib.util.spec_from_file_location("email_send_confirmed", ${JSON.stringify(scriptPath)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
`;

function stageArgs(extra = []) {
  return [
    "stage",
    "--approver",
    OWNER,
    "--to",
    TO,
    "--subject",
    SUBJECT,
    "--body",
    BODY,
    "--from-account",
    FROM_ACCOUNT,
    "--connected-account",
    CONNECTED,
    ...extra,
  ];
}

test("skill routes Gmail through the script and forbids the send tool", () => {
  assert.match(skill, /^name: email-send-confirmed$/m);
  assert.match(skill, /Email one person from the advisor's Gmail/);
  assert.match(skill, /Your entire reply to the owner is the JSON `attestation` field, verbatim/);
  assert.match(skill, /exactly `SEND` or `\/approve`/);
  assert.match(skill, /refused_no_confirm/);
  assert.match(skill, /refused_no_attestation/);
  assert.match(skill, /refused_autonomous/);
  assert.match(skill, /refused_no_why/);
  assert.match(skill, /refused_multi/);
  assert.match(skill, /refused_no_box/);
  assert.match(skill, /HERMES_DELEGATED_CHILD_CONTEXT/);
  assert.match(skill, /Never call `GMAIL_SEND_EMAIL`/);
  assert.match(skill, /GMAIL_REPLY_TO_THREAD/);
  assert.match(skill, /GMAIL_SEND_DRAFT/);
  assert.match(skill, /Never name a source you did not read/);
  assert.match(skill, /\(no source\)/);
  assert.match(skill, /ARIN memory:/);
  assert.match(skill, /\/opt\/data\/audit\/email-outbound\.jsonl/);
  assert.match(skill, /print `COMPOSIO_API_KEY`/);
  assert.doesNotMatch(skill, /COMPOSIO_MULTI_EXECUTE_TOOL` with properly formed/);
  const frontmatter = skill.match(/^---\n([\s\S]*?)\n---\n/)[1];
  assert.match(frontmatter, /required_environment_variables:\n  - TELNYX_SMS_ALLOWED_USERS/);
  assert.doesNotMatch(frontmatter, /COMPOSIO_API_KEY/);
  assert.match(script, /HERMES_DELEGATED_CHILD_CONTEXT/);
  assert.match(script, /email-send-v1/);
  assert.match(script, /GMAIL_SEND_EMAIL/);
  assert.doesNotMatch(script, /COMPOSIO_MULTI_EXECUTE_TOOL/);
  assert.doesNotMatch(script, /GMAIL_REPLY_TO_THREAD/);
});

test("skills that can send email route through the gate and name the Gmail tool as forbidden", () => {
  const files = [
    "skills/connect-app/SKILL.md",
    "skills/fub/SKILL.md",
    "skills/ghl/SKILL.md",
    "skills/smartlead-campaigns/SKILL.md",
    "skills/email-outreach/SKILL.md",
  ];
  for (const rel of files) {
    const text = readFileSync(join(root, rel), "utf8");
    assert.match(text, /email-send-confirmed/, rel);
    assert.match(text, /GMAIL_SEND_EMAIL/, rel);
  }
  const connect = readFileSync(join(root, "skills/connect-app/SKILL.md"), "utf8");
  assert.match(connect, /That reuse rule does not apply to email/);
  assert.match(connect, /Never call\n\s+`GMAIL_SEND_EMAIL`/);
});

test("stage shows recipient, subject, body preview, and Why line, and does not send", () => {
  const line = "Why: Jane's offer deadline is 5 PM today (FUB note, Oct 7).";
  assert.equal(line.length, 59);
  const dir = mkdtempSync(join(tmpdir(), "email-why-ok-"));
  const staged = run(
    stageArgs([
      "--why",
      "Jane's offer deadline is 5 PM today",
      "--source-kind",
      "fub_note",
      "--source-date",
      "2026-10-07",
      "--source-ref",
      "note-1",
    ]),
    {},
    dir,
  );
  assert.equal(staged.payload.outcome, "staged");
  assert.equal(staged.payload.provider_called, false);
  assert.equal(staged.payload.attestation_version, "email-send-v1");
  assert.equal(staged.payload.to, TO);
  assert.equal(staged.payload.from_account, FROM_ACCOUNT);
  assert.equal(staged.payload.subject, SUBJECT);
  assert.equal(staged.payload.body_preview, BODY);
  assert.equal(staged.payload.why_line, line);
  assert.equal(staged.payload.source_kind, "fub_note");
  assert.equal(staged.payload.source_date, "2026-10-07");
  assert.equal(staged.payload.source_ref, undefined);
  assert.equal(staged.payload.body, undefined);
  assert.equal(staged.callLines.length, 0);
  assert.doesNotMatch(staged.proc.stdout, new RegExp(SECRET));
  const parts = staged.payload.attestation.split("\n");
  assert.equal(parts[0], `You're about to send this email from ${FROM_ACCOUNT} to ${TO}.`);
  assert.equal(parts[1], `Subject: ${SUBJECT}`);
  assert.equal(parts[2], `Body: ${BODY}`);
  assert.equal(parts[3], line);
  assert.match(parts[4], /^Reply SEND to confirm/);
  const draft = JSON.parse(readFileSync(join(dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.body, BODY);
  assert.equal(draft.body_hash, createHash("sha256").update(BODY).digest("hex"));
  assert.equal(draft.why_line, line);
  assert.equal(draft.source_ref, "note-1");
  assert.doesNotMatch(draft.body, /Why:/);
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(sent.payload.provider_called, true);
  assert.equal(sent.payload.provider_message_id, "msg_test_1");
  assert.equal(sent.callLines.length, 1);
  const request = JSON.parse(sent.callLines[0]);
  assert.equal(request.tool_slug, "GMAIL_SEND_EMAIL");
  assert.equal(request.connected_account_id, CONNECTED);
  assert.equal(request.arguments.recipient_email, TO);
  assert.equal(request.arguments.subject, SUBJECT);
  assert.equal(request.arguments.body, BODY);
  assert.equal(request.arguments.is_html, false);
  assert.equal(request.arguments.from_email, FROM_ACCOUNT);
  assert.equal(request.arguments.user_id, "me");
  assert.equal(request.arguments.cc, undefined);
  assert.equal(request.arguments.bcc, undefined);
  assert.equal(request.arguments.attachment, undefined);
  assert.equal(request.leaked, undefined);
  assert.doesNotMatch(request.arguments.body, /Why:/);
  assert.doesNotMatch(sent.proc.stdout, new RegExp(SECRET));
  const stored = JSON.parse(readFileSync(join(dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"));
  assert.equal(stored.status, "sent");
  assert.equal(stored.body, "");
  const audit = sent.auditLines.at(-1);
  assert.equal(audit.outcome, "sent");
  assert.equal(audit.provider_called, true);
  assert.equal(audit.to, TO);
  assert.equal(audit.body_hash, draft.body_hash);
  assert.doesNotMatch(JSON.stringify(audit), /listing packet is ready/i);
  assert.doesNotMatch(JSON.stringify(audit), /Why:/);
  assert.doesNotMatch(JSON.stringify(audit), new RegExp(SECRET));
});

test("a long body is previewed and the full body is what would send", () => {
  const body = `${"a".repeat(300)}\nsecond line`;
  const staged = run(
    stageArgs().map((part) => (part === BODY ? body : part)),
  );
  assert.equal(staged.payload.outcome, "staged");
  assert.match(staged.payload.body_preview, /\[\+\d+ characters not shown\]$/);
  assert.ok(staged.payload.body_preview.length < body.length);
  assert.doesNotMatch(staged.payload.attestation, /second line/);
  assert.equal(staged.callLines.length, 0);
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "yes"],
    {},
    staged.dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(JSON.parse(sent.callLines[0]).arguments.body, body.trim());
});

test("an alias From does not set from_email", () => {
  const staged = run(stageArgs().map((part) => (part === FROM_ACCOUNT ? "work" : part)));
  assert.equal(staged.payload.outcome, "staged");
  assert.match(staged.payload.attestation, /from work to jane@example.com/);
  const sent = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "/approve", "--attest", "yes"],
    {},
    staged.dir,
  );
  assert.equal(sent.payload.outcome, "sent");
  assert.equal(JSON.parse(sent.callLines[0]).arguments.from_email, undefined);
});

test("send refuses a vague yes and anything except the exact confirm", () => {
  for (const confirm of ["yes", "go ahead", "send it", "SEND please", ""]) {
    const dir = mkdtempSync(join(tmpdir(), "email-vague-"));
    const staged = run(stageArgs(), {}, dir);
    assert.equal(staged.payload.outcome, "staged");
    const refused = run(
      ["send", "--draft-id", staged.payload.draft_id, "--confirm", confirm, "--attest", "yes"],
      {},
      dir,
    );
    assert.equal(refused.payload.outcome, "refused_no_confirm", confirm);
    assert.equal(refused.payload.provider_called, false);
    assert.equal(refused.callLines.length, 0);
    assert.equal(refused.proc.status, 2);
  }
});

test("missing attestation does not send and leaves the draft pending", () => {
  const dir = mkdtempSync(join(tmpdir(), "email-attest-"));
  const staged = run(stageArgs(), {}, dir);
  const refused = run(
    ["send", "--draft-id", staged.payload.draft_id, "--confirm", "SEND", "--attest", "no"],
    {},
    dir,
  );
  assert.equal(refused.payload.outcome, "refused_no_attestation");
  assert.equal(refused.payload.provider_called, false);
  assert.equal(refused.callLines.length, 0);
  const draft = JSON.parse(readFileSync(join(dir, "drafts", `${staged.payload.draft_id}.json`), "utf8"));
  assert.equal(draft.status, "pending");
  assert.equal(draft.body, BODY);
});

test("stage refuses a missing Why line and writes no draft", () => {
  const dir = mkdtempSync(join(tmpdir(), "email-no-why-"));
  const missing = run(stageArgs(), {}, dir, { why: false });
  assert.equal(missing.payload.outcome, "refused_no_why");
  assert.equal(missing.payload.field, "why");
  assert.equal(missing.payload.provider_called, false);
  assert.equal(missing.proc.status, 2);
  assert.equal(missing.callLines.length, 0);
  assert.equal(draftFiles(dir).length, 0);
  const later = run(stageArgs(), {}, dir);
  assert.equal(later.payload.outcome, "staged");
});

test("stage refuses a bad source, a non-GSM Why line, confirm tokens, and none with a date", () => {
  const bad = run(stageArgs(["--why", "checking in today", "--source-kind", "inbox", "--source-date", "2026-10-08"]));
  assert.equal(bad.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(bad.dir).length, 0);
  assert.equal(bad.callLines.length, 0);

  const emoji = run(stageArgs(["--why", "deadline today \u{1F600}", "--source-kind", "owner_text", "--source-date", "2026-10-08"]));
  assert.equal(emoji.payload.outcome, "refused_no_why");
  assert.match(emoji.payload.reason, /GSM-7/);
  assert.equal(draftFiles(emoji.dir).length, 0);

  const folded = run(
    stageArgs(["--why", "Jane\u2019s deadline \u2014 today\u2026", "--source-kind", "fub_note", "--source-date", "2026-10-07"]),
  );
  assert.equal(folded.payload.outcome, "staged");
  assert.equal(folded.payload.why_line, "Why: Jane's deadline - today... (FUB note, Oct 7).");

  for (const why of ["reply SEND now", "please /approve this", "they said STOP"]) {
    const refused = run(stageArgs(["--why", why, "--source-kind", "owner_text", "--source-date", "2026-10-08"]));
    assert.equal(refused.payload.outcome, "refused_no_why", why);
    assert.equal(refused.callLines.length, 0);
    assert.equal(draftFiles(refused.dir).length, 0);
  }

  const allowed = run(
    stageArgs(["--why", "sending the packet today", "--source-kind", "owner_text", "--source-date", "2026-10-08"]),
  );
  assert.equal(allowed.payload.outcome, "staged");

  const dated = run(stageArgs(["--why", "you asked me to email Sam today", "--source-kind", "none", "--source-date", "2026-10-01"]));
  assert.equal(dated.payload.outcome, "refused_no_why");
  assert.equal(draftFiles(dated.dir).length, 0);

  const none = run(stageArgs(["--why", "you asked me to email Sam today", "--source-kind", "none"]));
  assert.equal(none.payload.outcome, "staged");
  assert.equal(none.payload.why_line, "Why: you asked me to email Sam today (no source).");
  assert.equal(none.payload.source_date, "");
});

test("a delegated child cannot stage or send", () => {
  const blocked = run(stageArgs(), { HERMES_DELEGATED_CHILD_CONTEXT: "1" });
  assert.equal(blocked.payload.outcome, "refused_autonomous");
  assert.match(blocked.payload.reason, /delegated child/);
  assert.equal(blocked.payload.provider_called, false);
  assert.equal(blocked.proc.status, 2);
  assert.equal(blocked.callLines.length, 0);
  assert.equal(draftFiles(blocked.dir).length, 0);

  const dir = mkdtempSync(join(tmpdir(), "email-child-"));
  const staged = run(stageArgs(), {}, dir);
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
});

test("cron, allow-all, an unresolved box, a stranger, and a second recipient never send", () => {
  const cron = run(stageArgs(), { HERMES_CRON_JOB_ID: "job-1" });
  assert.equal(cron.payload.outcome, "refused_autonomous");
  assert.equal(cron.callLines.length, 0);
  assert.equal(draftFiles(cron.dir).length, 0);

  const allowAll = run(stageArgs(), { TELNYX_SMS_ALLOW_ALL_USERS: "1" });
  assert.equal(allowAll.payload.outcome, "refused_autonomous");
  assert.equal(allowAll.callLines.length, 0);

  const unresolved = run(stageArgs(), { SMS_BOX_ID: "" });
  assert.equal(unresolved.payload.outcome, "refused_no_box");
  assert.equal(unresolved.payload.provider_called, false);
  assert.equal(unresolved.callLines.length, 0);

  const stranger = run(stageArgs().map((part) => (part === OWNER ? "+15555550111" : part)));
  assert.equal(stranger.payload.outcome, "refused_not_owner");
  assert.equal(stranger.callLines.length, 0);

  const multi = run(stageArgs().map((part) => (part === TO ? "jane@example.com, bob@example.com" : part)));
  assert.equal(multi.payload.outcome, "refused_multi");
  assert.equal(multi.callLines.length, 0);
  assert.equal(draftFiles(multi.dir).length, 0);

  const subjectToken = run(stageArgs().map((part) => (part === SUBJECT ? "Please SEND this" : part)));
  assert.equal(subjectToken.payload.outcome, "refused_no_why");
  assert.equal(subjectToken.callLines.length, 0);
});

test("a second open draft is refused until the first is cancelled", () => {
  const dir = mkdtempSync(join(tmpdir(), "email-two-"));
  const first = run(stageArgs(), {}, dir);
  assert.equal(first.payload.outcome, "staged");
  const second = run(stageArgs(), {}, dir);
  assert.equal(second.payload.outcome, "refused_multi");
  assert.equal(second.callLines.length, 0);
  const cancelled = run(["cancel", "--draft-id", first.payload.draft_id], {}, dir);
  assert.equal(cancelled.payload.outcome, "cancelled");
  assert.equal(cancelled.payload.provider_called, false);
  assert.equal(cancelled.callLines.length, 0);
  const third = run(stageArgs(), {}, dir);
  assert.equal(third.payload.outcome, "staged");
});

test("Why line labels match the source kind", () => {
  const out = py(`${importMod}
assert len(mod.GSM7_CHARS) == 134
assert chr(96) not in mod.GSM7_CHARS
line, kind, day, ref = mod.build_why_line(
    "Jane's offer deadline is 5 PM today", "fub_note", "2026-10-07", "", "note-1")
assert line == "Why: Jane's offer deadline is 5 PM today (FUB note, Oct 7)."
assert len(line) == 59 and kind == "fub_note" and day == "2026-10-07" and ref == "note-1"
gmail, _, gmail_day, _ = mod.build_why_line(
    "Mark asked about rates and has had no reply for 3 days",
    "gmail", "2026-10-05", "Mark", "msg-1")
assert gmail.endswith("(Gmail from Mark, Oct 5).") and gmail_day == "2026-10-05"
memory, memory_kind, _, _ = mod.build_why_line(
    "Sam's lease ends Nov 30, so renewal talk is due",
    "memory", "2026-09-12", "FUB note", "")
assert memory.endswith("(ARIN memory: FUB note, Sep 12).") and memory_kind == "memory"
args = mod.gmail_arguments("jane@example.com", "Hi", "Body", "advisor@example.com")
assert args["is_html"] is False and args["from_email"] == "advisor@example.com"
assert "cc" not in args and "bcc" not in args and "attachment" not in args
alias = mod.gmail_arguments("jane@example.com", "Hi", "Body", "work")
assert "from_email" not in alias
print("ok")
`);
  assert.equal(out, "ok");
});

test("the Composio execute path is built for GMAIL_SEND_EMAIL and does not run on a bad host or a missing key", () => {
  const out = py(`${importMod}
import json, os
calls = []
class Resp:
    status = 200
    def read(self, n=None):
        return b'{"successful": true, "data": {"id": "msg_live_1"}, "error": null}'
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
def fake(req, timeout=0):
    calls.append((req.full_url, dict(req.header_items()), req.data, timeout))
    return Resp()
mod.urllib.request.urlopen = fake
os.environ["COMPOSIO_API_KEY"] = ${JSON.stringify(SECRET)}
os.environ.pop("COMPOSIO_GMAIL_EXECUTE_URL", None)
os.environ.pop("EMAIL_SEND_CONFIRMED_TEST", None)
result = mod.execute_gmail("jane@example.com", "Hi", "Body text", "advisor@example.com", "ca_test_work")
assert result["success"] is True and result["message_id"] == "msg_live_1" and result["provider_called"] is True
assert ${JSON.stringify(SECRET)} not in json.dumps(result)
url, headers, data, timeout = calls[0]
assert url == mod.DEFAULT_EXECUTE_URL
assert timeout == 30
payload = json.loads(data)
assert payload["connected_account_id"] == "ca_test_work"
assert payload["version"] == "latest"
assert payload["arguments"]["recipient_email"] == "jane@example.com"
assert payload["arguments"]["body"] == "Body text"
assert payload["arguments"]["is_html"] is False
assert "cc" not in payload["arguments"]
header_key = headers.get("X-api-key") or headers.get("x-api-key")
assert header_key == ${JSON.stringify(SECRET)}
os.environ["COMPOSIO_GMAIL_EXECUTE_URL"] = "https://evil.example/tools/execute/GMAIL_SEND_EMAIL"
def boom(*args, **kwargs):
    raise SystemExit("urlopen called")
mod.urllib.request.urlopen = boom
blocked = mod.execute_gmail("jane@example.com", "Hi", "Body text", "advisor@example.com", "ca_test_work")
assert blocked["provider_called"] is False and blocked["success"] is False
os.environ["COMPOSIO_GMAIL_EXECUTE_URL"] = "https://backend.composio.dev/api/v3.1/tools/execute/GMAIL_REPLY_TO_THREAD"
reply = mod.execute_gmail("jane@example.com", "Hi", "Body text", "advisor@example.com", "ca_test_work")
assert reply["provider_called"] is False
os.environ.pop("COMPOSIO_API_KEY", None)
os.environ.pop("COMPOSIO_GMAIL_EXECUTE_URL", None)
missing = mod.execute_gmail("jane@example.com", "Hi", "Body text", "advisor@example.com", "ca_test_work")
assert missing["provider_called"] is False and missing["field"] == "composio"
print("ok")
`);
  assert.equal(out, "ok");
});
