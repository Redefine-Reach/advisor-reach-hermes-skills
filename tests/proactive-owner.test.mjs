// Hermetic contract for proactive-owner. No network. Synthetic contacts only.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdtempSync, mkdirSync, readFileSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const skillDir = join(root, "skills", "proactive-owner");
const script = join(skillDir, "scripts", "proactive.py");
const skill = readFileSync(join(skillDir, "SKILL.md"), "utf8");
const configDoc = readFileSync(join(skillDir, "references", "config.md"), "utf8");
const jobDoc = readFileSync(join(skillDir, "references", "afternoon-job.md"), "utf8");
const dailyBrief = readFileSync(join(root, "skills", "daily-brief", "SKILL.md"), "utf8");
const dayOpen = readFileSync(join(root, "skills", "day-open-rollcall", "SKILL.md"), "utf8");
const sendGate = readFileSync(join(root, "skills", "sms-send-confirmed", "SKILL.md"), "utf8");
const source = readFileSync(script, "utf8");
const AFTERNOON = "2026-10-09T15:00:00-07:00";
const PHONE = "+15555550123";
const MAIL = "riley@example.com";

function description(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const match = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(match, "description is one double-quoted line");
  return { fm: fm[1], desc: match[1] };
}

function home() {
  return mkdtempSync(join(tmpdir(), "proactive-"));
}

function writeZone(dir, zone = "America/Phoenix") {
  writeFileSync(
    join(dir, "config.yaml"),
    `skills:\n  timezone: Pacific/Auckland\ntimezone: ${zone} # owner zone\n`,
  );
}

function enable(dir, extra = {}) {
  const folder = join(dir, "proactivity");
  mkdirSync(folder, { recursive: true });
  writeFileSync(join(folder, "config.json"), JSON.stringify({ enabled: true, ...extra }));
  writeZone(dir);
  return readFileSync(join(folder, "config.json"), "utf8");
}

function run(dir, args, extraEnv = {}) {
  return new Promise((resolve) => {
    execFile("python3", [script, ...args], {
      env: { PATH: process.env.PATH, HERMES_HOME: dir, ...extraEnv },
    }, (err, stdout, stderr) => {
      let out = null;
      try {
        out = JSON.parse(stdout);
      } catch {
        out = null;
      }
      resolve({ code: err ? err.code : 0, out, stdout, stderr });
    });
  });
}

function candidates() {
  return {
    contacts: [
      { name: "Jordan Example", source: "fub", last_touch: "2026-10-09T09:00:00-07:00", stage_due: "2026-10-09", phone: PHONE },
      { name: "Avery Example", source: "ghl", last_touch: "2026-10-01T12:00:00-07:00", email: MAIL },
      { name: "Morgan Example", source: "fub", last_touch: "2026-10-08T12:00:00-07:00" },
      { name: "Pat Example", source: "composio", last_touch: "2026-09-01T12:00:00-07:00" },
      { name: PHONE, source: "fub", last_touch: "2026-09-01T12:00:00-07:00" },
      { name: "No Touch Example", source: "fub" },
      { name: "Future Example", source: "fub", stage_due: "2026-11-01" },
    ],
    emails: [
      { name: "Quinn Example", received_at: "2026-10-05T11:00:00-07:00", unanswered: true, known_client: true, from: MAIL },
      { name: "Riley Example", received_at: "2026-10-06T16:00:00-07:00", unanswered: true, known_client: true, from: MAIL },
      { name: "Answered Example", received_at: "2026-10-01T12:00:00-07:00", unanswered: false, known_client: true },
      { name: "Stranger Example", received_at: "2026-10-01T12:00:00-07:00", unanswered: true, known_client: false },
      { name: "Naive Example", received_at: "2026-10-01T12:00:00", unanswered: true, known_client: true },
    ],
    events: [
      { who: "Casey Example", title: "Showing", start: "2026-10-09T16:00:00-07:00" },
      { who: "Devon Example", title: "Walkthrough", start: "2026-10-10T02:00:00Z" },
      { who: "Sam Example", title: "Late UTC", start: "2026-10-09T06:00:00Z" },
    ],
  };
}

