// Hermetic contract test for the `connect-app` skill (no network, no docker).
// Pins the multi-account procedure (2026-09-21): COMPOSIO_MANAGE_CONNECTIONS takes toolkit
// OBJECTS with action/alias/account_id, the agent lists before adding, names a second account,
// confirms with list (never a repeated add), passes `account` on COMPOSIO_MULTI_EXECUTE_TOOL
// when several accounts exist, and never removes an account without an explicit yes.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const skill = readFileSync(join(here, "..", "skills", "connect-app", "SKILL.md"), "utf8");

test("frontmatter still names the skill's purpose (routing text untouched)", () => {
  const fm = skill.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  assert.match(fm[1], /^description: Connect any outside app Composio supports/m);
});

test("connecting starts with a side-effect-free list of connected accounts", () => {
  assert.match(skill, /\{"toolkits": \[\{"name": "<slug>", "action": "list"\}\]\}/);
  assert.match(skill, /has no side effects/);
});

test("a second account gets an alias, and an unnamed first account is renamed first", () => {
  assert.match(skill, /"action": "rename", "account_id": "<id from list>", "alias": "work"/);
  assert.match(skill, /"action": "add", "alias": "<alias or omit>"/);
  assert.match(skill, /up to 3 accounts per app/);
});

test("the post-sign-in check is ONE list call, never a repeated add", () => {
  assert.match(skill, /confirm with ONE `action: "list"` call/);
  assert.match(skill, /never repeat `add` to check/);
});

test("tool execution passes account by alias when several accounts exist, asks once if ambiguous", () => {
  assert.match(skill, /"account": "<alias or id>"/);
  assert.match(skill, /ask once, briefly \("Work or\n\s+personal Gmail\?"\)/);
  assert.match(skill, /With a single connected account, omit `account`\./);
});

test("removing an account needs an explicit yes; writes name the source account", () => {
  assert.match(skill, /^- `action: "remove"` deletes a connected account — only with the user's explicit yes/m);
  assert.match(skill, /and which account it goes from/);
});

test("an un-restarted box falls back to string toolkits for the session and says when a second account becomes possible", () => {
  const rule = skill.split("\n").filter((l) => l.includes("must be a list of strings")).length;
  assert.equal(rule, 1, "exactly one fallback rule for the pre-restart tool shape");
  assert.match(skill, /use `\{"toolkits": \["<slug>"\]\}` for\n\s+this session/);
  assert.match(skill, /a second account will be possible after the next update/);
});
