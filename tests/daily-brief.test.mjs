import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "skills", "daily-brief");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");
const gathering = readFileSync(join(dir, "references", "gathering.md"), "utf8");
const page = readFileSync(join(dir, "references", "brief-page.html"), "utf8");

test("discovery routes ordinary briefs to the coordinator and explicit jobs to schedule-text", () => {
  assert.match(skill, /^name: daily-brief$/m);
  assert.match(skill, /only when the user explicitly asks to create, change, run, pause, or remove a job/);
  assert.match(skill, /Only the last routes to `schedule-text`/);
});

test("composition delegates evidence and preferences to the applicable day skill", () => {
  assert.match(skill, /`day-open-rollcall` for a start-of-day brief/);
  assert.match(skill, /`day-close-debrief` for a wrap-up/);
  assert.match(skill, /does not duplicate gathering/);
  assert.match(gathering, /bounded Composio reads/);
  assert.match(gathering, /one relevant member-scoped Circle read/);
});

test("direct send-now runs only an existing authorized job and otherwise composes", () => {
  assert.match(skill, /list existing jobs and run the matching authorized Brief Job/);
  assert.match(skill, /If none exists, compose the currently requested brief without scheduling it/);
});

test("brief job loads the coordinator and day skill through workflow routing", () => {
  assert.match(skill, /`daily-brief` plus the appropriate day skill/);
  assert.match(skill, /never `schedule-text`/);
  assert.match(skill, /workflow routing, while runtime cron policy controls tool permissions/);
  assert.match(skill, /produces only its final response/);
});

test("SMS is the default and page delivery requires authority and safe presentation", () => {
  assert.match(skill, /Default SMS is plain text below 550 characters/);
  assert.match(skill, /valid public-sharing authority/);
  assert.match(skill, /HTML-escape every inserted source value/);
  assert.match(skill, /opaque unique `.html` filename/);
  assert.equal((page.match(/<script/g) || []).length, 0);
  assert.equal((page.match(/https?:\/\//g) || []).length, 0);
});

test("source-neutral notes preserve priority and honest status limits", () => {
  assert.match(gathering, /explicit unresolved customer requests and commitments/);
  assert.match(gathering, /not evidence of attendance, discussion, completion, or a decision/);
  assert.match(gathering, /last-touch status is unknown/);
});