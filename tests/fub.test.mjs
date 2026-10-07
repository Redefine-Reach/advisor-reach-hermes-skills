// Contract + behaviour test for the `fub` skill (no network beyond 127.0.0.1, no docker).
// Routing: Hermes shows only the first 57 characters of a skill description in the
// system-prompt index (agent/skill_utils.py SKILL_PROMPT_DESC_LIMIT = 60 — see
// tests/ghl.test.mjs). The index window must name FUB and say this is not Composio.
// Behaviour: runs the REAL skills/fub/scripts/fub.py (python3) against one local HTTP
// server that plays both the AdvisorReach API's /fub/v1 mount and Follow Up Boss.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, existsSync, statSync, mkdirSync, chmodSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createServer } from "node:http";
import { execFile } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const skillDir = join(here, "..", "skills", "fub");
const skill = readFileSync(join(skillDir, "SKILL.md"), "utf8");
const script = join(skillDir, "scripts", "fub.py");
const SKILL_PROMPT_DESC_LIMIT = 60;
const ACCESS = "at-claimed-0123456789abcdef";
const REFRESH = "rt-claimed-0123456789abcdef";
const SAVED_ACCESS = "at-saved-0123456789abcdef";
const SAVED_REFRESH = "rt-saved-0123456789abcdef";
const SYSTEM_KEY = "fleet-system-key-should-not-persist";

function description(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const m = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(m, "description is a double-quoted single line");
  return { fm: fm[1], desc: m[1] };
}

test("index prefix (first 57 chars) names FUB and is not Composio", () => {
  const { desc } = description(skill);
  const shown = desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3);
  assert.equal(shown, "FUB CRM. NOT a Composio/connect-app app. Read and write. ");
  assert.ok(shown.includes("FUB"));
  assert.ok(shown.includes("NOT a Composio/connect-app app"));
  assert.match(desc, /Follow Up Boss/);
});

test("routes FUB away from Composio and declares only the AdvisorReach env vars", () => {
  const { fm, desc } = description(skill);
  assert.match(desc, /NOT a Composio\/connect-app app/);
  for (const v of ["ADVISORREACH_API_URL", "ADVISORREACH_API_KEY"]) {
    assert.match(fm, new RegExp("^  - " + v + "$", "m"));
  }
  const required = (fm.split("required_environment_variables:\n")[1] || "").split("\n").filter((line) => line.trim());
  assert.deepEqual(required, ["  - ADVISORREACH_API_URL", "  - ADVISORREACH_API_KEY"]);
  assert.doesNotMatch(fm, /FUB_API_KEY|FUB_SYSTEM/);
  assert.match(skill, /Do not open `connect-app`/);
  assert.match(skill, /never try to read the files in `\/opt\/data\/fub\/`/);
  assert.match(skill, /wait for yes/);
  assert.match(skill, /sms-send-confirmed/);
  assert.match(skill, /\/fub\/v1\/connect/);
  assert.match(skill, /\/fub\/v1\/claim/);
  assert.match(skill, /\/fub\/v1\/refresh/);
  assert.match(skill, /\/fub\/v1\/revoke/);
  assert.doesNotMatch(skill, /\/crm\/v1\/fub/);
  assert.doesNotMatch(readFileSync(script, "utf8"), /\/crm\/v1\/fub/);
  assert.match(skill, /api\.followupboss\.com/);
  assert.match(skill, /python3 \/opt\/data\/skills\/fub\/scripts\/fub\.py status/);
  assert.match(skill, /POST '\/people'/);
  assert.match(skill, /least one of a name/);
  assert.doesNotMatch(skill, /`POST \/people`, action plans/);
});

// ---- behaviour against a local fake ------------------------------------------------------

