// Hermetic test for skills/advisorreach-site/scripts/git-credential-wttc-oauth.py, the ARIN Lane's git
// credential helper. The real script runs under python3 against a local stand-in for the hosted OmegaAI
// MCP server (OMEGA_MCP_URL), which records each JSON-RPC request and answers in the shapes the real
// server gave on 2026-10-09 (tools/call `run` → result.content[0].text = {"ok": …}). It proves only the
// helper's own logic; the real MCP → WTTC OAuth Client → GitHub path is proven on team ARIN's box
// (plan 2026-10-08 Task 8.4: `refs/heads/production` read as ar-team-arin, 2026-10-09).
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const HELPER = join(here, "..", "skills", "advisorreach-site", "scripts", "git-credential-wttc-oauth.py");
const GIT_REQUEST = "protocol=https\nhost=github.com\n\n";

async function standIn(answer) {
  const calls = [];
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => {
      const msg = JSON.parse(body);
      calls.push({ auth: req.headers.authorization, session: req.headers["mcp-session-id"], msg });
      if (answer.status) { res.writeHead(answer.status); res.end("no"); return; }
      if (!("id" in msg)) { res.writeHead(202); res.end(); return; }
      const reply = msg.method === "initialize"
        ? { jsonrpc: "2.0", id: msg.id, result: { protocolVersion: "2025-03-26", capabilities: {} } }
        : { jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text: JSON.stringify(answer.payload) }] } };
      if (answer.sse) {
        res.writeHead(200, { "Content-Type": "text/event-stream", "mcp-session-id": "sess-1" });
        res.end("event: message\ndata: " + JSON.stringify(reply) + "\n\n");
      } else {
        res.writeHead(200, { "Content-Type": "application/json", "mcp-session-id": "sess-1" });
        res.end(JSON.stringify(reply));
      }
    });
  });
  await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
  return { calls, url: "http://127.0.0.1:" + server.address().port + "/mcp", close: () => server.close() };
}

function helper(args, env) {
  return new Promise((resolve) => {
    const child = spawn("python3", [HELPER, ...args], { env: { PATH: process.env.PATH, ...env } });
    let stdout = "", stderr = "";
    child.stdout.on("data", (c) => { stdout += c; });
    child.stderr.on("data", (c) => { stderr += c; });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.stdin.end(GIT_REQUEST);
  });
}

test("get answers git with the OAuth Client's token, asked for the WTTC GitHub client as this box", async () => {
  const mcp = await standIn({ payload: { ok: true, data: { result: [{ "access-token": "gho_unit_token", "expires-at": 0 }] } } });
  try {
    const r = await helper(["get"], { OMEGA_MCP_URL: mcp.url, MCP_QUERY_OMEGA_API_KEY: "unit-box-key" });
    assert.equal(r.code, 0, r.stderr);
    assert.equal(r.stdout, "username=x-access-token\npassword=gho_unit_token\n");
    assert.equal(r.stderr, "");
    assert.deepEqual(mcp.calls.map((c) => c.msg.method), ["initialize", "notifications/initialized", "tools/call"]);
    assert.ok(mcp.calls.every((c) => c.auth === "Bearer unit-box-key"));
    assert.equal(mcp.calls[2].session, "sess-1");
    assert.deepEqual(mcp.calls[2].msg.params, { name: "run", arguments: {
      app_id: "5b4edd7a-f920-450b-8732-399095154c83", page_path: "Component Installs/OAuth/GitHub",
      protocol: "OAuth Client", method: "get-token", args: [{}] } });
  } finally { mcp.close(); }
});

test("a server-sent-events reply is read the same way", async () => {
  const mcp = await standIn({ sse: true, payload: { ok: true, data: { "access-token": "gho_sse_token" } } });
  try {
    const r = await helper(["get"], { OMEGA_MCP_URL: mcp.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.stdout, "username=x-access-token\npassword=gho_sse_token\n");
  } finally { mcp.close(); }
});

test("a sign-in that is not connected fails with the OAuth Client's error type and no password", async () => {
  const mcp = await standIn({ payload: { ok: false, error: '{"type":"oauth/NotConnected","data":{}}\nstack' } });
  try {
    const r = await helper(["get"], { OMEGA_MCP_URL: mcp.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.equal(r.code, 1);
    assert.equal(r.stdout, "");
    assert.equal(r.stderr, "git-credential-wttc-oauth: oauth/NotConnected\n");
  } finally { mcp.close(); }
});

test("no OmegaAI key, a refused key and an answer without a token all fail loudly", async () => {
  let r = await helper(["get"], { OMEGA_MCP_URL: "http://127.0.0.1:9/mcp" });
  assert.deepEqual([r.code, r.stdout, r.stderr], [1, "", "git-credential-wttc-oauth: omega/mcp/NoKey\n"]);
  let mcp = await standIn({ status: 401 });
  try {
    r = await helper(["get"], { OMEGA_MCP_URL: mcp.url, MCP_QUERY_OMEGA_API_KEY: "bad" });
    assert.deepEqual([r.code, r.stdout, r.stderr], [1, "", "git-credential-wttc-oauth: omega/mcp/HTTP401\n"]);
  } finally { mcp.close(); }
  mcp = await standIn({ payload: { ok: true, data: { result: [{}] } } });
  try {
    r = await helper(["get"], { OMEGA_MCP_URL: mcp.url, MCP_QUERY_OMEGA_API_KEY: "k" });
    assert.deepEqual([r.code, r.stdout, r.stderr], [1, "", "git-credential-wttc-oauth: oauth/NoToken\n"]);
  } finally { mcp.close(); }
});

test("store and erase do nothing and ask nobody", async () => {
  const mcp = await standIn({ payload: { ok: true, data: { "access-token": "never" } } });
  try {
    for (const op of ["store", "erase"]) {
      const r = await helper([op], { OMEGA_MCP_URL: mcp.url, MCP_QUERY_OMEGA_API_KEY: "k" });
      assert.deepEqual([r.code, r.stdout], [0, ""]);
    }
    assert.equal(mcp.calls.length, 0);
  } finally { mcp.close(); }
});
