// Contract + behaviour test for the `feeder-markets` skill (no network beyond 127.0.0.1).
// Routing: Hermes shows only the first 57 characters of a skill description in the system-prompt
// index (agent/skill_utils.py SKILL_PROMPT_DESC_LIMIT = 60 — see tests/circle-member-token.test.mjs).
// Gating: metadata.hermes.requires_toolsets hides the skill unless the query-omega MCP server's
// toolset is loaded (agent/prompt_builder.py _skill_should_show; the toolset of an MCP server
// named X is "mcp-X", tools/mcp_tool.py).
// Behaviour: runs the REAL scripts (python3): feeder_markets.py against the small IRS/Census
// fixtures in tests/fixtures/feeder-markets (passed as --cache, named like the real files), and
// cas_pull.py against one local HTTP server that plays the hosted OmegaAI MCP server (JSON-RPC,
// SSE responses, mcp-session-id) and the CSV download. render.py needs WeasyPrint and is proven
// in the box image instead (google-cloud-gke-customer-boxes/tests/test_feeder_markets_box.sh).
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createServer } from "node:http";
import { execFile } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const skillDir = join(here, "..", "skills", "feeder-markets");
const skill = readFileSync(join(skillDir, "SKILL.md"), "utf8");
const analyzeScript = join(skillDir, "scripts", "feeder_markets.py");
const pullScript = join(skillDir, "scripts", "cas_pull.py");
const fixtures = join(here, "fixtures", "feeder-markets");
const SKILL_PROMPT_DESC_LIMIT = 60;

function frontmatter(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  const m = fm[1].match(/^description: "(.*)"$/m);
  assert.ok(m, "description is a double-quoted single line");
  return { fm: fm[1], desc: m[1] };
}

function run(script, args, env = {}) {
  return new Promise((resolve) => {
    execFile("python3", [script, ...args], { env: { ...process.env, ...env }, timeout: 60000 }, (err, stdout, stderr) => {
      resolve({ code: err ? err.code : 0, json: stdout.trim() ? JSON.parse(stdout.trim().split("\n").pop()) : null, stderr });
    });
  });
}

test("index prefix (first 57 chars) names feeder markets, the report, ZIPs and the agent CSV", () => {
  const { desc } = frontmatter(skill);
  assert.equal(desc.slice(0, SKILL_PROMPT_DESC_LIMIT - 3), "Feeder markets: migration report, scored ZIPs, agent CSV.");
});

test("only OmegaAI-connected boxes see it, and the key passes into the sandbox", () => {
  const { fm } = frontmatter(skill);
  assert.match(fm, /^metadata:\n  hermes:\n    requires_toolsets: \[mcp-query-omega\]$/m);
  assert.match(fm, /^required_environment_variables:\n  - MCP_QUERY_OMEGA_API_KEY$/m);
});