function writeCandidates(dir, body = candidates()) {
  const path = join(dir, "candidates.json");
  writeFileSync(path, JSON.stringify(body));
  return path;
}

test("routing prefix is the quiet command and the feature defaults off", () => {
  const { fm, desc } = description(skill);
  assert.equal(desc.slice(0, 57), "Quiet pauses ARIN-started texts to the owner. Default off");
  assert.match(desc, /Never texts a client/);
  assert.equal(fm.includes("required_environment_variables"), false);
  assert.doesNotMatch(skill, /HERMES_TIMEZONE|PROACTIVITY_/);
  assert.match(skill, /\/opt\/data\/proactivity\/config\.json/);
  assert.match(skill, /Do not create that file/);
  assert.match(skill, /never calls `sms-send-confirmed`/);
  assert.match(skill, /\[SILENT\]/);
  assert.match(dayOpen, /Who needs you today/);
  assert.match(dayOpen, /Do not call `sms-send-confirmed`/);
  assert.match(dayOpen, /Do not text a client/);
  assert.match(dailyBrief, /Who needs you today/);
  assert.match(sendGate, /proactive-owner/);
  assert.match(sendGate, /must not call this script/);
  assert.match(configDoc, /No environment variable/);
  assert.match(jobDoc, /not installed by this repo/);
  assert.match(jobDoc, /Never a client number/);
  assert.doesNotMatch(source, /HERMES_TIMEZONE|PROACTIVITY_|telnyx|urllib|http\.client|socket\./i);
  assert.doesNotMatch(source, /standalone_sender|import sms_send/);
});

test("missing config stays off even if enablement env vars are set", async () => {
  const dir = home();
  const result = await run(dir, ["gate", "--kind", "brief", "--pre-script", "--now", AFTERNOON], {
    PROACTIVITY_ENABLED: "1",
    HERMES_TIMEZONE: "America/Phoenix",
  });
  assert.equal(result.code, 0);
  assert.equal(result.out.wakeAgent, false);
  assert.equal(result.out.reason, "disabled");
  assert.equal(result.out.owner_only, true);
  assert.equal(result.out.pre_script, true);
  assert.equal(existsSync(join(dir, "proactivity", "config.json")), false);
  const nudge = await run(dir, ["nudge", "--now", AFTERNOON], { PROACTIVITY_ENABLED: "true" });
  assert.equal(nudge.out.text, "[SILENT]");
  assert.equal(nudge.out.deliver, false);
  assert.equal(nudge.out.recorded, false);
  const section = await run(dir, ["who", "--now", AFTERNOON]);
  assert.equal(section.out.enabled, false);
  assert.equal(section.out.section, null);
  assert.deepEqual(section.out.items, []);
});

test("string true and UTC do not enable a proactive text", async () => {
  const dir = home();
  const folder = join(dir, "proactivity");
  mkdirSync(folder);
  writeFileSync(join(folder, "config.json"), JSON.stringify({ enabled: "true" }));
  writeZone(dir, "UTC");
  const invalid = await run(dir, ["gate", "--kind", "nudge", "--now", AFTERNOON]);
  assert.equal(invalid.out.wakeAgent, false);
  assert.equal(invalid.out.reason, "config_invalid");
  writeFileSync(join(folder, "config.json"), JSON.stringify({ enabled: true }));
  const utc = await run(dir, ["gate", "--kind", "nudge", "--now", AFTERNOON]);
  assert.equal(utc.out.reason, "timezone_refused");
  assert.equal(utc.out.wakeAgent, false);
});

