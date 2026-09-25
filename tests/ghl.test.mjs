// Contract + behaviour test for the `ghl` skill (no network beyond 127.0.0.1, no docker).
// Routing: Hermes shows only the first 57 characters of a skill description in the
// system-prompt index (agent/skill_utils.py SKILL_PROMPT_DESC_LIMIT = 60 — see
// tests/circle-member-token.test.mjs), so the routing words must sit inside that window.
// Behaviour: runs the REAL skills/ghl/scripts/ghl.py (python3) against one local HTTP server
// that plays both the AdvisorReach API's /crm/v1 mount and GoHighLevel's REST API.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, existsSync, statSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createServer } from "node:http";
import { execFile } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const skillDir = join(here, "..", "skills", "ghl");
const skill = readFileSync(join(skillDir, "SKILL.md"), "utf8");
const script = join(skillDir, "scripts", "ghl.py");
const SKILL_PROMPT_DESC_LIMIT = 60;

function description(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const m = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(m, "description is a double-quoted single line");
  return { fm: fm[1], desc: m[1] };
}

test("index prefix (first 57 chars) names GoHighLevel and the actions", () => {
  const { desc } = description(skill);
  assert.equal(desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3), "GoHighLevel (GHL/LeadConnector) CRM: connect, read, write");
});

test("routes GHL away from Composio and declares the sandbox env vars", () => {
  const { fm, desc } = description(skill);
  assert.match(desc, /NOT a Composio\/connect-app app/);
  for (const v of ["ADVISORREACH_API_URL", "ADVISORREACH_API_KEY"]) {
    assert.match(fm, new RegExp("^  - " + v + "$", "m"));
  }
  assert.match(skill, /Do not open `connect-app`/);
  assert.match(skill, /python3 \/opt\/data\/skills\/ghl\/scripts\/ghl\.py status/);
});

// ---- behaviour against a local fake ------------------------------------------------------

function fakeServer() {
  const state = { claimStatus: 409, requests: [], ghl401Once: false };
  const token = (tag, extra = {}) => ({
    access_token: `at-${tag}`, token_type: "Bearer", expires_in: 86399, refresh_token: `rt-${tag}`,
    scope: "contacts.readonly contacts.write locations.readonly", userType: "Location",
    companyId: "fTIuHhbcAnvaYbqutWJm", locationId: "8lZ9fJmKPqGBpUhtLlDD", userId: "SnD70zqTOCqK5SIfedap", ...extra,
  });
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      state.requests.push({ method: req.method, url: req.url, headers: req.headers, body });
      const send = (code, obj) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
      if (req.url === "/crm/v1/connect") return send(200, { connect_url: "https://marketplace.gohighlevel.com/oauth/chooselocation?state=st-1", state: "st-1", expires_in_seconds: 1800 });
      if (req.url === "/crm/v1/claim") return state.claimStatus === 200 ? send(200, token("claimed")) : send(state.claimStatus, { detail: "x" });
      if (req.url === "/crm/v1/refresh") return send(200, token("refreshed"));
      if (req.url.startsWith("/locations/")) {
        if (state.ghl401Once) { state.ghl401Once = false; return send(401, { message: "Invalid JWT" }); }
        return send(200, { location: { id: req.url.split("/")[2], name: "Welcome to the Cause" } });
      }
      if (req.url === "/contacts/" && req.method === "POST") return send(201, { contact: JSON.parse(body) });
      return send(404, { message: "not found" });
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, state, base: `http://127.0.0.1:${server.address().port}` })));
}

function run(base, home, ...args) {
  return new Promise((resolve) => {
    execFile("python3", [script, ...args], {
      env: { PATH: process.env.PATH, HERMES_HOME: home, ADVISORREACH_API_URL: base, ADVISORREACH_API_KEY: "ar_live_testpfx_testsecret", GHL_API_BASE: base },
    }, (err, stdout) => resolve({ code: err ? err.code : 0, out: JSON.parse(stdout) }));
  });
}