function fakeServer() {
  const state = {
    claimStatus: 409,
    revokeStatus: 200,
    claimOmitsSystem: false,
    refreshOmitsSystem: false,
    requests: [],
    fubStatus: 200,
    fubBody: null,
    fubHeaders: {},
    fub401Once: false,
  };
  const token = (tag, extra = {}) => ({
    access_token: tag === "saved" ? SAVED_ACCESS : `at-${tag}-0123456789abcdef`,
    token_type: "Bearer",
    expires_in: 3600,
    refresh_token: tag === "saved" ? SAVED_REFRESH : `rt-${tag}-0123456789abcdef`,
    scope: "people notes",
    account_id: "acct-1",
    user_id: "user-9",
    system: "AdvisorReach",
    system_key: SYSTEM_KEY,
    client_secret: "oauth-client-secret-should-not-persist",
    api_key: "fub-api-key-should-not-persist",
    ...extra,
  });
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      state.requests.push({ method: req.method, url: req.url, headers: req.headers, body });
      const send = (code, obj, extra = {}) => {
        res.writeHead(code, { "content-type": "application/json", ...extra });
        res.end(JSON.stringify(obj));
      };
      if (req.url === "/fub/v1/connect" && req.method === "POST") {
        return send(200, {
          connect_url: "https://app.followupboss.com/oauth/authorize?state=st-1",
          state: "st-1",
          expires_in_seconds: 1800,
        });
      }
      if (req.url === "/fub/v1/claim" && req.method === "POST") {
        if (state.claimStatus !== 200) return send(state.claimStatus, { detail: "x" });
        const claimed = token("claimed");
        if (state.claimOmitsSystem) delete claimed.system;
        return send(200, claimed);
      }
      if (req.url === "/fub/v1/refresh" && req.method === "POST") {
        const refreshed = token("refreshed");
        if (state.refreshOmitsSystem) delete refreshed.system;
        return send(200, refreshed);
      }
      if (req.url === "/fub/v1/revoke" && req.method === "POST") {
        return send(state.revokeStatus, state.revokeStatus === 200 ? { revoked: true } : { detail: "x" });
      }
      if (req.url.startsWith("/v1/")) {
        if (state.fub401Once) {
          state.fub401Once = false;
          return send(401, { errorMessage: "Invalid token" });
        }
        if (state.fubBody === "large") {
          res.writeHead(state.fubStatus, { "content-type": "application/json" });
          res.end(Buffer.alloc(1024 * 1024 + 1, 0x61));
          return;
        }
        const payload = state.fubBody || {
          label: "AdvisorReach demo",
          short: "abcde",
          system: "AdvisorReach",
          token: "abcde",
          people: [{ id: 7, name: "Jane Doe" }],
          _metadata: { nextLink: "https://api.followupboss.com/v1/people?limit=10&next=abc" },
        };
        return send(state.fubStatus, payload, state.fubHeaders);
      }
      return send(404, { message: "not found" });
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({
    server, state, base: `http://127.0.0.1:${server.address().port}`,
  })));
}

function run(base, home, args, extraEnv = {}) {
  return new Promise((resolve, reject) => {
    execFile("python3", [script, ...args], {
      env: {
        PATH: process.env.PATH,
        HERMES_HOME: home,
        ADVISORREACH_API_URL: base,
        ADVISORREACH_API_KEY: "ar_live_testpfx_testsecret",
        FUB_API_BASE: base,
        ...extraEnv,
      },
    }, (err, stdout, stderr) => {
      let out;
      try {
        out = JSON.parse(stdout);
      } catch (parseError) {
        reject(new Error(`not json (code ${err && err.code}): ${stdout}\n${stderr}`));
        return;
      }
      resolve({ code: err ? err.code : 0, out, stderr });
    });
  });
}

function seedToken(home, fields = {}) {
  const dir = join(home, "fub");
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  chmodSync(dir, 0o700);
  const now = Math.floor(Date.now() / 1000);
  const token = {
    access_token: SAVED_ACCESS,
    refresh_token: SAVED_REFRESH,
    token_type: "Bearer",
    system: "AdvisorReach",
    scope: "people notes",
    account_id: "acct-1",
    user_id: "user-9",
    obtained_at: now,
    expires_in: 80000,
    expires_at: now + 80000,
    ...fields,
  };
  const file = join(dir, "token.json");
  writeFileSync(file, JSON.stringify(token), { mode: 0o600 });
  chmodSync(file, 0o600);
  return token;
}

