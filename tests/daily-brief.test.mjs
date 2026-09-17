// Hermetic contract test for the `daily-brief` skill (no network, no docker).
// Guards the 2026-09-17 brief format failure (box mackenzie-rasmus, job 710335da64d6: a 3.1 KB
// markdown brief texted in five parts) and the division of labour: scheduling belongs to
// `schedule-text`, this skill owns the prompt template and the fire-time format.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "skills", "daily-brief");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");
const page = readFileSync(join(dir, "references", "brief-page.html"), "utf8");
const gathering = readFileSync(join(dir, "references", "gathering.md"), "utf8");

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

test("index prefix (first 57 chars) names the brief and says it is a scheduled text + page", () => {
  const desc = description(frontmatter(skill));
  const shown = desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3);
  assert.equal(shown, "Morning brief, daily update: a scheduled text + page. Use");
});

test("description hands scheduling to schedule-text", () => {
  const desc = description(frontmatter(skill));
  assert.ok(desc.includes("is the schedule-text skill"), "names schedule-text");
});

test("body defers the schedule to schedule-text (the present-file pattern) and never edits it here", () => {
  assert.match(skill, /is the\n`schedule-text` skill's job/);
  assert.match(skill, /`skills`: `\["schedule-text", "daily-brief"\]`/);
  assert.match(skill, /^- Never create or edit the schedule here — that is `schedule-text`/m);
});

test("prompt template pins the timezone line and the delivery-format paragraph", () => {
  assert.match(skill, /^User timezone: <IANA zone>\. Local send time:/m);
  assert.match(skill, /^DELIVERY FORMAT \(mandatory\)/m);
  assert.match(skill, /Morning-Brief-<YYYY-MM-DD>\.html/);
  assert.match(skill, /publish it with the present-file skill/);
  assert.match(skill, /under 550 characters of plain text/);
  assert.match(skill, /the line "Full brief: <link>"/);
  assert.match(skill, /No markdown, no bullets, no headings/);
});

test("fire-time rules: under 550, never invent, honest not-connected variant", () => {
  assert.match(skill, /^- Never text more than 550 characters from a Brief Job/m);
  assert.match(skill, /^- Never invent brief content/m);
  assert.match(skill, /Morning brief: nothing is connected yet/);
  assert.match(skill, /following `references\/gathering\.md`/);
});

test("brief page: AdvisorReach palette, no scripts, no external assets, mobile viewport", () => {
  assert.ok(page.includes("--ink:#141414"), "ink");
  assert.ok(page.includes("--paper:#f7f5f2"), "paper");
  assert.ok(page.includes("--gold:#b8892b"), "gold");
  assert.equal((page.match(/<script/g) || []).length, 0, "no <script>");
  assert.equal((page.match(/https?:\/\//g) || []).length, 0, "no external URLs");
  assert.match(page, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
  assert.match(page, /Top priorities/);
});

test("gathering rules: priority order, honest failure wording", () => {
  assert.match(gathering, /^1\. A closing or deadline that is today or tomorrow/m);
  assert.match(gathering, /"File visible" and "content parsed" are different claims/);
  assert.match(gathering, /Last-touch status unknown because sent mail was not checked/);
});