test("the body gives the exact script paths and hands the pull to Cas", () => {
  assert.match(skill, /python3 \/opt\/data\/skills\/feeder-markets\/scripts\/feeder_markets\.py analyze --dest "Orange County, FL"/);
  assert.match(skill, /\/opt\/hermes\/\.venv\/bin\/python \/opt\/data\/skills\/feeder-markets\/assets\/render\.py /);
  assert.match(skill, /python3 \/opt\/data\/skills\/feeder-markets\/scripts\/cas_pull\.py start --zips "<the line from zips-ab\.txt>" --max-agents 5000/);
  assert.match(skill, /python3 \/opt\/data\/skills\/feeder-markets\/scripts\/cas_pull\.py wait --session ses_\.\.\./);
  assert.match(skill, /Agents in\nthe user's own market are competitors — never pull them\./);
  assert.match(skill, /\*\*Run each command below as ONE plain command\*\* — in your terminal, or as a subprocess from\ncode execution, whichever you have\. Never wrap it in `\$\(…\)`, never chain with `&&` or `;`, never\nput `VAR=` in front: the terminal rejects compound commands\./);
});

test("analyze: out-of-state feeders ranked by moved income, ZIPs scored and tiered", async () => {
  const out = mkdtempSync(join(tmpdir(), "fm-"));
  const r = await run(analyzeScript, ["analyze", "--dest", "Orange County, FL", "--out", out, "--cache", fixtures]);
  assert.equal(r.code, 0, r.stderr);
  assert.equal(r.json.ok, true);
  assert.deepEqual(r.json.top_feeders, ["Los Angeles County, CA", "Cook County, IL", "Queens County, NY"]);
  assert.deepEqual(r.json.zips_ab, ["90210", "60043", "11109", "11101", "90011"]);
  assert.deepEqual(r.json.tiers, { A: 3, B: 2, C: 0 });
  const feeders = JSON.parse(readFileSync(join(out, "feeders.json"), "utf8"));
  assert.deepEqual(feeders.map((f) => [f.county, f.agi_moved, f.migration_score]), [
    ["Los Angeles County, CA", 55853000, 5],
    ["Cook County, IL", 42165000, 4],
    ["Queens County, NY", 36594000, 4],
  ]);
  const zips = JSON.parse(readFileSync(join(out, "zips.json"), "utf8"));
  assert.deepEqual(zips.map((z) => [z.zip, z.affluence_score, z.total, z.tier]), [
    ["90210", 5, 5, "A"], ["60043", 5, 4.45, "A"], ["11109", 4, 4, "A"], ["11101", 3, 3.55, "B"], ["90011", 1, 3.2, "B"],
  ]);
  assert.equal(readFileSync(join(out, "zips-ab.txt"), "utf8"), "90210 60043 11109 11101 90011\n");
  const summary = JSON.parse(readFileSync(join(out, "summary.json"), "utf8"));
  assert.equal(summary.destination_fips, "12095");
  assert.deepEqual(summary.inflow_totals, { returns: 4800, individuals: 8600, agi_thousands: 480000 });
});

test("analyze: --include-in-state adds same-state feeders; unknown county is an error", async () => {
  const out = mkdtempSync(join(tmpdir(), "fm-"));
  const r = await run(analyzeScript, ["analyze", "--dest", "Orange County, FL", "--out", out, "--cache", fixtures, "--include-in-state"]);
  assert.equal(r.code, 0, r.stderr);
  assert.deepEqual(r.json.top_feeders, ["Los Angeles County, CA", "Broward County, FL", "Cook County, IL", "Queens County, NY"]);
  const bad = await run(analyzeScript, ["analyze", "--dest", "Nowhere County, FL", "--out", out, "--cache", fixtures]);
  assert.equal(bad.code, 1);
  assert.deepEqual(bad.json, { ok: false, error: "no county named 'Nowhere County' in FL in the IRS inflow file" });
});

function fakeOmega({ finish = "stop", completed = true, text = null, textFor = null } = {}) {
  const state = { calls: [], sessionHeaders: [], auth: [] };
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const port = server.address().port;
      if (req.method === "GET" && req.url === "/f/Agent-Referrals-Test.csv") {
        res.writeHead(200, { "content-type": "text/csv" });
        return res.end("Query ZIP,Agent,Company,DB Rank,Email,FB Rank\r\n90210,,Acme,,a@x.com,\r\n60043,,Beta,,b@x.com,\r\n");
      }
      if (req.method === "GET" && req.url === "/download/tok.csv") {
        res.writeHead(200, { "content-type": "text/csv" });
        return res.end("Agent,Company,DB Rank,Email,FB Rank\r\n,Acme,,a@x.com,\r\n");
      }
      if (req.method === "GET" && req.url === "/f/not-a-referral-export.csv") {
        res.writeHead(200, { "content-type": "text/csv" });
        return res.end("name,phone\r\nx,1\r\n");
      }
      state.auth.push(req.headers.authorization);
      state.sessionHeaders.push(req.headers["mcp-session-id"] || null);
      const msg = JSON.parse(body);
      if (!("id" in msg)) { res.writeHead(202); return res.end(); }
      const sse = (result) => {
        res.writeHead(200, { "content-type": "text/event-stream", "mcp-session-id": "mcp-sess-1" });
        res.end("event: message\ndata: " + JSON.stringify({ jsonrpc: "2.0", id: msg.id, result }) + "\n\n");
      };
      if (msg.method === "initialize") return sse({ protocolVersion: "2025-03-26", capabilities: {}, serverInfo: { name: "query-omega-mcp", version: "2.0.0" } });
      const { name, arguments: args } = msg.params;
      state.calls.push({ name, args });
      const tool = (data) => sse({ content: [{ type: "text", text: JSON.stringify({ ok: true, command: name, data }) }] });
      if (name === "agent_create_session") return tool({ session: { sessionId: "ses_test123", appId: "app-1", serviceAccountId: "sa-1", userId: "service-account:sa-1" } });
      if (name === "agent_send_message") return tool({ sessionId: args.session_id, async: true, result: { accepted: true } });
      if (name === "agent_get_messages") {
        if (args.skip === 0) return tool({ sessionId: args.session_id, result: { messages: [], total: 3, skip: 0, limit: 1, "has-more": "true" } });
        const reply = textFor ? textFor(port) : text ?? `http://127.0.0.1:${port}/f/Agent-Referrals-Test.csv\n{"file":"/data/artifacts/Agent-Referrals-Test.csv","agents":2,"capped":false,"zips":[{"zip":"90210","added":1}]}`;
        return tool({ sessionId: args.session_id, result: { messages: [{ info: { role: "assistant", finish, time: completed ? { created: 1, completed: 2 } : { created: 1 } }, parts: [{ type: "text", text: reply }] }], total: 3, skip: 2, limit: 1, "has-more": "false" } });
      }
      res.writeHead(404); res.end();
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, state, url: `http://127.0.0.1:${server.address().port}/mcp` })));
}

