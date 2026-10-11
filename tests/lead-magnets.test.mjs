// Hermetic contract test for the generic `lead-magnets` skill (no network, no docker). The skill is baked
// into every box (google-cloud-gke-customer-boxes docker/sms-box/Dockerfile copies skills/ whole), so it
// teaches how to build a Lead Magnet and names no particular one (Lead Magnet Factory plan U.10). Hermes
// shows only the first 57 characters of a skill description in the system-prompt index
// (agent/skill_utils.py SKILL_PROMPT_DESC_LIMIT = 60; see tests/circle-member-token.test.mjs), so the
// routing words are pinned here. scripts/form_capture.py runs under python3 against a local stand-in for
// the hosted OmegaAI MCP server (OMEGA_MCP_URL), in the shapes tests/git-credential-wttc-oauth.test.mjs
// uses; it proves the helper's own logic only. Form Capture itself is tested in the form-capture repo
// (tests/form-capture), and the box's /scripts/ endpoint in google-cloud-gke-customer-boxes
// (tests/test_box_scripts.py, tests/test_box_scripts_kind.sh).
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "skills", "lead-magnets");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");
const HELPER = join(dir, "scripts", "form_capture.py");
const helper = readFileSync(HELPER, "utf8");
const SKILL_PROMPT_DESC_LIMIT = 60;
const SECRET = "a".repeat(64);

function description(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const m = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(m, "description is a double-quoted single line");
  return m[1];
}

// A stand-in MCP server: list_workspaces answers a home workspace; `run` answers per FormCapture method.
async function standIn(methods) {
  const calls = [];
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => {
      const msg = JSON.parse(body);
      calls.push({ auth: req.headers.authorization, msg });
      if (!("id" in msg)) { res.writeHead(202); res.end(); return; }
      let payload = { ok: true, data: null };
      if (msg.method === "tools/call" && msg.params.name === "list_workspaces") {
        payload = { ok: true, data: { "home-app-id": "app-1" } };
      } else if (msg.method === "tools/call" && msg.params.name === "run") {
        const answer = methods[msg.params.arguments.method];
        payload = answer === undefined ? { ok: false, error: "PageNotFoundException" } : { ok: true, data: [answer] };
      }
      const reply = msg.method === "initialize"
        ? { jsonrpc: "2.0", id: msg.id, result: { protocolVersion: "2025-03-26", capabilities: {} } }
        : { jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text: JSON.stringify(payload) }] } };
      res.writeHead(200, { "Content-Type": "application/json", "mcp-session-id": "sess-1" });
      res.end(JSON.stringify(reply));
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return { calls, url: `http://127.0.0.1:${server.address().port}/mcp`, close: () => server.close() };
}

function runHelper(url, args, key = "key-1") {
  return new Promise((resolve) => {
    const child = spawn("python3", [HELPER, ...args], {
      env: { ...process.env, OMEGA_MCP_URL: url, MCP_QUERY_OMEGA_API_KEY: key, PYTHONDONTWRITEBYTECODE: "1" },
    });
    let stdout = "";
    child.stdout.on("data", (c) => { stdout += c; });
    child.on("close", (code) => resolve({ code, stdout, msg: JSON.parse(stdout.trim()) }));
  });
}

const runs = (calls) => calls.filter((c) => c.msg.params?.name === "run").map((c) => c.msg.params.arguments);

test("lead-magnets routes on lead magnets, web forms and Form Capture", () => {
  assert.equal(description(skill).slice(0, SKILL_PROMPT_DESC_LIMIT - 3),
    "Lead magnets and web forms: capture leads (Form Capture),");
});

test("lead-magnets is generic: it names no particular Lead Magnet, gate or delivery channel", () => {
  for (const text of [skill, helper]) {
    assert.doesNotMatch(text, /scorecard|gbp|google business|circle|smartlead|hdc|homes\.com/i);
    assert.doesNotMatch(text, /advisor-reach-internal|nadine|tf-canary/i);
  }
});