test("the box zone is config.yaml, and a timezone env var cannot open quiet hours", async () => {
  const dir = home();
  enable(dir);
  const blocked = await run(dir, ["gate", "--kind", "nudge", "--now", "2026-10-10T04:30:00Z"], {
    HERMES_TIMEZONE: "Pacific/Auckland",
  });
  assert.equal(blocked.code, 0);
  assert.equal(blocked.out.timezone, "America/Phoenix");
  assert.equal(blocked.out.local_date, "2026-10-09");
  assert.equal(blocked.out.local_time, "21:30");
  assert.equal(blocked.out.reason, "quiet_hours");
  assert.equal(blocked.out.wakeAgent, false);

  const open = await run(dir, ["gate", "--kind", "brief", "--now", "2026-10-09T16:30:00Z"], {
    HERMES_TIMEZONE: "Pacific/Auckland",
  });
  assert.equal(open.out.timezone, "America/Phoenix");
  assert.equal(open.out.local_time, "09:30");
  assert.equal(open.out.reason, "allowed");
  assert.equal(open.out.wakeAgent, true);
});

test("quiet hours use the local clock, including the morning and evening edges", async () => {
  const dir = home();
  enable(dir);
  const evening = await run(dir, ["gate", "--kind", "brief", "--now", "2026-10-09T21:00:00-07:00"]);
  assert.equal(evening.out.reason, "quiet_hours");
  const before = await run(dir, ["gate", "--kind", "brief", "--now", "2026-10-09T20:59:00-07:00"]);
  assert.equal(before.out.reason, "allowed");
  const morning = await run(dir, ["gate", "--kind", "brief", "--now", "2026-10-09T07:59:00-07:00"]);
  assert.equal(morning.out.reason, "quiet_hours");
  assert.equal(morning.out.local_date, "2026-10-09");
  const opens = await run(dir, ["gate", "--kind", "brief", "--now", "2026-10-09T08:00:00-07:00"]);
  assert.equal(opens.out.reason, "allowed");
  const stillYesterday = await run(dir, ["status", "--now", "2026-10-10T06:30:00Z"]);
  assert.equal(stillYesterday.out.local_date, "2026-10-09");
  assert.equal(stillYesterday.out.reason, "quiet_hours");
});

test("daily cap counts brief, nudge, and receipt on the local date and resets the next morning", async () => {
  const dir = home();
  enable(dir, { daily_cap: 2 });
  const first = await run(dir, ["record", "--kind", "brief", "--token", "brief:2026-10-09", "--now", AFTERNOON]);
  assert.equal(first.out.recorded, true);
  assert.equal(first.out.count, 1);
  const again = await run(dir, ["record", "--kind", "brief", "--token", "brief:2026-10-09", "--now", AFTERNOON]);
  assert.equal(again.out.idempotent, true);
  assert.equal(again.out.recorded, false);
  assert.equal(again.out.count, 1);
  const second = await run(dir, ["record", "--kind", "receipt", "--token", "receipt:2026-10-09", "--now", AFTERNOON]);
  assert.equal(second.out.recorded, true);
  assert.equal(second.out.count, 2);
  const blocked = await run(dir, ["gate", "--kind", "nudge", "--now", "2026-10-09T16:00:00-07:00"]);
  assert.equal(blocked.out.reason, "daily_cap");
  assert.equal(blocked.out.wakeAgent, false);
  const nextDay = await run(dir, ["gate", "--kind", "nudge", "--now", "2026-10-10T08:30:00-07:00"]);
  assert.equal(nextDay.out.local_date, "2026-10-10");
  assert.equal(nextDay.out.reason, "allowed");
  assert.equal(nextDay.out.count, 0);
});