test("cas_pull start: opens a Cas session and sends the job async with the ZIPs and the 5000 cap", async () => {
  const { server, state, url } = await fakeOmega();
  try {
    const r = await run(pullScript, ["start", "--zips", "90210 60043 11109"], { OMEGA_MCP_URL: url, MCP_QUERY_OMEGA_API_KEY: "sa-key-not-real" });
    assert.equal(r.code, 0, r.stderr);
    assert.deepEqual(r.json, { ok: true, session: "ses_test123", zips: 3, max_agents: 5000 });
    assert.deepEqual(state.calls.map((c) => c.name), ["agent_create_session", "agent_send_message"]);
    const send = state.calls[1].args;
    assert.equal(send.session_id, "ses_test123");
    assert.equal(send.async, true);
    assert.match(send.message, /Redefine Reach Agent Referral Data/);
    assert.match(send.message, /d4c389e0-588e-45d9-b291-6e6a8ca37ae3/);
    assert.match(send.message, /with MAX_ROWS 5000: 90210 60043 11109\./);
    assert.ok(state.auth.every((a) => a === "Bearer sa-key-not-real"), "every MCP call carries the box key");
    assert.ok(state.sessionHeaders.slice(1).every((h) => h === "mcp-sess-1"), "the MCP session id is reused after initialize");
  } finally { server.close(); }
});

test("cas_pull wait: done → the link, the counted CSV rows and Cas's summary", async () => {
  const { server, url } = await fakeOmega();
  try {
    const r = await run(pullScript, ["wait", "--session", "ses_test123"], { OMEGA_MCP_URL: url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 0, r.stderr);
    assert.equal(r.json.status, "done");
    assert.match(r.json.link, /\/f\/Agent-Referrals-Test\.csv$/);
    assert.equal(r.json.agents, 2);
    assert.equal(r.json.summary.agents, 2);
  } finally { server.close(); }
});

test("cas_pull wait: Cas's export_csv fallback link counts; a CSV that is not an export fails", async () => {
  let f = await fakeOmega({ textFor: (port) => `http://127.0.0.1:${port}/download/tok.csv` });
  try {
    const r = await run(pullScript, ["wait", "--session", "ses_test123"], { OMEGA_MCP_URL: f.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 0, r.stderr);
    assert.equal(r.json.status, "done");
    assert.equal(r.json.agents, 1);
    assert.equal(r.json.summary, null);
  } finally { f.server.close(); }
  f = await fakeOmega({ textFor: (port) => `http://127.0.0.1:${port}/f/not-a-referral-export.csv` });
  try {
    const r = await run(pullScript, ["wait", "--session", "ses_test123"], { OMEGA_MCP_URL: f.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 1);
    assert.equal(r.json.status, "failed");
    assert.match(r.json.error, /^the file at the link is not a Referral Export CSV \(header: name,phone/);
  } finally { f.server.close(); }
});

test("cas_pull wait: still working → running; a failed turn or no link → failed", async () => {
  let f = await fakeOmega({ completed: false, finish: "tool-calls" });
  try {
    const r = await run(pullScript, ["wait", "--session", "ses_test123", "--max-seconds", "1"], { OMEGA_MCP_URL: f.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 0, r.stderr);
    assert.equal(r.json.status, "running");
  } finally { f.server.close(); }
  f = await fakeOmega({ finish: "error", text: "model error" });
  try {
    const r = await run(pullScript, ["wait", "--session", "ses_test123"], { OMEGA_MCP_URL: f.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 1);
    assert.deepEqual(r.json, { ok: false, status: "failed", error: "Cas stopped with finish=error: model error" });
  } finally { f.server.close(); }
  f = await fakeOmega({ text: "qo run failed for ZIP 90210 at skip 0: boom" });
  try {
    const r = await run(pullScript, ["wait", "--session", "ses_test123"], { OMEGA_MCP_URL: f.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 1);
    assert.equal(r.json.status, "failed");
    assert.match(r.json.error, /^Cas finished without a CSV link: qo run failed for ZIP 90210/);
  } finally { f.server.close(); }
});

test("cas_pull: no key → not connected; bad ZIPs rejected before any call", async () => {
  const env = { ...process.env }; delete env.MCP_QUERY_OMEGA_API_KEY;
  const noKey = await new Promise((resolve) => execFile("python3", [pullScript, "wait", "--session", "ses_x"], { env }, (err, stdout) => resolve({ code: err ? err.code : 0, json: JSON.parse(stdout.trim()) })));
  assert.equal(noKey.code, 1);
  assert.deepEqual(noKey.json, { ok: false, error: "MCP_QUERY_OMEGA_API_KEY is not set: this box is not connected to OmegaAI" });
  const bad = await run(pullScript, ["start", "--zips", "9021 abcde"], { MCP_QUERY_OMEGA_API_KEY: "k", OMEGA_MCP_URL: "http://127.0.0.1:9/mcp" });
  assert.equal(bad.code, 1);
  assert.deepEqual(bad.json, { ok: false, error: "--zips must be five-digit ZIP codes separated by spaces" });
});
