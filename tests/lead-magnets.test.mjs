// Hermetic contract test for the generic `lead-magnets` skill (no network, no docker). The skill is baked
// into every box (google-cloud-gke-customer-boxes docker/sms-box/Dockerfile copies skills/ whole), so it
// teaches how to build a Lead Magnet and names no particular one, no result type, no delivery channel and
// no customer (Lead Magnet Factory plan U.10, U.28, U.29, U.35). Hermes shows only the first 57
// characters of a skill description in the system-prompt index (agent/skill_utils.py
// SKILL_PROMPT_DESC_LIMIT = 60; see tests/circle-member-token.test.mjs), so the routing words are pinned
// here. scripts/form_capture.py runs under python3 against a local stand-in for the hosted OmegaAI MCP
// server (OMEGA_MCP_URL), in the shapes tests/circle-member-token.test.mjs uses. The skill's Box Script,
// worker and magnet helper (scripts/box_script.py, worker.py, magnet.py) are installed by magnet.py into
// a temporary root laid out like /opt/data and run under python3: the script against CGI variables, the
// worker against a local stand-in for the box's Hermes api_server (POST /v1/runs, GET /v1/runs/{id}),
// with a deliver.py written by the test. They prove the skill's code only. Form Capture
// itself is tested in the form-capture repo (tests/form-capture), the box's /scripts/ endpoint and its
// detached workers in google-cloud-gke-customer-boxes (tests/test_box_scripts.py,
// tests/test_box_scripts_kind.sh), and the real api_server in the Lead Magnet Factory plan's kind run.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync, chmodSync } from "node:fs";
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

const SCRIPT_TEXT = readFileSync(join(dir, "scripts", "box_script.py"), "utf8");
const WORKER_TEXT = readFileSync(join(dir, "scripts", "worker.py"), "utf8");
const MAGNET_PY = join(dir, "scripts", "magnet.py");