test("scripts live in the Scripts Directory, never the cron script folder, and never run as a server", () => {
  assert.match(skill, /SCRIPT = "\/opt\/data\/cgi-bin\/" \+ NAME/);
  assert.match(skill, /SCRIPT_URL = base \+ "\/scripts\/" \+ NAME/);
  assert.doesNotMatch(skill, /\/opt\/data\/scripts\//);
  assert.doesNotMatch(skill, /start_new_session|Popen/);
  assert.match(skill, /Idempotency-Key/);
  assert.match(skill, /Never start a server, a daemon or a cron job for a magnet\./);
  assert.match(skill, /hmac\.compare_digest\(os\.environ\.get\("HTTP_X_BOX_SCRIPT_SECRET", ""\), want\)/);
  assert.match(skill, /\/opt\/data\/skills\/lead-magnet-builds\/<NAME>\/SKILL\.md/);
});

test("the helper never installs Form Capture: it only calls the install's FormCapture methods", () => {
  assert.match(helper, /INSTALL_PAGE = "Component Installs\/Form Capture"/);
  assert.match(helper, /PROTOCOL = "FormCapture"/);
  assert.doesNotMatch(helper, /Installable|set_component|add_page/);
  assert.match(skill, /Never install, re-install or change the Form Capture component itself\./);
});

test("status answers the hook URL through the box's own key and home workspace", async () => {
  const s = await standIn({ endpoint: { status: "ok", "endpoint-url": "https://db.queryomega.com/hook/e-1" } });
  try {
    const r = await runHelper(s.url, ["status"]);
    assert.equal(r.code, 0);
    assert.deepEqual(r.msg, { ok: true, app_id: "app-1", page: "Component Installs/Form Capture",
      endpoint_url: "https://db.queryomega.com/hook/e-1" });
    assert.ok(s.calls.every((c) => c.auth === "Bearer key-1"));
    assert.deepEqual(runs(s.calls), [{ app_id: "app-1", page_path: "Component Installs/Form Capture",
      protocol: "FormCapture", method: "endpoint", args: [{}] }]);
  } finally { s.close(); }
});

test("status without Form Capture installed is a clean error", async () => {
  const s = await standIn({});
  try {
    const r = await runHelper(s.url, ["status"]);
    assert.equal(r.code, 1);
    assert.equal(r.msg.ok, false);
    assert.match(r.msg.error, /PageNotFoundException/);
  } finally { s.close(); }
});

test("add-webhook sends the secret from a 0600 file as X-Box-Script-Secret and never prints it", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "lm-"));
  const file = join(tmp, "secret");
  writeFileSync(file, SECRET + "\n");
  chmodSync(file, 0o600);
  const s = await standIn({ "add-webhook": { status: "added", id: "w-1" } });
  try {
    const r = await runHelper(s.url, ["add-webhook", "--url", "https://box.test/scripts/a-b", "--form", "a-b", "--header-file", file]);
    assert.equal(r.code, 0);
    assert.deepEqual(r.msg, { ok: true, id: "w-1", url: "https://box.test/scripts/a-b", form: "a-b", headers: ["X-Box-Script-Secret"] });
    assert.doesNotMatch(r.stdout, new RegExp(SECRET));
    assert.deepEqual(runs(s.calls)[0].args, [{ url: "https://box.test/scripts/a-b", form: "a-b", headers: { "X-Box-Script-Secret": SECRET } }]);
    chmodSync(file, 0o644);
    const loose = await runHelper(s.url, ["add-webhook", "--url", "https://box.test/scripts/a-b", "--header-file", file]);
    assert.equal(loose.code, 1);
    assert.match(loose.msg.error, /must be mode 0600/);
    const plain = await runHelper(s.url, ["add-webhook", "--url", "http://box.test/scripts/a-b"]);
    assert.equal(plain.code, 1);
    assert.match(plain.msg.error, /must start with https:\/\//);
  } finally { s.close(); }
});

test("list-webhooks shows header names, never values", async () => {
  const s = await standIn({ "list-webhooks": { status: "ok", items: [
    { id: "w-1", url: "https://box.test/scripts/a-b", form: "a-b", headers: { "X-Box-Script-Secret": SECRET }, "created-at": "t" },
    { id: "w-2", url: "https://other.test/x", form: "", headers: {}, "created-at": "t" }] } });
  try {
    const r = await runHelper(s.url, ["list-webhooks"]);
    assert.equal(r.code, 0);
    assert.doesNotMatch(r.stdout, new RegExp(SECRET));
    assert.deepEqual(r.msg.webhooks, [
      { id: "w-1", url: "https://box.test/scripts/a-b", form: "a-b", headers: ["X-Box-Script-Secret"] },
      { id: "w-2", url: "https://other.test/x", form: null, headers: [] }]);
  } finally { s.close(); }
});

test("remove-webhook --form removes exactly that form's webhooks", async () => {
  const s = await standIn({
    "list-webhooks": { status: "ok", items: [
      { id: "w-1", url: "u1", form: "a-b", headers: {} },
      { id: "w-2", url: "u2", form: "c-d", headers: {} },
      { id: "w-3", url: "u3", form: "a-b", headers: {} }] },
    "remove-webhook": { status: "removed", id: "x" } });
  try {
    const r = await runHelper(s.url, ["remove-webhook", "--form", "a-b"]);
    assert.equal(r.code, 0);
    assert.deepEqual(r.msg, { ok: true, removed: ["w-1", "w-3"] });
    assert.deepEqual(runs(s.calls).filter((a) => a.method === "remove-webhook").map((a) => a.args[0]), [{ id: "w-1" }, { id: "w-3" }]);
  } finally { s.close(); }
});

test("submissions passes the form filter and limit", async () => {
  const s = await standIn({ "list-submissions": { status: "ok", items: [{ id: "s-1", form: "a-b", fields: { name: "T" } }], skip: 0, limit: 5, total: 1 } });
  try {
    const r = await runHelper(s.url, ["submissions", "--form", "a-b", "--limit", "5"]);
    assert.equal(r.code, 0);
    assert.deepEqual(r.msg, { ok: true, total: 1, submissions: [{ id: "s-1", form: "a-b", fields: { name: "T" } }] });
    assert.deepEqual(runs(s.calls)[0].args, [{ limit: 5, form: "a-b" }]);
  } finally { s.close(); }
});

test("no OmegaAI key: one JSON line, exit 1, no network", async () => {
  const r = await runHelper("http://127.0.0.1:9/mcp", ["status"], "");
  assert.equal(r.code, 1);
  assert.equal(r.msg.ok, false);
  assert.match(r.msg.error, /MCP_QUERY_OMEGA_API_KEY is not set/);
});
