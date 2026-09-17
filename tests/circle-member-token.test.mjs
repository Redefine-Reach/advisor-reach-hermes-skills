// Hermetic contract test for the `circle-member-token` skill (no network, no docker).
// Guards the routing + capability contract that failed on 2026-09-17 (box marc-king,
// session 20260914_172930_0f2bbd27): Hermes puts only the first 57 characters of a
// skill description into the system-prompt index (agent/skill_utils.py
// SKILL_PROMPT_DESC_LIMIT = 60), so the routing words must sit inside that window;
// and the skill must actually document finding a post and commenting on it.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const skill = readFileSync(join(here, "..", "skills", "circle-member-token", "SKILL.md"), "utf8");
const connectApp = readFileSync(join(here, "..", "skills", "connect-app", "SKILL.md"), "utf8");

const SKILL_PROMPT_DESC_LIMIT = 60; // hermes agent/skill_utils.py:1257 — desc[:57] + "..."

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

test("index prefix (first 57 chars) names Circle and the actions the agent routes on", () => {
  const desc = description(frontmatter(skill));
  const shown = desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3);
  assert.equal(shown, "Circle community (circle.so): read, search, post, comment");
});

test("description says Circle is not a Composio app", () => {
  const desc = description(frontmatter(skill));
  assert.match(desc, /NOT a Composio\/connect-app app/);
});

test("required env vars are declared for the sandbox passthrough", () => {
  const fm = frontmatter(skill);
  for (const v of ["ADVISORREACH_API_URL", "ADVISORREACH_API_KEY", "CIRCLE_MEMBERS_FILE"]) {
    assert.match(fm, new RegExp("^  - " + v + "$", "m"));
  }
});

test("body routes Circle requests here, never to connect-app / Composio", () => {
  assert.match(skill, /this skill is the ONLY way to reach it/);
  assert.match(skill, /do not open `connect-app`/);
  assert.match(skill, /do not call `COMPOSIO_SEARCH_TOOLS`/);
});

test("documents every Member API path needed to find a post and comment", () => {
  for (const p of [
    "/api/headless/v1/search/community_members",
    "/api/headless/v1/community_members/{community_member_id}/posts",
    "/api/headless/v1/spaces",
    "/api/headless/v1/spaces/{space_slug}/posts",
    "/api/headless/v1/search?search_text=",
    "/api/headless/v1/posts/{post_id}/comments",
    "/api/headless/v1/comments/{comment_id}/replies",
  ]) assert.ok(skill.includes(p), `missing ${p}`);
  assert.match(skill, /^## Finding a post$/m);
  assert.match(skill, /^## Commenting on a post$/m);
});

test("comment body shape is {comment:{body}} and posting needs an explicit yes", () => {
  assert.match(skill, /-d '\{"comment": \{"body": "/);
  assert.match(skill, /Post only after they say yes/);
});

test("search is documented as title-only helper, not the primary path", () => {
  assert.match(skill, /Search is title-only and is a helper, not the primary path/);
});

test("every curl in the new sections sets a User-Agent (Cloudflare 1010 rule)", () => {
  const start = skill.indexOf("## Finding a post");
  const end = skill.indexOf("## What this does NOT do");
  assert.ok(start > 0 && end > start);
  const section = skill.slice(start, end);
  const curls = section.split("\n").filter((l) => l.trim().startsWith("curl "));
  assert.ok(curls.length >= 5, `expected >=5 curl commands, got ${curls.length}`);
  const blocks = section.split(/\n\s*\n/).filter((b) => b.includes("curl "));
  for (const b of blocks) assert.match(b, /User-Agent: advisorreach-box\/1\.0/, "curl block without User-Agent:\n" + b);
});

test("connect-app hands Circle off to circle-member-token", () => {
  assert.match(connectApp, /^\*\*Not for Circle\.\*\* Circle \(circle\.so\) is AdvisorReach's own community, not a Composio app — use the `circle-member-token` skill for anything in Circle\.$/m);
});