test("quiet is an exact owner phrase, cron cannot change it, and it does not enable the file", async () => {
  const dir = home();
  const original = enable(dir);
  const ignored = await run(dir, ["owner", "--text", "be quiet about the price", "--now", AFTERNOON]);
  assert.equal(ignored.out.reason, "not_a_command");
  assert.equal(ignored.out.paused, false);
  const cron = await run(dir, ["owner", "--text", "quiet", "--now", AFTERNOON], { HERMES_CRON_JOB_ID: "job-1" });
  assert.equal(cron.code, 0);
  assert.equal(cron.out.reason, "refused_autonomous");
  const still = await run(dir, ["gate", "--kind", "nudge", "--now", AFTERNOON], { HERMES_CRON_JOB_ID: "job-1" });
  assert.equal(still.out.reason, "allowed");
  const paused = await run(dir, ["owner", "--text", "Quiet!", "--now", AFTERNOON]);
  assert.equal(paused.out.action, "pause");
  assert.equal(paused.out.paused, true);
  assert.equal(paused.out.enabled, true);
  assert.equal(readFileSync(join(dir, "proactivity", "config.json"), "utf8"), original);
  assert.equal(statSync(join(dir, "proactivity", "state.json")).mode & 0o777, 0o600);
  const blocked = await run(dir, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(blocked.out.reason, "quiet");
  const recorded = await run(dir, ["record", "--kind", "nudge", "--token", "nudge:2026-10-09", "--now", AFTERNOON]);
  assert.equal(recorded.out.recorded, false);
  assert.equal(recorded.out.reason, "quiet");
  const resumed = await run(dir, ["owner", "--text", "nudges on", "--now", AFTERNOON]);
  assert.equal(resumed.out.action, "resume");
  assert.equal(resumed.out.paused, false);
  const open = await run(dir, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(open.out.reason, "allowed");
});

test("quiet while the feature is off is remembered and does not create config.json", async () => {
  const dir = home();
  writeZone(dir);
  const paused = await run(dir, ["owner", "--text", "pause nudges", "--now", AFTERNOON]);
  assert.equal(paused.out.paused, true);
  assert.equal(paused.out.enabled, false);
  assert.equal(existsSync(join(dir, "proactivity", "config.json")), false);
  const off = await run(dir, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(off.out.reason, "disabled");
  assert.equal(off.out.paused, true);
  enable(dir);
  const still = await run(dir, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(still.out.reason, "quiet");
});

test("a destination flag is refused and does not send", async () => {
  const dir = home();
  enable(dir);
  const result = await run(dir, ["gate", "--kind", "nudge", "--dest", PHONE, "--now", AFTERNOON]);
  assert.equal(result.code, 2);
  assert.equal(result.out.reason, "refused_owner_only");
  assert.match(result.stdout, /owner only/);
  assert.doesNotMatch(result.stdout, new RegExp(PHONE.replace("+", "\\+")));
});

test("who needs you today is ranked in the box zone and omits non-clients", async () => {
  const dir = home();
  enable(dir, { who_limit: 3 });
  const path = writeCandidates(dir);
  const result = await run(dir, ["who", "--input", path, "--now", AFTERNOON]);
  assert.equal(result.code, 0);
  assert.equal(result.out.section, "Who needs you today");
  assert.deepEqual(result.out.items.map((item) => item.who), [
    "Jordan Example",
    "Casey Example",
    "Devon Example",
  ]);
  assert.equal(result.out.items[0].why, "stage due today");
  assert.equal(result.out.items[1].source, "calendar");
  assert.equal(result.out.items[2].why, "on your calendar today");
  const names = result.out.items.map((item) => item.who);
  for (const absent of ["Sam Example", "Avery Example", "Riley Example", "Pat Example", "Morgan Example", "Stranger Example", "Answered Example", "Naive Example", "No Touch Example"]) {
    assert.equal(names.includes(absent), false, absent);
  }
  assert.match(result.out.stage_hint, /sms-send-confirmed/);
  assert.match(result.out.stage_hint, /needs SEND/);
  assert.match(result.out.stage_hint, /does not text them/);
  assert.match(result.out.sms, /^Who needs you:/);
  assert.doesNotMatch(result.stdout, /\+1555/);
  assert.doesNotMatch(result.stdout, /example\.com/);
  assert.doesNotMatch(result.stdout, /I will|I'll/i);
  for (const item of result.out.items) {
    assert.match(item.draft, /^Draft to /);
  }
});

test("an email younger than 48 hours does not qualify and an exact 48 does", async () => {
  const dir = home();
  enable(dir);
  const path = writeCandidates(dir, {
    contacts: [],
    events: [],
    emails: [
      { name: "Exact Example", received_at: "2026-10-07T15:00:00-07:00", unanswered: true, known_client: true },
      { name: "Recent Example", received_at: "2026-10-07T16:00:00-07:00", unanswered: true, known_client: true },
    ],
  });
  const result = await run(dir, ["who", "--input", path, "--now", AFTERNOON]);
  assert.deepEqual(result.out.items.map((item) => item.who), ["Exact Example"]);
  assert.match(result.out.items[0].why, /Wednesday/);
});

test("the afternoon nudge texts the owner about unanswered mail or stays silent", async () => {
  const dir = home();
  enable(dir, { who_limit: 1, daily_cap: 3 });
  const path = writeCandidates(dir);
  const first = await run(dir, ["nudge", "--input", path, "--now", AFTERNOON]);
  assert.equal(first.out.deliver, true);
  assert.equal(first.out.silent, false);
  assert.equal(first.out.recorded, true);
  assert.match(first.out.text, /You haven't replied to Quinn Example's email from Monday/);
  assert.match(first.out.text, /1 other client email is also waiting/);
  assert.doesNotMatch(first.out.text, /Jordan Example|sms-send-confirmed|\bSEND\b|I will|I'll|\+1555|example\.com/);
  assert.ok(first.out.text.length <= 549);
  const state = JSON.parse(readFileSync(join(dir, "proactivity", "state.json"), "utf8"));
  assert.equal(state.counts["2026-10-09"].nudge, 1);
  const second = await run(dir, ["nudge", "--input", path, "--now", AFTERNOON]);
  assert.equal(second.out.text, "[SILENT]");
  assert.equal(second.out.reason, "already_sent");
  assert.equal(second.out.recorded, false);
  const after = JSON.parse(readFileSync(join(dir, "proactivity", "state.json"), "utf8"));
  assert.equal(after.counts["2026-10-09"].nudge, 1);
});

test("a nudge during quiet hours or with nothing to say does not spend the cap", async () => {
  const dir = home();
  enable(dir);
  const path = writeCandidates(dir, { contacts: [{ name: "Avery Example", source: "fub", last_touch: "2026-10-01T12:00:00-07:00" }], emails: [], events: [] });
  const none = await run(dir, ["nudge", "--input", path, "--now", AFTERNOON]);
  assert.equal(none.out.text, "[SILENT]");
  assert.equal(none.out.reason, "none");
  assert.equal(existsSync(join(dir, "proactivity", "state.json")), false);
  const quiet = await run(dir, ["nudge", "--input", writeCandidates(dir), "--now", "2026-10-09T22:00:00-07:00"]);
  assert.equal(quiet.out.text, "[SILENT]");
  assert.equal(quiet.out.reason, "quiet_hours");
  assert.equal(quiet.out.recorded, false);
  assert.equal(existsSync(join(dir, "proactivity", "state.json")), false);
});

test("unreadable config, a loose counter, and a symlink fail closed", async () => {
  const dir = home();
  const folder = join(dir, "proactivity");
  mkdirSync(folder);
  writeFileSync(join(folder, "config.json"), "{");
  writeZone(dir);
  const broken = await run(dir, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(broken.out.reason, "config_invalid");
  writeFileSync(join(folder, "config.json"), JSON.stringify({ enabled: true }));
  chmodSync(folder, 0o777);
  const loose = await run(dir, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(loose.out.reason, "state_unreadable");
  assert.equal(loose.out.wakeAgent, false);
  const other = home();
  const linked = join(other, "proactivity");
  mkdirSync(linked);
  symlinkSync(join(folder, "config.json"), join(linked, "config.json"));
  writeZone(other);
  const link = await run(other, ["gate", "--kind", "brief", "--now", AFTERNOON]);
  assert.equal(link.out.reason, "config_unreadable");
});