function fubRequests(state) {
  return state.requests.filter((q) => q.url.startsWith("/v1/"));
}

test("connect → claim (pending, then ready) → status → disconnect", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  try {
    const c = await run(base, home, ["connect"]);
    assert.equal(c.code, 0);
    assert.equal(c.out.connect_url, "https://app.followupboss.com/oauth/authorize?state=st-1");
    assert.equal(state.requests[0].headers.authorization, "Bearer ar_live_testpfx_testsecret");
    assert.equal(statSync(join(home, "fub")).mode & 0o777, 0o700);
    assert.equal(statSync(join(home, "fub", "pending.json")).mode & 0o777, 0o600);
    const st = await run(base, home, ["status"]);
    assert.deepEqual(st.out, { connected: false, pending: true, waiting_for_user: true });
    assert.equal(state.requests.at(-1).method, "POST");
    assert.equal(state.requests.at(-1).url, "/fub/v1/claim");

    const early = await run(base, home, ["claim"]);
    assert.equal(early.code, 2);
    assert.equal(early.out.pending, true);
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { state: "st-1" });

    state.claimStatus = 200;
    const done = await run(base, home, ["claim"]);
    assert.equal(done.code, 0);
    assert.equal(done.out.account_id, "acct-1");
    assert.equal(done.out.system, "AdvisorReach");
    const printed = JSON.stringify(done.out);
    assert.ok(!printed.includes(ACCESS), "claim never prints the access token");
    assert.ok(!printed.includes(REFRESH), "claim never prints the refresh token");
    assert.ok(!printed.includes(SYSTEM_KEY), "claim never prints the system key");
    assert.ok(!printed.includes("ar_live_testpfx_testsecret"));
    const tokenFile = join(home, "fub", "token.json");
    assert.equal(statSync(tokenFile).mode & 0o777, 0o600);
    const saved = JSON.parse(readFileSync(tokenFile, "utf8"));
    assert.equal(saved.access_token, ACCESS);
    assert.equal(saved.refresh_token, REFRESH);
    assert.equal(saved.system, "AdvisorReach");
    assert.equal(saved.system_key, undefined);
    assert.equal(saved.client_secret, undefined);
    assert.equal(saved.api_key, undefined);
    assert.ok(!existsSync(join(home, "fub", "pending.json")));

    const s = await run(base, home, ["status"]);
    assert.equal(s.code, 0);
    assert.equal(s.out.connected, true);
    assert.equal(s.out.access_token_expired, false);
    assert.equal(s.out.pending, false);
    assert.ok(!JSON.stringify(s.out).includes(ACCESS));

    const d = await run(base, home, ["disconnect"]);
    assert.deepEqual(d.out, { ok: true, connected: false, revoked: true });
    assert.ok(!JSON.stringify(d.out).includes(ACCESS));
    const revoke = state.requests.at(-1);
    assert.equal(revoke.method, "POST");
    assert.equal(revoke.url, "/fub/v1/revoke");
    assert.deepEqual(JSON.parse(revoke.body), { access_token: ACCESS });
    assert.ok(!existsSync(tokenFile));
  } finally { server.close(); }
});

test("status saves an approved token itself", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  try {
    await run(base, home, ["connect"]);
    state.claimStatus = 200;
    const s = await run(base, home, ["status"]);
    assert.equal(s.code, 0);
    assert.equal(s.out.connected, true);
    assert.equal(s.out.just_connected, true);
    assert.equal(s.out.account_id, "acct-1");
    const tokenFile = join(home, "fub", "token.json");
    assert.equal(statSync(tokenFile).mode & 0o777, 0o600);
    assert.ok(!existsSync(join(home, "fub", "pending.json")));
    assert.ok(!JSON.stringify(s.out).includes(ACCESS), "status never prints the token");
    assert.ok(!JSON.stringify(s.out).includes(SYSTEM_KEY));
  } finally { server.close(); }
});

