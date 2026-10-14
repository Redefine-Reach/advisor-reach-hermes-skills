// Learning loop (AX-2). The real script runs against a local fake of the
// box do-not-keep gate. No network, no Hermes, no customer data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const scriptPath = join(root, "skills", "learning-loop", "scripts", "learning_loop.py");
const skillPath = join(root, "skills", "learning-loop", "SKILL.md");
const gatePath = join(here, "fixtures", "learning-loop", "arin_donotkeep.py");
const judgePath = join(here, "fixtures", "learning-loop", "judge.py");
const skill = readFileSync(skillPath, "utf8");
const script = readFileSync(scriptPath, "utf8");
const daily = readFileSync(join(root, "skills", "daily-brief", "SKILL.md"), "utf8");
const dayOpen = readFileSync(join(root, "skills", "day-open-rollcall", "SKILL.md"), "utf8");

const BRIEF = "For my Daily Brief, put new leads first and keep it to 5 bullets";
const CONFIRM = "Saved. I'll use that next time.";
const FORGOT = "Forgot that.";

function run(home, args, extra = {}) {
  const env = {
    PATH: process.env.PATH,
    HOME: process.env.HOME || home,
    LANG: "C.UTF-8",
    PYTHONDONTWRITEBYTECODE: "1",
    HERMES_HOME: home,
    LEARNING_LOOP_TEST: "1",
    LEARNING_LOOP_JUDGE: judgePath,
    ARIN_DONOTKEEP_PY: gatePath,
    ...extra,
  };
  const proc = spawnSync("python3", [scriptPath, ...args], { env, encoding: "utf8" });
  let payload = null;
  try {
    payload = JSON.parse(proc.stdout || "null");
  } catch {
    payload = null;
  }
  const storePath = join(home, "learning", "loop.json");
  let store = null;
  if (existsSync(storePath)) store = JSON.parse(readFileSync(storePath, "utf8"));
  return { proc, payload, store, storePath };
}

function home() {
  return mkdtempSync(join(tmpdir(), "learning-loop-"));
}