test("connect → claim (pending, then ready) → status → disconnect", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "ghl-"));
  try {
    const c = await run(base, home, "connect");
    assert.equal(c.code, 0);
    assert.equal(c.out.connect_url, "https://marketplace.gohighlevel.com/oauth/chooselocation?state=st-1");
    assert.equal(state.requests[0].headers.authorization, "Bearer ar_live_testpfx_testsecret");
    assert.deepEqual((await run(base, home, "status")).out, { connected: false, pending: true });

    const early = await run(base, home, "claim");
    assert.equal(early.code, 2);
    assert.equal(early.out.pending, true);
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { state: "st-1" });

    state.claimStatus = 200;
    const done = await run(base, home, "claim");
    assert.equal(done.code, 0);
    assert.equal(done.out.location_id, "8lZ9fJmKPqGBpUhtLlDD");
    assert.ok(!JSON.stringify(done.out).includes("at-claimed"), "claim never prints the token");
    const tokenFile = join(home, "ghl", "token.json");
    assert.equal(statSync(tokenFile).mode & 0o777, 0o600);
    assert.equal(JSON.parse(readFileSync(tokenFile, "utf8")).access_token, "at-claimed");
    assert.ok(!existsSync(join(home, "ghl", "pending.json")));

    const s = await run(base, home, "status");
    assert.equal(s.out.connected, true);
    assert.equal(s.out.access_token_expired, false);
    assert.equal(s.out.pending, false);

    const d = await run(base, home, "disconnect");
    assert.deepEqual(d.out, { ok: true, connected: false });
    assert.ok(!existsSync(tokenFile));
  } finally { server.close(); }
});

function seedToken(home, fields) {
  mkdirSync(join(home, "ghl"), { recursive: true });
  const now = Math.floor(Date.now() / 1000);
  writeFileSync(join(home, "ghl", "token.json"), JSON.stringify({
    access_token: "at-saved", refresh_token: "rt-saved", userType: "Location",
    locationId: "8lZ9fJmKPqGBpUhtLlDD", scope: "contacts.readonly", obtained_at: now, expires_at: now + 80000, ...fields,
  }), { mode: 0o600 });
}

test("api substitutes {locationId} and sends the token + Version header", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "ghl-"));
  seedToken(home, {});
  try {
    const r = await run(base, home, "api", "GET", "/locations/{locationId}");
    assert.equal(r.code, 0);
    assert.deepEqual(r.out, { status: 200, body: { location: { id: "8lZ9fJmKPqGBpUhtLlDD", name: "Welcome to the Cause" } } });
    const req = state.requests.at(-1);
    assert.equal(req.headers.authorization, "Bearer at-saved");
    assert.equal(req.headers.version, "2021-07-28");
    assert.equal(req.headers["user-agent"], "advisorreach-box/1.0");

    const w = await run(base, home, "api", "POST", "/contacts/", "--data", '{"locationId": "{locationId}", "firstName": "Jane"}');
    assert.equal(w.out.status, 201);
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { locationId: "8lZ9fJmKPqGBpUhtLlDD", firstName: "Jane" });
  } finally { server.close(); }
});

test("api refreshes an expiring token through /crm/v1/refresh and saves the new one", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "ghl-"));
  seedToken(home, { expires_at: Math.floor(Date.now() / 1000) + 60 });
  try {
    const r = await run(base, home, "api", "GET", "/locations/{locationId}");
    assert.equal(r.out.status, 200);
    const refresh = state.requests.find((q) => q.url === "/crm/v1/refresh");
    assert.deepEqual(JSON.parse(refresh.body), { refresh_token: "rt-saved", user_type: "Location" });
    assert.equal(state.requests.at(-1).headers.authorization, "Bearer at-refreshed");
    assert.equal(JSON.parse(readFileSync(join(home, "ghl", "token.json"), "utf8")).refresh_token, "rt-refreshed");
  } finally { server.close(); }
});

test("api retries once after a 401 with a refreshed token", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "ghl-"));
  seedToken(home, {});
  state.ghl401Once = true;
  try {
    const r = await run(base, home, "api", "GET", "/locations/{locationId}");
    assert.equal(r.out.status, 200);
    assert.deepEqual(state.requests.map((q) => q.url), ["/locations/8lZ9fJmKPqGBpUhtLlDD", "/crm/v1/refresh", "/locations/8lZ9fJmKPqGBpUhtLlDD"]);
  } finally { server.close(); }
});

test("api without a saved token says so and calls nothing", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "ghl-"));
  try {
    const r = await run(base, home, "api", "GET", "/locations/{locationId}");
    assert.equal(r.code, 1);
    assert.equal(r.out.connected, false);
    assert.equal(state.requests.length, 0);
  } finally { server.close(); }
});