test("api sends the bearer token and X-System name, never the system key", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  try {
    const r = await run(base, home, ["api", "GET", "/people?limit=10&name=Jane%20Doe"]);
    assert.equal(r.code, 0);
    assert.equal(r.out.status, 200);
    assert.equal(r.out.body.label, "AdvisorReach demo");
    assert.equal(r.out.body.short, "abcde");
    assert.equal(r.out.body.system, "AdvisorReach");
    assert.equal(r.out.body.token, "[REDACTED]");
    assert.equal(r.out.body._metadata.nextLink, "/people?limit=10&next=abc");
    const req = state.requests.at(-1);
    assert.equal(req.url, "/v1/people?limit=10&name=Jane%20Doe");
    assert.equal(req.headers.authorization, "Bearer " + SAVED_ACCESS);
    assert.equal(req.headers["x-system"], "AdvisorReach");
    assert.equal(req.headers["x-system-key"], undefined);
    assert.equal(req.headers["user-agent"], "advisorreach-box/1.0");
    assert.ok(!JSON.stringify(r.out).includes(SAVED_ACCESS));
  } finally { server.close(); }
});

test("api rewrites an absolute Follow Up Boss nextLink and rejects other hosts", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  try {
    const absolute = "https://api.followupboss.com/v1/people?limit=10&next=abc";
    const r = await run(base, home, ["api", "GET", absolute]);
    assert.equal(r.code, 0);
    assert.equal(state.requests.at(-1).url, "/v1/people?limit=10&next=abc");
    assert.equal(r.out.body._metadata.nextLink, "/people?limit=10&next=abc");

    const off = await run(base, home, ["api", "GET", "https://evil.example/v1/people"]);
    assert.notEqual(off.code, 0);
    assert.match(off.out.error, /relative API path/);
    assert.equal(fubRequests(state).length, 1);
  } finally { server.close(); }
});

test("api surfaces Retry-After and rate-limit headers on 429", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  state.fubStatus = 429;
  state.fubHeaders = {
    "retry-after": "8",
    "x-ratelimit-limit": "200",
    "x-ratelimit-remaining": "0",
    "x-ratelimit-window": "10",
    "x-ratelimit-context": "global",
  };
  state.fubBody = { errorMessage: "rate limit" };
  try {
    const r = await run(base, home, ["api", "GET", "/people?limit=10"]);
    assert.equal(r.code, 1);
    assert.equal(r.out.status, 429);
    assert.equal(r.out.retry_after, 8);
    assert.deepEqual(r.out.rate_limit, { limit: 200, remaining: 0, window: 10, context: "global" });
    assert.equal(r.out.outcome_unknown, undefined);
    assert.equal(fubRequests(state).length, 1);
  } finally { server.close(); }
});