test("skill routes preferences, memory questions, drafts, and the gate", () => {
  assert.match(skill, /^name: learning-loop$/m);
  const description = skill.match(/^description: "(.+)"$/m)[1];
  assert.equal(description.slice(0, 57), "Save owner or client preferences and learned draft style.");
  assert.match(skill, /does not ask for approval/);
  assert.match(skill, /Send that line to the owner only when `saved` is true/);
  assert.match(skill, /same correction/);
  assert.match(skill, /including the turn right after `\/new`/);
  assert.match(skill, /What do you remember about client A/);
  assert.match(skill, /forget` removes one preference/);
  assert.match(skill, /\/opt\/box\/arin_donotkeep\.py/);
  assert.match(skill, /Health details, Social Security numbers, and financial account numbers are never learned/);
  assert.match(skill, /Do not use `write_file`, `patch`, or a shell redirect/);
  assert.match(skill, /--action edit/);
  assert.match(skill, /--action send/);
  assert.match(skill, /--action skip/);
  assert.match(skill, /`show` lists the learned signals/);
  assert.match(skill, /Silent background review stays off/);
  assert.match(skill, /Do not call `memory`, Mem0, or `cronjob`/);
  assert.match(skill, /Texts use the `learning_loop` tool/);
  assert.match(skill, /On a text turn, the terminal and `execute_code` are refused/);
  assert.match(skill, /Call the box plugin tool `learning_loop`/);
  assert.match(skill, /Do not use `execute_code` on a text turn/);
  assert.match(skill, /`save-explicit`, `note-correction`, `record`, and `write-client-skill` are `save`/);
  assert.match(skill, /`apply`, `list`, `next`, `show`, and `status` are `show`/);
  assert.doesNotMatch(skill, /Run it from `execute_code` with an argument list/);
  assert.doesNotMatch(script, /I won't save health details/);
  assert.doesNotMatch(script, /background_review: true/);
  assert.doesNotMatch(script, /surgery/);
  assert.match(script, /on_pre_tool_call\(\n\s+"memory"/);
  assert.match(script, /"action": "add"/);
  assert.match(script, /BOX_DONOTKEEP/);
  assert.match(daily, /learning_loop\.py apply --kind daily-brief/);
  assert.match(daily, /including after `\/new`/);
  assert.match(dayOpen, /load `learning-loop` and run its script/);
  assert.match(dayOpen, /Do not ask for approval/);
  assert.match(dayOpen, /apply --kind daily-brief/);
});

test("explicit preference saves without approval and confirms only after read-back", () => {
  const dir = home();
  const saved = run(dir, ["save-explicit", "--scope", "owner", "--kind", "daily-brief", "--text", BRIEF]);
  assert.equal(saved.proc.status, 0, saved.proc.stderr);
  assert.equal(saved.payload.ok, true);
  assert.equal(saved.payload.saved, true);
  assert.equal(saved.payload.confirm, CONFIRM);
  assert.equal(saved.payload.say, null);
  assert.equal(saved.payload.gate, "allow");
  assert.equal(saved.store.preferences.length, 1);
  assert.equal(saved.store.preferences[0].text, BRIEF);
  assert.equal(saved.store.preferences[0].scope, "owner");
  assert.equal(saved.store.preferences[0].client, null);
  assert.equal(saved.store.preferences[0].source, "explicit");
  assert.equal(saved.store.preferences[0].kind, "daily-brief");
  assert.equal(saved.store.preferences[0].id, saved.payload.id);
  assert.doesNotMatch(JSON.stringify(saved.payload), /approve/i);

  const again = run(dir, ["save-explicit", "--scope", "owner", "--kind", "daily-brief", "--text", BRIEF]);
  assert.equal(again.payload.saved, false);
  assert.equal(again.payload.confirm, null);
  assert.equal(again.store.preferences.length, 1);
});

test("after a fresh process the Daily Brief preference is applied", () => {
  const dir = home();
  const saved = run(dir, ["save-explicit", "--scope", "owner", "--text", BRIEF]);
  assert.equal(saved.payload.confirm, CONFIRM);
  assert.equal(saved.store.preferences[0].kind, "daily-brief");
  const applied = run(dir, ["apply", "--kind", "daily-brief"]);
  assert.equal(applied.proc.status, 0);
  assert.equal(applied.payload.items.length, 1);
  assert.equal(applied.payload.items[0].text, BRIEF);
  assert.equal(applied.payload.confirm, null);
});

test("the same correction saves on the second time, for one scope only", () => {
  const dir = home();
  const text = "Put new leads first";
  const first = run(dir, ["note-correction", "--scope", "owner", "--kind", "daily-brief", "--text", text]);
  assert.equal(first.payload.ok, true);
  assert.equal(first.payload.saved, false);
  assert.equal(first.payload.confirm, null);
  assert.equal(first.store.preferences.length, 0);
  assert.equal(first.store.pending_corrections.length, 1);

  const other = run(dir, ["note-correction", "--scope", "client", "--client", "Client A", "--kind", "daily-brief", "--text", text]);
  assert.equal(other.payload.saved, false);
  assert.equal(other.payload.confirm, null);
  assert.equal(other.store.preferences.length, 0);

  const second = run(dir, ["note-correction", "--scope", "owner", "--kind", "daily-brief", "--text", text]);
  assert.equal(second.payload.saved, true);
  assert.equal(second.payload.confirm, CONFIRM);
  assert.equal(second.store.preferences.length, 1);
  assert.equal(second.store.preferences[0].source, "repeated-correction");
  assert.equal(second.store.preferences[0].scope, "owner");
  assert.equal(second.store.pending_corrections.length, 1);
  assert.equal(second.store.pending_corrections[0].scope, "client");
});

test("list for client A excludes the owner and client B, and forget removes one", () => {
  const dir = home();
  const a = run(dir, ["save-explicit", "--scope", "client", "--client", "Client A", "--kind", "daily-brief", "--text", "Client A likes morning calls"]);
  const b = run(dir, ["save-explicit", "--scope", "client", "--client", "Client B", "--kind", "daily-brief", "--text", "Client B likes afternoon calls"]);
  const owner = run(dir, ["save-explicit", "--scope", "owner", "--kind", "daily-brief", "--text", BRIEF]);
  assert.equal(a.payload.confirm, CONFIRM);
  assert.equal(b.payload.confirm, CONFIRM);
  assert.equal(owner.payload.confirm, CONFIRM);

  const listed = run(dir, ["list", "--scope", "client", "--client", "Client A"]);
  assert.equal(listed.payload.items.length, 1);
  assert.equal(listed.payload.items[0].client, "Client A");
  assert.equal(listed.payload.items[0].text, "Client A likes morning calls");
  assert.equal(listed.payload.confirm, null);

  const ownerList = run(dir, ["list", "--scope", "owner"]);
  assert.equal(ownerList.payload.items.length, 1);
  assert.equal(ownerList.payload.items[0].scope, "owner");

  const ambiguous = run(dir, ["forget", "--text", "calls"]);
  assert.equal(ambiguous.payload.ok, false);
  assert.equal(ambiguous.payload.confirm, null);
  assert.match(ambiguous.payload.say, /Which one/);
  assert.equal(ambiguous.store.preferences.length, 3);

  const forgot = run(dir, ["forget", "--id", a.payload.id]);
  assert.equal(forgot.payload.saved, true);
  assert.equal(forgot.payload.confirm, FORGOT);
  assert.equal(forgot.store.preferences.length, 2);
  assert.ok(forgot.store.preferences.every((row) => row.id !== a.payload.id));
  assert.ok(forgot.store.preferences.some((row) => row.client === "Client B"));
  assert.ok(forgot.store.preferences.some((row) => row.scope === "owner"));
});

test("health, SSN, and account data are not learned, and a missing gate writes nothing", () => {
  const dir = home();
  const cases = [
    ["Client A has knee surgery Monday", "I won't save health details."],
    ["Client A SSN is 000-00-0000", "I won't save Social Security numbers."],
    ["Client A account number is 0000000000", "I won't save financial account numbers."],
  ];
  for (const [text, say] of cases) {
    const explicit = run(dir, ["save-explicit", "--scope", "client", "--client", "Client A", "--text", text]);
    assert.equal(explicit.payload.ok, false, text);
    assert.equal(explicit.payload.saved, false);
    assert.equal(explicit.payload.confirm, null);
    assert.equal(explicit.payload.say, say);
    assert.equal(explicit.store, null);
    const noted = run(dir, ["note-correction", "--scope", "client", "--client", "Client A", "--text", text]);
    assert.equal(noted.payload.say, say);
    assert.equal(noted.store, null);
  }
  const blockedNote = run(dir, ["record", "--kind", "follow-up", "--action", "edit", "--note", "mention the surgery"]);
  assert.equal(blockedNote.payload.say, "I won't save health details.");
  assert.equal(blockedNote.store, null);

  const rule = run(dir, ["save-explicit", "--scope", "owner", "--text", "block-rule keep the old order"]);
  assert.equal(rule.payload.say, "Not saved: this matches a do-not-keep rule.");
  assert.equal(rule.store, null);

  writeFileSync(join(dir, "boom-judge.py"), "def judge(candidate, rules):\n    raise RuntimeError('boom')\n");
  const boom = run(dir, ["save-explicit", "--scope", "owner", "--text", BRIEF], { LEARNING_LOOP_JUDGE: join(dir, "boom-judge.py") });
  assert.equal(boom.payload.ok, false);
  assert.equal(boom.payload.confirm, null);
  assert.equal(boom.payload.say, "I couldn't save that right now.");
  assert.equal(boom.store, null);

  const missing = run(dir, ["save-explicit", "--scope", "owner", "--text", BRIEF], { ARIN_DONOTKEEP_PY: join(dir, "missing.py") });
  assert.equal(missing.payload.ok, false);
  assert.equal(missing.payload.confirm, null);
  assert.equal(missing.payload.say, "I couldn't save that right now.");
  assert.equal(missing.payload.gate, "missing");
  assert.equal(missing.store, null);
});

test("edit, send, and skip record a signal the next draft of that kind uses", () => {
  const dir = home();
  const edited = run(dir, ["record", "--kind", "follow-up", "--action", "edit", "--note", "shorter, no exclamation"]);
  assert.equal(edited.payload.saved, true);
  assert.equal(edited.payload.confirm, null);
  assert.equal(edited.store.signals[0].signal, "style");
  assert.equal(edited.store.signals[0].note, "shorter, no exclamation");
  assert.doesNotMatch(JSON.stringify(edited.store), /draft body/i);

  const sent = run(dir, ["record", "--kind", "follow-up", "--action", "send"]);
  assert.equal(sent.payload.saved, true);
  assert.equal(sent.store.signals[1].signal, "acted-on");
  assert.equal(sent.store.signals[1].action, "send");
  assert.equal(sent.store.signals[1].note, "");

  const skipped = run(dir, ["record", "--kind", "follow-up", "--action", "skip"]);
  assert.equal(skipped.store.signals[2].action, "skip");
  assert.equal(skipped.store.signals[2].signal, "acted-on");

  const refused = run(dir, ["record", "--kind", "follow-up", "--action", "send", "--note", "the whole draft"]);
  assert.equal(refused.payload.ok, false);
  assert.equal(refused.store.signals.length, 3);

  const next = run(dir, ["next", "--kind", "follow-up"]);
  assert.deepEqual(next.payload.style, ["shorter, no exclamation"]);
  assert.equal(next.payload.items.length, 3);
  const other = run(dir, ["next", "--kind", "daily-brief"]);
  assert.deepEqual(other.payload.style, []);
  assert.equal(other.payload.items.length, 0);

  const shown = run(dir, ["show"]);
  assert.equal(shown.payload.items.length, 3);
  assert.equal(shown.payload.confirm, null);
  const oneKind = run(dir, ["show", "--kind", "follow-up"]);
  assert.equal(oneKind.payload.items.length, 3);
});

test("a client procedure is written only by the script and listed for that client", () => {
  const dir = home();
  const wrote = run(dir, [
    "write-client-skill",
    "--client", "Client A",
    "--name", "listing prep",
    "--when", "they ask for a listing packet",
    "--step", "Confirm the property address",
    "--step", "Draft the packet and stop",
  ]);
  assert.equal(wrote.payload.saved, true);
  assert.equal(wrote.payload.confirm, CONFIRM);
  const skillFile = join(dir, "skills", wrote.payload.id, "SKILL.md");
  const body = readFileSync(skillFile, "utf8");
  assert.match(body, /This procedure is only for this client/);
  assert.match(body, /The learning-loop script wrote this file/);
  assert.match(body, /Client: Client A\n/);
  assert.match(body, /1\. Confirm the property address\n2\. Draft the packet and stop\n/);
  assert.doesNotMatch(body, /write_file/);

  const listed = run(dir, ["list", "--scope", "client", "--client", "Client A"]);
  assert.equal(listed.payload.procedures.length, 1);
  assert.equal(listed.payload.procedures[0].procedure, "listing-prep");
  const other = run(dir, ["list", "--scope", "client", "--client", "Client B"]);
  assert.equal(other.payload.procedures.length, 0);

  const blocked = run(dir, [
    "write-client-skill",
    "--client", "Client A",
    "--name", "health note",
    "--when", "they mention surgery",
    "--step", "Record the surgery date",
  ]);
  assert.equal(blocked.payload.say, "I won't save health details.");
  assert.equal(blocked.payload.confirm, null);
  assert.equal(existsSync(join(dir, "skills", "c-client-a--health-note", "SKILL.md")), false);

  const forgot = run(dir, ["forget", "--client", "Client A", "--procedure", "listing-prep"]);
  assert.equal(forgot.payload.confirm, FORGOT);
  assert.equal(existsSync(skillFile), false);
  const after = run(dir, ["list", "--scope", "client", "--client", "Client A"]);
  assert.equal(after.payload.procedures.length, 0);
});

test("status reports background review and does not change config", () => {
  const dir = home();
  const config = join(dir, "config.yaml");
  const body = "skills:\n  background_review: false\n";
  writeFileSync(config, body);
  const reported = run(dir, ["status"]);
  assert.equal(reported.payload.ok, true);
  assert.equal(reported.payload.background_review, "off");
  assert.equal(readFileSync(config, "utf8"), body);

  writeFileSync(config, "background_review: true\n");
  const on = run(dir, ["status"]);
  assert.equal(on.payload.background_review, "on");
  assert.equal(readFileSync(config, "utf8"), "background_review: true\n");

  const unset = run(home(), ["status"]);
  assert.equal(unset.payload.background_review, "unset");
});

test("apply does not leak another client's preference into the owner brief", () => {
  const dir = home();
  run(dir, ["save-explicit", "--scope", "client", "--client", "Client A", "--kind", "daily-brief", "--text", "Client A wants five bullets"]);
  const applied = run(dir, ["apply", "--kind", "daily-brief"]);
  assert.equal(applied.payload.items.length, 0);
  const named = run(dir, ["apply", "--kind", "daily-brief", "--client", "Client A"]);
  assert.equal(named.payload.items.length, 1);
  assert.equal(named.payload.items[0].client, "Client A");
});
