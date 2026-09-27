// Contract + behaviour test for the `smartlead-campaigns` skill (no network beyond 127.0.0.1).
// Routing: Hermes shows only the first 57 characters of a skill description in the system-prompt
// index (agent/skill_utils.py SKILL_PROMPT_DESC_LIMIT = 60 — see tests/circle-member-token.test.mjs).
// Behaviour: runs the REAL skills/smartlead-campaigns/scripts/smartlead.py (python3) against one local
// HTTP server that plays both the AdvisorReach API's /smartlead/v1 mount and SmartLead's /api/v1.
// Request shapes asserted here are the SmartLead Connector's tested ones (wttc/smartlead
// component-src/SmartLead Connector/Queries: create-campaign, save-sequences, set-schedule, …).
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createServer } from "node:http";
import { execFile } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const skillDir = join(here, "..", "skills", "smartlead-campaigns");
const skill = readFileSync(join(skillDir, "SKILL.md"), "utf8");
const script = join(skillDir, "scripts", "smartlead.py");
const SKILL_PROMPT_DESC_LIMIT = 60;
const KEY = "sl-client-key-not-real-0123456789abcdef0000";

function description(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const m = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(m, "description is a double-quoted single line");
  return { fm: fm[1], desc: m[1] };
}

test("index prefix (first 57 chars) names SmartLead campaigns and the actions", () => {
  const { desc } = description(skill);
  assert.equal(desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3), "SmartLead cold-email campaigns: see, stats, write, launch");
});

test("routes campaigns here, away from the retired MAB workflow, and declares the env vars", () => {
  const { fm, desc } = description(skill);
  assert.match(desc, /not the OmegaAI MAB\/Design workflow/);
  for (const v of ["ADVISORREACH_API_URL", "ADVISORREACH_API_KEY"]) assert.match(fm, new RegExp("^  - " + v + "$", "m"));
  assert.match(skill, /This skill is the ONLY way to see or change the customer's SmartLead campaigns/);
  assert.match(skill, /python3 \/opt\/data\/skills\/smartlead-campaigns\/scripts\/smartlead\.py campaigns/);
});

function fake({ clients = [{ client_id: 562337, name: "Ray Lopez", email: "closings@raylopezteam.com" }], slStatus = 200 } = {}) {
  const state = { requests: [] };
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const url = new URL(req.url, "http://x");
      state.requests.push({ method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), headers: req.headers, body });
      const send = (code, obj) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
      if (url.pathname === "/smartlead/v1/clients") return send(200, clients);
      const m = url.pathname.match(/^\/smartlead\/v1\/clients\/(\d+)\/api-key$/);
      if (m) return send(200, { client_id: Number(m[1]), api_keys: [KEY] });
      if (!url.pathname.startsWith("/api/v1/")) return send(404, { message: "not found" });
      if (url.searchParams.get("api_key") !== KEY) return send(401, { message: "API key is required." });
      if (slStatus !== 200) return send(slStatus, { message: "nope" });
      const p = url.pathname.slice("/api/v1".length);
      if (p === "/campaigns" && req.method === "GET") return send(200, [{ id: 11, name: "Orlando agents", status: "DRAFTED", created_at: "2026-09-14T06:51:52.610Z", user_id: 9 }]);
      if (p === "/campaigns/11/analytics") return send(200, { id: 11, name: "Orlando agents", status: "ACTIVE", sent_count: "40", open_count: "12", reply_count: "3", bounce_count: "1", unique_sent_count: "40", unique_open_count: "10", click_count: "0", unsubscribed_count: "0", total_count: "50", drafted_count: "10" });
      if (p === "/campaigns/11/sequences" && req.method === "GET") return send(200, [{ seq_number: 1, subject: "Hi", email_body: "<p>Hello {{first_name}}</p>", seq_delay_details: { delay_in_days: 0 } }]);
      if (p === "/email-accounts/") return send(200, [{ id: 22545576, from_email: "ray.lopez@raylopezrealty.com", is_smtp_success: true, is_imap_success: true }]);
      if (p === "/campaigns/create") return send(200, { ok: true, id: 12, name: JSON.parse(body).name });
      if (p.match(/^\/campaigns\/12\/(sequences|leads|email-accounts|schedule|status)$/)) return send(200, { ok: true });
      return send(404, { message: "not found" });
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, state, base: `http://127.0.0.1:${server.address().port}` })));
}

function run(base, ...args) {
  return new Promise((resolve) => {
    execFile("python3", [script, ...args], {
      env: { PATH: process.env.PATH, ADVISORREACH_API_URL: base, ADVISORREACH_API_KEY: "ar_live_testpfx_testsecret", SMARTLEAD_API_BASE: base + "/api/v1" },
    }, (err, stdout) => resolve({ code: err ? err.code : 0, raw: stdout, out: JSON.parse(stdout) }));
  });
}