test("write allowlist denies dangerous paths even with --confirm-write", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  const denied = [
    ["POST", "/events"],
    ["POST", "/actionPlansPeople"],
    ["POST", "/textMessages"],
    ["POST", "/emails"],
    ["POST", "/webhooks"],
    ["POST", "/users"],
    ["POST", "/people/42"],
    ["DELETE", "/people/42"],
    ["PATCH", "/people/42"],
    ["PUT", "/events/1"],
  ];
  try {
    for (const [method, path] of denied) {
      const before = state.requests.length;
      const r = await run(base, home, ["api", method, path, "--data", "{}", "--confirm-write"]);
      assert.notEqual(r.code, 0, method + " " + path);
      assert.match(r.out.error, /not on the write allowlist|is not allowed/);
      assert.equal(state.requests.length, before, method + " " + path + " must not call Follow Up Boss");
    }
    const stage = await run(base, home, ["api", "PUT", "/people/42", "--confirm-write", "--data", '{"stage": "Closed"}']);
    assert.notEqual(stage.code, 0);
    assert.match(stage.out.error, /stage/);
    assert.equal(fubRequests(state).length, 0);

    const queried = await run(base, home, ["api", "POST", "/notes?notify=1", "--confirm-write", "--data", '{"personId": 1, "body": "x"}']);
    assert.notEqual(queried.code, 0);
    assert.match(queried.out.error, /query string/);
    assert.equal(fubRequests(state).length, 0);

    const unconfirmed = await run(base, home, ["api", "POST", "/notes", "--data", '{"personId": 4242, "body": "Call back Thursday"}']);
    assert.notEqual(unconfirmed.code, 0);
    assert.match(unconfirmed.out.error, /wait for yes/);
    assert.equal(fubRequests(state).length, 0);

    const note = await run(base, home, ["api", "POST", "/notes", "--confirm-write", "--data", '{"personId": 4242, "subject": "Call", "body": "Call back Thursday"}']);
    assert.equal(note.code, 0);
    assert.equal(note.out.status, 200);
    assert.equal(state.requests.at(-1).method, "POST");
    assert.equal(state.requests.at(-1).url, "/v1/notes");
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { personId: 4242, subject: "Call", body: "Call back Thursday" });
    assert.equal(state.requests.at(-1).headers["x-system-key"], undefined);

    const person = await run(base, home, ["api", "PUT", "/people/42", "--confirm-write", "--data", '{"firstName": "Jane"}']);
    assert.equal(person.code, 0);
    assert.equal(state.requests.at(-1).method, "PUT");
    assert.equal(state.requests.at(-1).url, "/v1/people/42");
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { firstName: "Jane" });
  } finally { server.close(); }
});

test("POST /people creates a contact after --confirm-write and refuses unsafe bodies", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  const created = {
    firstName: "David",
    lastName: "Marshall",
    emails: [{ value: "david@example.com" }],
    phones: [{ value: "5550100" }],
  };
  try {
    const unconfirmed = await run(base, home, ["api", "POST", "/people", "--data", JSON.stringify(created)]);
    assert.notEqual(unconfirmed.code, 0);
    assert.match(unconfirmed.out.error, /wait for yes/);
    assert.equal(fubRequests(state).length, 0);

    const automation = await run(base, home, ["api", "POST", "/people", "--confirm-write", "--data", JSON.stringify({
      firstName: "David", stage: "Lead", source: "SMS", tags: ["vip"], assignedUserId: 9,
    })]);
    assert.notEqual(automation.code, 0);
    assert.match(automation.out.error, /stage/);
    assert.match(automation.out.error, /source/);
    assert.match(automation.out.error, /tags/);
    assert.match(automation.out.error, /assignedUserId/);
    assert.equal(fubRequests(state).length, 0);

    const noIdentity = await run(base, home, ["api", "POST", "/people", "--confirm-write", "--data", '{"background": "met at open house"}']);
    assert.notEqual(noIdentity.code, 0);
    assert.match(noIdentity.out.error, /requires a name, email, or phone/);
    assert.equal(fubRequests(state).length, 0);

    const blankName = await run(base, home, ["api", "POST", "/people", "--confirm-write", "--data", '{"firstName": "  ", "emails": [{"value": ""}]}']);
    assert.notEqual(blankName.code, 0);
    assert.match(blankName.out.error, /requires a name, email, or phone/);
    assert.equal(fubRequests(state).length, 0);

    const phoneOnly = await run(base, home, ["api", "POST", "/people", "--confirm-write", "--data", '{"phones": [{"value": "5550100", "type": "mobile"}]}']);
    assert.equal(phoneOnly.code, 0);
    assert.equal(phoneOnly.out.status, 200);
    assert.equal(state.requests.at(-1).method, "POST");
    assert.equal(state.requests.at(-1).url, "/v1/people");
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { phones: [{ value: "5550100", type: "mobile" }] });

    state.fubBody = { id: 99, name: "David Marshall" };
    const person = await run(base, home, ["api", "POST", "/people", "--confirm-write", "--data", JSON.stringify(created)]);
    assert.equal(person.code, 0);
    assert.equal(person.out.status, 200);
    assert.equal(person.out.body.id, 99);
    assert.equal(state.requests.at(-1).method, "POST");
    assert.equal(state.requests.at(-1).url, "/v1/people");
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), created);
    assert.equal(state.requests.at(-1).headers.authorization, "Bearer " + SAVED_ACCESS);
    assert.equal(fubRequests(state).length, 2);
  } finally { server.close(); }
});

