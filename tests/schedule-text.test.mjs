// Hermetic contract test for the `schedule-text` skill (no network, no docker).
// Guards the failure modes seen on the fleet on 2026-09-17 (box mackenzie-rasmus, job
// 710335da64d6): a job born with deliver=local (texted nobody) and a schedule written in the
// customer's local time on a UTC box (fired at 02:30 Central). Hermes puts only the first 57
// characters of a skill description into the system-prompt index (agent/skill_utils.py
// SKILL_PROMPT_DESC_LIMIT = 60), so the routing words must sit inside that window.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "skills", "schedule-text");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");
const zones = readFileSync(join(dir, "references", "timezones.md"), "utf8");

const SKILL_PROMPT_DESC_LIMIT = 60; // hermes agent/skill_utils.py — desc[:57] + "..."

function frontmatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(m, "frontmatter present");
  return m[1];
}
function description(fm) {
  const m = fm.match(/^description: "(.*)"$/m);
  assert.ok(m, 'description is a double-quoted single line');
  return m[1];
}

test("index prefix (first 57 chars) names reminders and scheduled texts", () => {
  const desc = description(frontmatter(skill));
  const shown = desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3);
  assert.equal(shown, "Reminders and scheduled texts: later, daily, weekly. Use ");
});

test("description carries the plain-English triggers, the change/stop cases, and the brief hand-off", () => {
  const desc = description(frontmatter(skill));
  for (const t of ["remind me in 20 minutes", "every weekday at 7:30", "stop the reminders", "daily-brief skill"]) {
    assert.ok(desc.includes(t), `description mentions '${t}'`);
  }
});

test("delivery rule: never local, verify with list, origin captured when deliver is omitted", () => {
  assert.match(skill, /Do NOT include `deliver` in a text conversation/);
  assert.match(skill, /Its `deliver` must be\n\s+`origin` or start with `telnyx_sms:`/);
  assert.match(skill, /^- Never create a job that is left with `deliver: local`/m);
  assert.match(skill, /`failure_deliver`: `local`/);
});

test("timezone rule: UTC box, ask once, convert to a UTC cron expression, delays untouched", () => {
  assert.match(skill, /The box's clock is UTC/);
  assert.match(skill, /which time zone are you in\?/);
  assert.match(skill, /`30 12 \* \* 1-5`/);
  assert.match(skill, /`30 13 \* \* 1-5`/);
  assert.match(skill, /^- Never write a clock-time schedule without converting/m);
  assert.match(skill, /Never hand-compute an absolute timestamp/);
  assert.match(skill, /pass the tool's own form \(`in 20m`, `in 2h`\)/);
});

test("fire-time: the job loads this skill; reminders stay short and plain; briefs go to daily-brief", () => {
  assert.match(skill, /`\["schedule-text"\]` for a plain reminder/);
  assert.match(skill, /`\["schedule-text", "daily-brief"\]` for a brief/);
  assert.match(skill, /under 300 characters for a reminder/);
  assert.match(skill, /^- A brief is a scheduled text whose content the `daily-brief` skill defines — load both\./m);
});

test("edits: list first; send-now is action run", () => {
  assert.match(skill, /Always `list` first, match by name, then `update`/);
  assert.match(skill, /"Send me one now" = `action: run` on the existing job/);
});

test("timezone table covers the seven US zones with both offsets and the DST windows", () => {
  for (const z of ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu"]) {
    assert.match(zones, new RegExp("^\\| " + z.replace("/", "\\/") + " \\|", "m"), z);
  }
  assert.match(zones, /\| America\/Chicago \|[^|]*\| 6 \| 5 \|/);
  assert.match(zones, /2026-03-08 → 2026-11-01, 2027-03-14 → 2027-11-07/);
  assert.match(zones, /`30 12 \* \* 1-5`/);
});
