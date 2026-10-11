// Hermetic contract test for team ARIN's `advisorreach-site` skill, the ARIN Lane (no network, no
// docker). Hermes shows only the first 57 characters of a skill description in the system-prompt index
// (agent/skill_utils.py SKILL_PROMPT_DESC_LIMIT = 60; see tests/circle-member-token.test.mjs), so the
// routing words are pinned here, along with the mechanics the site repo's arin-promote.yml depends on.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const site = readFileSync(join(here, "..", "skills", "advisorreach-site", "SKILL.md"), "utf8");
const SKILL_PROMPT_DESC_LIMIT = 60;

function description(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const m = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(m, "description is a double-quoted single line");
  return m[1];
}

test("advisorreach-site routes on the website and advisorreach.ai", () => {
  assert.equal(description(site).slice(0, SKILL_PROMPT_DESC_LIMIT - 3),
    "Edit and publish advisorreach.ai, the AdvisorReach websit");
});

test("advisorreach-site pushes only arin/ branches, by URL, and confirms the live release", () => {
  assert.match(site, /git\("push", URL, "HEAD:refs\/heads\/" \+ BRANCH\)/);
  assert.match(site, /BRANCH = "arin\/" \+ TOPIC/);
  assert.doesNotMatch(site, /refs\/heads\/production"\)\s*$/m);
  assert.match(site, /https:\/\/advisorreach\.ai\/release-identity\.json/);
  assert.match(site, /live_sha\(\) == sha/);
  assert.match(site, /URL = "https:\/\/github\.com\/Redefine-Reach\/advisorreach-site\.git"/);
  assert.match(site, /git-credential-wttc-oauth\.py/);
  assert.doesNotMatch(site, /git@github\.com|\/etc\/arin-git|GIT_SSH_COMMAND/);
});

test("a Lead Magnet page goes under public/m/<name>/ and needs no route edit by a person", () => {
  assert.match(site, /public\/m\/<name>\/index\.html/);
  assert.match(site, /accepts every page under `public\/m\/` on its own/);
});