test("data-file refuses the token file and other credential paths", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  const tokenFile = join(home, "fub", "token.json");
  try {
    const shipped = await run(base, home, ["api", "POST", "/notes", "--data-file", tokenFile, "--confirm-write"]);
    assert.notEqual(shipped.code, 0);
    assert.match(shipped.out.error, /credential|token/i);
    assert.ok(!JSON.stringify(shipped.out).includes(SAVED_ACCESS));
    assert.equal(fubRequests(state).length, 0);

    const homeJson = join(home, "notes.json");
    writeFileSync(homeJson, '{"personId": 1, "body": "home"}');
    const inHome = await run(base, home, ["api", "POST", "/notes", "--data-file", homeJson, "--confirm-write"]);
    assert.notEqual(inHome.code, 0);
    assert.match(inHome.out.error, /credential|token/i);
    assert.equal(fubRequests(state).length, 0);

    const named = join(mkdtempSync(join(tmpdir(), "fub-cred-")), "credentials.json");
    writeFileSync(named, '{"personId": 1, "body": "nope"}');
    const byName = await run(base, home, ["api", "POST", "/notes", "--data-file", named, "--confirm-write"]);
    assert.notEqual(byName.code, 0);
    assert.match(byName.out.error, /credential|token/i);
    assert.equal(fubRequests(state).length, 0);

    const link = join(mkdtempSync(join(tmpdir(), "fub-link-")), "note.json");
    symlinkSync(tokenFile, link);
    const viaLink = await run(base, home, ["api", "POST", "/notes", "--data-file", link, "--confirm-write"]);
    assert.notEqual(viaLink.code, 0);
    assert.match(viaLink.out.error, /link|credential|token/i);
    assert.equal(fubRequests(state).length, 0);

    const staging = join(mkdtempSync(join(tmpdir(), "fub-stage-")), "note.json");
    writeFileSync(staging, JSON.stringify({ personId: 7, body: "Call back Thursday" }));
    const ok = await run(base, home, ["api", "POST", "/notes", "--data-file", staging, "--confirm-write"]);
    assert.equal(ok.code, 0);
    assert.equal(ok.out.status, 200);
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { personId: 7, body: "Call back Thursday" });
    assert.ok(!state.requests.at(-1).body.includes(SAVED_ACCESS));
  } finally { server.close(); }
});

test("POSIX permissions fail closed and are not repaired", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  const dir = join(home, "fub");
  mkdirSync(dir, { recursive: true });
  chmodSync(dir, 0o755);
  const tokenFile = join(dir, "token.json");
  writeFileSync(tokenFile, JSON.stringify({
    access_token: SAVED_ACCESS, refresh_token: SAVED_REFRESH, system: "AdvisorReach", expires_at: 9_999_999_999,
  }), { mode: 0o600 });
  try {
    const looseDir = await run(base, home, ["status"]);
    assert.notEqual(looseDir.code, 0);
    assert.match(looseDir.out.error, /not private/);
    assert.equal(statSync(dir).mode & 0o777, 0o755);
    assert.equal(state.requests.length, 0);
    assert.ok(!JSON.stringify(looseDir.out).includes(SAVED_ACCESS));

    chmodSync(dir, 0o700);
    chmodSync(tokenFile, 0o644);
    const looseFile = await run(base, home, ["api", "GET", "/people"]);
    assert.notEqual(looseFile.code, 0);
    assert.match(looseFile.out.error, /not private/);
    assert.equal(statSync(tokenFile).mode & 0o777, 0o644);
    assert.equal(fubRequests(state).length, 0);
    assert.ok(!JSON.stringify(looseFile.out).includes(SAVED_ACCESS));
  } finally { server.close(); }
});