test("reads: account, campaigns, stats, sequences, mailboxes — key sent as api_key, never printed", async () => {
  const { server, state, base } = await fake();
  try {
    assert.deepEqual((await run(base, "account")).out, { ok: true, client_id: 562337, name: "Ray Lopez", email: "closings@raylopezteam.com" });
    const c = await run(base, "campaigns");
    assert.deepEqual(c.out, { ok: true, campaigns: [{ id: 11, name: "Orlando agents", status: "DRAFTED", created_at: "2026-09-14T06:51:52.610Z" }] });
    assert.ok(!c.raw.includes(KEY), "the key never appears in output");
    const sl = state.requests.filter((r) => r.path.startsWith("/api/v1/"));
    assert.equal(sl.at(-1).query.api_key, KEY);
    assert.equal(sl.at(-1).headers["user-agent"], "advisorreach-box/1.0");
    assert.equal(state.requests.find((r) => r.path === "/smartlead/v1/clients").headers.authorization, "Bearer ar_live_testpfx_testsecret");
    const s = await run(base, "stats", "11");
    assert.equal(s.out.sent_count, "40");
    assert.equal(s.out.reply_count, "3");
    assert.equal(s.out.status, "ACTIVE");
    const q = await run(base, "sequences", "11");
    assert.deepEqual(q.out.sequences, [{ seq_number: 1, subject: "Hi", email_body: "<p>Hello {{first_name}}</p>", delay_in_days: 0 }]);
    const m = await run(base, "mailboxes");
    assert.deepEqual(m.out.mailboxes, [{ id: 22545576, from_email: "ray.lopez@raylopezrealty.com", sending_ok: true, receiving_ok: true }]);
    assert.deepEqual(state.requests.find((r) => r.path === "/api/v1/email-accounts/").query, { offset: "0", limit: "100", api_key: KEY });
  } finally { server.close(); }
});

test("writes send the SmartLead Connector's exact bodies", async () => {
  const { server, state, base } = await fake();
  const dir = mkdtempSync(join(tmpdir(), "sl-"));
  const seqFile = join(dir, "seq.json");
  const leadFile = join(dir, "leads.json");
  const seqs = [{ seq_number: 1, seq_delay_details: { delay_in_days: 0 }, subject: "Hi", email_body: "Hello {{first_name}}" }];
  writeFileSync(seqFile, JSON.stringify(seqs));
  writeFileSync(leadFile, JSON.stringify([{ email: "a@b.com", first_name: "A" }]));
  const last = (p) => JSON.parse(state.requests.filter((r) => r.path === p).at(-1).body);
  try {
    assert.deepEqual((await run(base, "create", "Orlando test")).out, { ok: true, campaign_id: 12, name: "Orlando test", status: "DRAFTED" });
    assert.deepEqual(last("/api/v1/campaigns/create"), { name: "Orlando test" });
    assert.equal((await run(base, "save-sequences", "12", "--file", seqFile)).out.emails_saved, 1);
    assert.deepEqual(last("/api/v1/campaigns/12/sequences"), { sequences: seqs });
    await run(base, "add-leads", "12", "--file", leadFile);
    assert.deepEqual(last("/api/v1/campaigns/12/leads"), { lead_list: [{ email: "a@b.com", first_name: "A" }] });
    await run(base, "attach-mailboxes", "12", "22545576");
    assert.deepEqual(last("/api/v1/campaigns/12/email-accounts"), { email_account_ids: [22545576] });
    await run(base, "schedule", "12", "--timezone", "America/New_York");
    assert.deepEqual(last("/api/v1/campaigns/12/schedule"), { timezone: "America/New_York", days_of_the_week: [1, 2, 3, 4, 5], start_hour: "09:00", end_hour: "17:00", min_time_btw_emails: 20, max_new_leads_per_day: 50 });
    assert.deepEqual((await run(base, "start", "12")).out, { ok: true, campaign_id: "12", status: "START" });
    assert.deepEqual(last("/api/v1/campaigns/12/status"), { status: "START" });
    await run(base, "pause", "12");
    assert.deepEqual(last("/api/v1/campaigns/12/status"), { status: "PAUSED" });
  } finally { server.close(); }
});

test("no account, several accounts, someone else's account, SmartLead refusing — all clean errors", async () => {
  let f = await fake({ clients: [] });
  try {
    const r = await run(f.base, "campaigns");
    assert.equal(r.code, 1);
    assert.match(r.out.error, /no SmartLead account yet/);
    assert.equal(f.state.requests.filter((q) => q.path.startsWith("/api/v1/")).length, 0);
  } finally { f.server.close(); }
  f = await fake({ clients: [{ client_id: 1, name: "A", email: "a@x" }, { client_id: 2, name: "B", email: "b@x" }] });
  try {
    const r = await run(f.base, "campaigns");
    assert.equal(r.code, 1);
    assert.match(r.out.error, /several SmartLead accounts/);
    assert.equal((await run(f.base, "--client-id", "3", "campaigns")).code, 1);
    assert.equal((await run(f.base, "--client-id", "2", "account")).out.name, "B");
  } finally { f.server.close(); }
  f = await fake({ slStatus: 401 });
  try {
    const r = await run(f.base, "campaigns");
    assert.equal(r.code, 1);
    assert.equal(r.out.status, 401);
    assert.ok(!r.raw.includes(KEY));
  } finally { f.server.close(); }
});