// A stand-in MCP server: list_workspaces answers a home workspace; `run` answers per FormCapture method.
// shape "envelope": every tool answers {ok, data | error}, run's data a bare list (until 2026-10-12).
// shape "current": list_workspaces answers its data bare; run answers {ok, command, data: {path, result: [...]}}.
async function standIn(methods, shape = "envelope") {
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
        payload = shape === "current"
          ? { workspaces: [{ app_id: "app-1", name: "W" }], "active-app-id": "app-1", "home-app-id": "app-1" }
          : { ok: true, data: { "home-app-id": "app-1" } };
      } else if (msg.method === "tools/call" && msg.params.name === "run") {
        const answer = methods[msg.params.arguments.method];
        payload = answer === undefined ? { ok: false, command: "run", error: "PageNotFoundException" }
          : shape === "current" ? { ok: true, command: "run", data: { path: msg.params.arguments.page_path, result: [answer] } }
          : { ok: true, data: [answer] };
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

test("lead-magnets is generic: no particular magnet, result type, delivery channel or customer", () => {
  const banned = /pdf|scorecard|gbp|google business|circle|smartlead|hdc|homes\.com|advisor-reach-internal|nadine|tf-canary|team arin|publish-site|advisorreach-site/i;
  for (const text of [skill, SCRIPT_TEXT, WORKER_TEXT, readFileSync(MAGNET_PY, "utf8")]) {
    assert.doesNotMatch(text, banned);
    assert.doesNotMatch(text, /advisorreach/i);
  }
  assert.doesNotMatch(helper, banned);
});

test("the Box Script lives in the Scripts Directory, the rest of the magnet outside it, and nothing runs as a server", () => {
  assert.match(skill, /`\/opt\/data\/magnets\/<NAME>\/`/);
  assert.match(skill, /made = mg\("create", NAME\)/);
  assert.doesNotMatch(skill, /\/opt\/data\/scripts\//);
  assert.match(SCRIPT_TEXT, /hmac\.compare_digest\(os\.environ\.get\("HTTP_X_BOX_SCRIPT_SECRET", ""\), want\)/);
  assert.match(SCRIPT_TEXT, /start_new_session=True,\n\s+stdin=subprocess\.DEVNULL, stdout=subprocess\.DEVNULL, stderr=subprocess\.DEVNULL\)/);
  assert.match(skill, /Never start a server, a daemon or a cron job for a magnet/);
  assert.match(skill, /\/opt\/data\/skills\/lead-magnet-builds\/<NAME>\/SKILL\.md/);
});

test("a run only makes the result: the prompt sends nothing and carries no contact field", () => {
  assert.match(WORKER_TEXT, /json\.dumps\(job\["product"\], indent=2\)/);
  assert.doesNotMatch(WORKER_TEXT.slice(WORKER_TEXT.indexOf("def produce"), WORKER_TEXT.indexOf("def load_deliver")), /job\["contact"\]/);
  assert.match(WORKER_TEXT, /Do not send, post, publish, upload "\n\s+"or share anything, and do not contact anyone\./);
  assert.match(skill, /A run of you only makes the result/);
  assert.match(skill, /Delivery is code, and it uses only the submitted contact values\./);
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

test("status works with the hosted MCP's current answer shapes (bare list_workspaces, run data.result)", async () => {
  const s = await standIn({ endpoint: { status: "ok", "endpoint-url": "https://db.queryomega.com/hook/e-1" } }, "current");
  try {
    const r = await runHelper(s.url, ["status"]);
    assert.equal(r.code, 0);
    assert.deepEqual(r.msg, { ok: true, app_id: "app-1", page: "Component Installs/Form Capture",
      endpoint_url: "https://db.queryomega.com/hook/e-1" });
    const empty = await standIn({}, "current");
    try {
      const missing = await runHelper(empty.url, ["status"]);
      assert.equal(missing.code, 1);
      assert.match(missing.msg.error, /PageNotFoundException/);
    } finally { empty.close(); }
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

// ---- the skill's Box Script, worker and magnet helper, installed and run as on a box ----

// magnet.py under a temp root laid out like /opt/data.
function mgRun(root, args, env = {}) {
  return new Promise((resolve) => {
    const child = spawn("python3", [MAGNET_PY, ...args, "--root", root], {
      env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", ...env },
    });
    let stdout = "";
    child.stdout.on("data", (c) => { stdout += c; });
    child.on("close", (code) => resolve({ code, msg: JSON.parse(stdout.trim()) }));
  });
}

const MAGNET = {
  what: "Write a one-line note naming the market in the fields below.",
  result: "note.txt",
  product: { market: "[A-Za-z .,'-]{2,80}" },
  contact: { name: "[^\\x00-\\x1f<>]{1,100}", email: "[^@\\s<>]{1,64}@[^@\\s<>]{1,190}\\.[A-Za-z]{2,24}" },
  test: { market: "Austin", name: "Test Lead", email: "lead@example.com" },
};
const DELIVER_WRITES_FILE = 'def deliver(job, result, ctx):\n    ctx["log"]("sending")\n    open(result + ".sent", "w").write(job["contact"]["email"] + " " + open(result).read())\n';
const DELIVER_NOT_YET = 'def deliver(job, result, ctx):\n    raise RuntimeError("delivery_down")\n';

// A magnet made by `create`, given its two files, and installed by `install`.
async function magnet(deliverText = DELIVER_WRITES_FILE, magnetJson = MAGNET) {
  const root = mkdtempSync(join(tmpdir(), "lm-root-"));
  const made = await mgRun(root, ["create", "free-market-report"], { BOX_PUBLIC_BASE_URL: "https://unit.example" });
  assert.equal(made.code, 0);
  const DIR = made.msg.dir;
  assert.deepEqual(made.msg, { ok: true, dir: join(root, "magnets", "free-market-report"),
    script: join(root, "cgi-bin", "free-market-report"), url: "https://unit.example/scripts/free-market-report" });
  assert.equal(statSync(DIR).mode & 0o777, 0o700);
  assert.equal(statSync(join(DIR, "secret")).mode & 0o777, 0o600);
  writeFileSync(join(DIR, "magnet.json"), JSON.stringify(magnetJson));
  writeFileSync(join(DIR, "deliver.py"), deliverText);
  const inst = await mgRun(root, ["install", "free-market-report"]);
  return { root, DIR, inst, script: made.msg.script, secret: readFileSync(join(DIR, "secret"), "utf8"),
    log: () => existsSync(join(DIR, "log.jsonl"))
      ? readFileSync(join(DIR, "log.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l)) : [] };
}

// Run a CGI script the way the box's runner does: CGI variables in, the body on stdin.
function cgi(script, secret, { method = "POST", body = "" } = {}) {
  return new Promise((resolve) => {
    const started = Date.now();
    const child = spawn(script, [], {
      env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", REQUEST_METHOD: method,
        CONTENT_LENGTH: String(Buffer.byteLength(body)), HTTP_X_BOX_SCRIPT_SECRET: secret },
    });
    let stdout = "";
    child.stdout.on("data", (c) => { stdout += c; });
    child.on("close", () => {
      const [head, payload] = stdout.split("\r\n\r\n");
      resolve({ status: Number(head.match(/^Status: (\d+)/)[1]), body: JSON.parse(payload), ms: Date.now() - started });
    });
    child.stdin.end(body);
  });
}

const sub = (id, fields) => JSON.stringify({ id, form: "free-market-report", "submitted-at": "t", fields });
const GOOD = { name: "Test Lead", email: "lead@example.com", market: "Austin" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// A stub worker in place of work.py: notes its argument at once, and that it finished two seconds later.
const STUB = 'import sys, time\nopen(sys.argv[1] + ".started", "a").write("1")\ntime.sleep(2)\nopen(sys.argv[1] + ".finished", "w").write("1")\n';

test("magnet.py install copies the skill's script and worker byte for byte, 0700, and refuses a bad magnet.json or deliver.py", async () => {
  const m = await magnet();
  assert.deepEqual(m.inst, { code: 0, msg: { ok: true, script: m.script, worker: join(m.DIR, "work.py") } });
  assert.equal(readFileSync(m.script, "utf8"), SCRIPT_TEXT);
  assert.equal(readFileSync(join(m.DIR, "work.py"), "utf8"), WORKER_TEXT);
  assert.equal(statSync(m.script).mode & 0o777, 0o700);
  const badTest = await magnet(DELIVER_WRITES_FILE, { ...MAGNET, test: { ...MAGNET.test, email: "not an email" } });
  assert.deepEqual([badTest.inst.code, badTest.inst.msg.error], [1, "magnet.json: test value for contact field email does not match"]);
  assert.ok(!existsSync(badTest.script), "nothing installed");
  const noDeliver = await magnet("x = 1\n");
  assert.deepEqual([noDeliver.inst.code, noDeliver.inst.msg.error], [1, "deliver.py: no deliver(job, result, ctx)"]);
  const badName = await mgRun(m.root, ["create", "Bad_Name"]);
  assert.equal(badName.code, 1);
});

test("magnet.py test posts magnet.json's test values and the form name through Form Capture's hook", async () => {
  const posts = [];
  const hook = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => {
      posts.push({ method: req.method, type: req.headers["content-type"], body });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "received" }));
    });
  });
  await new Promise((r) => hook.listen(0, "127.0.0.1", r));
  const hookUrl = `http://127.0.0.1:${hook.address().port}/hook/e-1`;
  const s = await standIn({ endpoint: { status: "ok", "endpoint-url": hookUrl } });
  try {
    const m = await magnet();
    assert.equal(m.inst.code, 0);
    const r = await mgRun(m.root, ["test", "free-market-report"], { OMEGA_MCP_URL: s.url, MCP_QUERY_OMEGA_API_KEY: "key-1" });
    assert.equal(r.code, 0);
    assert.deepEqual(r.msg, { ok: true, status: 200 });
    assert.equal(posts.length, 1);
    assert.equal(posts[0].method, "POST");
    assert.equal(posts[0].type, "application/x-www-form-urlencoded");
    assert.deepEqual(Object.fromEntries(new URLSearchParams(posts[0].body)),
      { form: "free-market-report", market: "Austin", name: "Test Lead", email: "lead@example.com" });
    assert.ok(s.calls.length > 0 && s.calls.every((c) => c.auth === "Bearer key-1"));
    assert.ok(runs(s.calls).some((a) => a.method === "endpoint"));
  } finally { s.close(); hook.close(); }
});

test("magnet.py create keeps an existing secret", async () => {
  const m = await magnet();
  const file = join(m.DIR, "secret");
  const before = readFileSync(file, "utf8");
  const again = await mgRun(m.root, ["create", "free-market-report"]);
  assert.equal(again.code, 0);
  assert.equal(readFileSync(file, "utf8"), before);
  assert.equal(statSync(file).mode & 0o777, 0o600);
});

test("the Box Script refuses a wrong method, a missing secret and a non-submission, and starts nothing", async () => {
  const m = await magnet();
  assert.equal((await cgi(m.script, m.secret, { method: "GET" })).status, 405);
  assert.equal((await cgi(m.script, "b".repeat(64), { body: sub("s-1", GOOD) })).status, 403);
  const bad = await cgi(m.script, m.secret, { body: "not json" });
  assert.deepEqual([bad.status, bad.body], [400, { ok: false, error: "not a Form Capture submission" }]);
  assert.equal((await cgi(m.script, m.secret, { body: sub("../x", GOOD) })).status, 400);
  assert.deepEqual(readdirSync(join(m.DIR, "jobs")), []);
});

test("the Box Script refuses a field that does not match its pattern, and logs only the field's name", async () => {
  const m = await magnet();
  const r = await cgi(m.script, m.secret, { body: sub("s-2", { ...GOOD, email: "lead at example" }) });
  assert.deepEqual([r.status, r.body], [422, { ok: false, field: "email" }]);
  assert.deepEqual(readdirSync(join(m.DIR, "jobs")), []);
  assert.deepEqual(m.log().map((e) => [e.id, e.event, e.field]), [["s-2", "rejected", "email"]]);
  assert.doesNotMatch(readFileSync(join(m.DIR, "log.jsonl"), "utf8"), /lead at example/);
});

test("the Box Script saves the job, starts the worker in its own session and answers before it ends", async () => {
  const m = await magnet();
  writeFileSync(join(m.DIR, "work.py"), STUB);
  const r = await cgi(m.script, m.secret, { body: sub("s-3", GOOD) });
  assert.deepEqual([r.status, r.body], [202, { ok: true }]);
  assert.ok(r.ms < 1500, `answered in ${r.ms} ms while the worker runs for 2 s`);
  const job = join(m.DIR, "jobs", "s-3.json");
  assert.deepEqual(JSON.parse(readFileSync(job, "utf8")),
    { id: "s-3", product: { market: "Austin" }, contact: { name: "Test Lead", email: "lead@example.com" } });
  assert.equal(statSync(job).mode & 0o777, 0o600);
  for (let i = 0; i < 50 && !existsSync(job + ".finished"); i++) await sleep(100);
  assert.ok(existsSync(job + ".finished"), "the worker outlived the script");
  assert.deepEqual(m.log().map((e) => [e.id, e.event]), [["s-3", "received"]]);
  assert.doesNotMatch(readFileSync(join(m.DIR, "log.jsonl"), "utf8"), /lead@example\.com|Test Lead/);
  const again = await cgi(m.script, m.secret, { body: sub("s-3", GOOD) });
  assert.deepEqual([again.status, again.body], [200, { ok: true, duplicate: true }]);
  await sleep(300);
  assert.equal(readFileSync(job + ".started", "utf8"), "1", "a repeated delivery starts no second worker");
});

// A stand-in for the box's Hermes api_server: a run "makes" the file the prompt names, then ends as told.
async function hermesStandIn(ending = "completed", writes = true) {
  const calls = [];
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => {
      calls.push({ method: req.method, url: req.url, headers: req.headers, body: body ? JSON.parse(body) : null });
      res.writeHead(req.method === "POST" ? 202 : 200, { "Content-Type": "application/json" });
      if (req.method === "POST") {
        const file = calls.at(-1).body.input.match(/Save the result as the file (\S+) and nothing else/)[1];
        if (ending === "completed" && writes) writeFileSync(file, "made");
        res.end(JSON.stringify({ run_id: "run_1", status: "queued" }));
      } else {
        res.end(JSON.stringify({ run_id: "run_1", status: ending, output: "DONE" }));
      }
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return { calls, url: `http://127.0.0.1:${server.address().port}`, close: () => server.close() };
}

const JOB = { id: "s-4", product: { market: "Austin" }, contact: { name: "Test Lead", email: "lead@example.com" } };

function work(m, apiUrl, attempt) {
  const key = join(m.root, "api-server.key");
  writeFileSync(key, "hermes-key\n", { mode: 0o600 });
  writeFileSync(join(m.DIR, "jobs", "s-4.json"), JSON.stringify(JOB), { mode: 0o600 });
  return new Promise((resolve) => {
    const child = spawn("python3", [join(m.DIR, "work.py"), join(m.DIR, "jobs", "s-4.json"), ...(attempt ? [attempt] : [])], {
      env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", HERMES_API_URL: apiUrl, HERMES_API_KEY_FILE: key,
        MAGNET_POLL_SECONDS: "0.05" },
    });
    child.on("close", (code) => resolve(code));
  });
}

test("the worker's run gets `what` and the product fields only; deliver.py delivers from the contact values", async () => {
  const m = await magnet();
  const h = await hermesStandIn();
  try {
    assert.equal(await work(m, h.url), 0);
    const [post] = h.calls;
    assert.deepEqual([post.method, post.url], ["POST", "/v1/runs"]);
    assert.equal(post.headers.authorization, "Bearer hermes-key");
    assert.equal(post.headers["idempotency-key"], "free-market-report:s-4:1");
    assert.equal(post.headers["user-agent"], "box-script/free-market-report");
    assert.ok(post.body.input.startsWith(MAGNET.what + "\n\n"));
    assert.ok(post.body.input.includes('"market": "Austin"'));
    assert.doesNotMatch(post.body.input, /lead@example\.com|Test Lead/);
    assert.ok(post.body.input.includes("Never open anything under " + join(m.root, "magnets") + "."));
    assert.match(post.body.input, /reply with exactly one line: DONE$/);
    assert.deepEqual(h.calls.slice(1).map((c) => [c.method, c.url]), [["GET", "/v1/runs/run_1"]]);
    assert.deepEqual(m.log().map((e) => [e.event, e.run ?? null]),
      [["run_started", "run_1"], ["produced", null], ["sending", null], ["delivered", null]]);
    const result = join(m.root, "magnet-results", "free-market-report", "s-4", "note.txt");
    assert.equal(readFileSync(result + ".sent", "utf8"), "lead@example.com made");
    assert.doesNotMatch(readFileSync(join(m.DIR, "log.jsonl"), "utf8"), /lead@example\.com/);
  } finally { h.close(); }
});

test("the worker fails a run that does not complete, a by-hand attempt is a new run, and a failed delivery is logged", async () => {
  const m = await magnet();
  const h = await hermesStandIn("failed");
  try {
    assert.equal(await work(m, h.url, "2"), 1);
    assert.equal(h.calls[0].headers["idempotency-key"], "free-market-report:s-4:2");
    assert.deepEqual(m.log().map((e) => [e.event, e.run ?? e.reason]), [["run_started", "run_1"], ["failed", "run_failed"]]);
  } finally { h.close(); }
  const d = await magnet(DELIVER_NOT_YET);
  const h2 = await hermesStandIn();
  try {
    assert.equal(await work(d, h2.url), 1);
    assert.deepEqual(d.log().map((e) => [e.event, e.reason ?? null]).slice(-2), [["produced", null], ["failed", "delivery_down"]]);
  } finally { h2.close(); }
});

test("the worker fails a run that completes without its file", async () => {
  const m = await magnet();
  const h = await hermesStandIn("completed", false);
  try {
    assert.equal(await work(m, h.url), 1);
    assert.deepEqual(m.log().map((e) => e.event).slice(-1).concat(m.log().at(-1).reason), ["failed", "no_result"]);
    assert.ok(!m.log().some((e) => e.event === "produced"));
  } finally { h.close(); }
});

test("magnet.py off renames the Box Script, and log shows the magnet's own lines", async () => {
  const m = await magnet();
  await cgi(m.script, m.secret, { body: sub("s-5", { ...GOOD, email: "bad" }) });
  const l = await mgRun(m.root, ["log", "free-market-report"]);
  assert.deepEqual(l.msg.log.map((e) => [e.id, e.event]), [["s-5", "rejected"]]);
  const off = await mgRun(m.root, ["off", "free-market-report"]);
  assert.deepEqual(off.msg, { ok: true, script: m.script + ".off" });
  assert.ok(!existsSync(m.script) && existsSync(m.script + ".off"));
});