test("long token literals are redacted and the system name is not", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  state.fubBody = {
    label: "AdvisorReach demo",
    short: "abcde",
    system: "AdvisorReach",
    token: "abcde",
    echo: SAVED_ACCESS,
    _metadata: { nextLink: "https://api.followupboss.com/v1/people?limit=10&next=abc" },
  };
  try {
    const r = await run(base, home, ["api", "GET", "/me"]);
    assert.equal(r.code, 0);
    assert.equal(r.out.body.label, "AdvisorReach demo");
    assert.equal(r.out.body.short, "abcde");
    assert.equal(r.out.body.system, "AdvisorReach");
    assert.equal(r.out.body.token, "[REDACTED]");
    assert.equal(r.out.body.echo, "[REDACTED]");
    assert.equal(r.out.body._metadata.nextLink, "/people?limit=10&next=abc");
    assert.ok(!JSON.stringify(r.out).includes(SAVED_ACCESS));
  } finally { server.close(); }
});

test("a non-loopback FUB_API_BASE is refused before any request", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  try {
    const r = await run(base, home, ["api", "GET", "/people"], { FUB_API_BASE: "https://evil.example" });
    assert.notEqual(r.code, 0);
    assert.match(r.out.error, /host is fixed/);
    assert.equal(state.requests.length, 0);
  } finally { server.close(); }
});

test("api refreshes an expiring token and retries once after 401", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home, { expires_at: Math.floor(Date.now() / 1000) + 60 });
  try {
    const r = await run(base, home, ["api", "GET", "/people?limit=10"]);
    assert.equal(r.out.status, 200);
    const refresh = state.requests.find((q) => q.url === "/fub/v1/refresh");
    assert.deepEqual(JSON.parse(refresh.body), { refresh_token: SAVED_REFRESH });
    assert.equal(state.requests.at(-1).headers.authorization, "Bearer at-refreshed-0123456789abcdef");
    assert.equal(JSON.parse(readFileSync(join(home, "fub", "token.json"), "utf8")).refresh_token, "rt-refreshed-0123456789abcdef");
    assert.equal(JSON.parse(readFileSync(join(home, "fub", "token.json"), "utf8")).system_key, undefined);
  } finally { server.close(); }

  const second = await fakeServer();
  const home2 = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home2);
  second.state.fub401Once = true;
  try {
    const r = await run(second.base, home2, ["api", "GET", "/people?limit=10"]);
    assert.equal(r.out.status, 200);
    assert.deepEqual(second.state.requests.map((q) => q.url), [
      "/v1/people?limit=10",
      "/fub/v1/refresh",
      "/v1/people?limit=10",
    ]);
    assert.equal(second.state.requests.at(-1).headers.authorization, "Bearer at-refreshed-0123456789abcdef");
  } finally { second.server.close(); }
});

test("raw spaces are rejected before transport and do not claim an unknown write", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  try {
    const r = await run(base, home, ["api", "POST", "/notes extra", "--confirm-write", "--data", '{"personId": 1, "body": "x"}']);
    assert.notEqual(r.code, 0);
    assert.equal(r.out.outcome_unknown, undefined);
    assert.equal(fubRequests(state).length, 0);
  } finally { server.close(); }
});

test("api without a saved token says so and calls nothing", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  try {
    const r = await run(base, home, ["api", "GET", "/people"]);
    assert.equal(r.code, 1);
    assert.equal(r.out.connected, false);
    assert.equal(state.requests.length, 0);
  } finally { server.close(); }
});

