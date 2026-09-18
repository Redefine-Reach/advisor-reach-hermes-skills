import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "skills", "schedule-text");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");
const zones = readFileSync(join(dir, "references", "timezones.md"), "utf8");

test("discovery is limited to explicit scheduler operations", () => {
  assert.match(skill, /^name: schedule-text$/m);
  assert.match(skill, /explicit create, update, run, pause, or remove request/);
  assert.match(skill, /ordinary brief, draft, or current update does not create a job/);
});

test("delays remain scheduler-native while clock times use verified scheduler timezone", () => {
  assert.match(skill, /`in 20m`, `in 2h`/);
  assert.match(skill, /timezone from trusted preferences or known context; otherwise ask once/);
  assert.match(skill, /Inspect the actual configured scheduler timezone/);
  assert.match(skill, /verified IANA local walltime/);
  assert.doesNotMatch(skill, /convert to a UTC cron expression/);
  assert.doesNotMatch(zones, /America\/Chicago/);
});

test("timezone mismatch is a migration assessment, not a global mutation", () => {
  assert.match(skill, /do not change it globally/);
  assert.match(skill, /Assess affected jobs/);
  assert.match(skill, /coherent migration authority/);
});

test("brief jobs omit schedule-text and fire only a final response", () => {
  assert.match(skill, /`daily-brief` plus `day-open-rollcall` or `day-close-debrief`, never `schedule-text`/);
  assert.match(skill, /returns only its final response/);
});

test("creation and verification require persisted delivery recipient and local schedule", () => {
  assert.match(skill, /List before create, update, run, pause, resume, or remove/);
  assert.match(skill, /update it instead of creating a duplicate/);
  assert.match(skill, /verified gateway context/);
  assert.match(skill, /explicit verified authorized SMS target/);
  assert.match(skill, /Never leave a user SMS job with `deliver: local`/);
  assert.match(skill, /platform and recipient/);
  assert.match(skill, /next run and selected days/);
  assert.match(skill, /`deliver: origin` alone is not proof/);
  assert.match(skill, /CLI session without an origin cannot claim SMS success/);
  assert.match(skill, /`failure_deliver: local`/);
});

test("reminder runs stay final-only and send-now does not create a missing Brief Job", () => {
  assert.match(skill, /requested reminder as plain text under 300 characters/);
  assert.match(skill, /Do not make an extra send or job-management request while firing/);
  assert.match(skill, /Use `update`, `pause`, resume, or remove/);
  assert.match(skill, /run an existing matching authorized Brief Job after listing it/);
  assert.match(skill, /If none exists, compose the current requested brief; do not create or assume a job/);
});