test("FUB_READ_ONLY refuses allowlisted writes", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home);
  try {
    const r = await run(base, home, ["api", "POST", "/notes", "--confirm-write", "--data", '{"personId": 1, "body": "x"}'], { FUB_READ_ONLY: "1" });
    assert.notEqual(r.code, 0);
    assert.match(r.out.error, /writes are disabled/);
    assert.equal(fubRequests(state).length, 0);
    const read = await run(base, home, ["api", "GET", "/people?limit=10"], { FUB_READ_ONLY: "1" });
    assert.equal(read.code, 0);
    assert.equal(read.out.status, 200);
  } finally { server.close(); }
});

test("claim without a system name does not send X-System", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  state.claimOmitsSystem = true;
  try {
    await run(base, home, ["connect"]);
    state.claimStatus = 200;
    const done = await run(base, home, ["claim"]);
    assert.equal(done.code, 0);
    assert.equal(done.out.system, null);
    const saved = JSON.parse(readFileSync(join(home, "fub", "token.json"), "utf8"));
    assert.equal(saved.system, undefined);
    const read = await run(base, home, ["api", "GET", "/me"]);
    assert.equal(read.code, 0);
    assert.equal(state.requests.at(-1).headers["x-system"], undefined);
    assert.equal(state.requests.at(-1).headers.authorization, "Bearer " + ACCESS);
  } finally { server.close(); }
});

test("refresh that omits system keeps the stored X-System name", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  seedToken(home, { expires_at: Math.floor(Date.now() / 1000) + 60 });
  state.refreshOmitsSystem = true;
  try {
    const r = await run(base, home, ["api", "GET", "/people?limit=10"]);
    assert.equal(r.code, 0);
    const saved = JSON.parse(readFileSync(join(home, "fub", "token.json"), "utf8"));
    assert.equal(saved.system, "AdvisorReach");
    assert.equal(state.requests.at(-1).headers["x-system"], "AdvisorReach");
  } finally { server.close(); }
});

test("revoke failure keeps the local token; 409 still deletes it", async () => {
  const { server, state, base } = await fakeServer();
  const home = mkdtempSync(join(tmpdir(), "fub-"));
  const tokenFile = join(home, "fub", "token.json");
  seedToken(home);
  state.revokeStatus = 502;
  try {
    const failed = await run(base, home, ["disconnect"]);
    assert.equal(failed.code, 1);
    assert.equal(failed.out.connected, true);
    assert.match(failed.out.error, /could not revoke/);
    assert.equal(JSON.parse(readFileSync(tokenFile, "utf8")).access_token, SAVED_ACCESS);
    assert.equal(state.requests.at(-1).url, "/fub/v1/revoke");

    state.revokeStatus = 409;
    const gone = await run(base, home, ["disconnect"]);
    assert.deepEqual(gone.out, { ok: true, connected: false, revoked: false });
    assert.ok(!existsSync(tokenFile));
    assert.equal(state.requests.at(-1).url, "/fub/v1/revoke");
    assert.deepEqual(JSON.parse(state.requests.at(-1).body), { access_token: SAVED_ACCESS });
  } finally { server.close(); }
});

test("ADVISORREACH_API_URL allows in-cluster http *.svc.cluster.local", async () => {
  // _base_url is pure string validation (no DNS). Fleet boxes set
  // ADVISORREACH_API_URL=http://advisorreach-api.advisorreach-api.svc.cluster.local.
  const { execFileSync } = await import("node:child_process");
  const code = [
    "import importlib.util",
    "spec = importlib.util.spec_from_file_location('fub', " + JSON.stringify(script) + ")",
    "m = importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(m)",
    "assert m._base_url('http://advisorreach-api.advisorreach-api.svc.cluster.local', False) == 'http://advisorreach-api.advisorreach-api.svc.cluster.local'",
    "assert m._base_url('http://foo.bar.svc.cluster.local:8080', False) == 'http://foo.bar.svc.cluster.local:8080'",
    "assert m._base_url('http://evil.example', False) is None",
    "assert m._base_url('https://api.advisorreach.ai', False) == 'https://api.advisorreach.ai'",
    "print('ok')",
  ].join("\n");
  const out = execFileSync("python3", ["-c", code], { encoding: "utf-8" });
  assert.match(out, /ok/);
});
