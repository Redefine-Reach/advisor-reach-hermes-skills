// RED-629 thin slice, stacked on PR #10. Hermetic: local helper processes, no network.
// 6.0 presence and Kanban off. 6.1 overlapping helper timestamps. 6.2 parallel
// median beats sequential over 3 runs. 6.3 "what are you working on" matches the
// log. A helper asked to send a text or an email is refused.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const script = join(root, "skills", "daily-brief", "scripts", "parallel_brief.py");
const configPath = join(root, "skills", "daily-brief", "references", "parallel-brief.json");
const skillPath = join(root, "skills", "daily-brief", "SKILL.md");
const smsScript = join(root, "skills", "sms-send-confirmed", "scripts", "sms_send_confirmed.py");
const smsSkill = join(root, "skills", "sms-send-confirmed", "SKILL.md");

const ORDER = ["priorities", "meetings", "commitments", "followups"];
const LABELS = {
  priorities: "priorities",
  meetings: "meetings",
  commitments: "commitments",
  followups: "follow-ups",
};

function envFor(dir, extra = {}) {
  const env = {
    ...process.env,
    PARALLEL_BRIEF_DIR: dir,
    PARALLEL_BRIEF_LOG: join(dir, "helpers.jsonl"),
    PARALLEL_BRIEF_STATE: join(dir, "state.json"),
    ...extra,
  };
  if (!Object.prototype.hasOwnProperty.call(extra, "HERMES_DELEGATED_CHILD_CONTEXT")) {
    delete env.HERMES_DELEGATED_CHILD_CONTEXT;
  }
  return env;
}

function run(args, dir, extra = {}) {
  const proc = spawnSync("python3", [script, ...args], {
    env: envFor(dir, extra),
    encoding: "utf8",
  });
  let payload = null;
  try {
    payload = JSON.parse(proc.stdout || "null");
  } catch {
    payload = null;
  }
  return { proc, payload, dir };
}

function writeJobs(dir, items) {
  const path = join(dir, "jobs.json");
  writeFileSync(path, JSON.stringify({ items }));
  return path;
}

function fourItems(delays, tokens = 1000) {
  return ORDER.map((slot, index) => ({
    slot,
    delay_ms: Array.isArray(delays) ? delays[index] : delays,
    text: `part-${slot}`,
    tokens,
  }));
}

function readLog(dir) {
  const path = join(dir, "helpers.jsonl");
  if (!existsSync(path)) return [];
  const raw = readFileSync(path, "utf8").trim();
  if (!raw) return [];
  return raw.split("\n").map((line) => JSON.parse(line));
}

function intervals(events) {
  const open = {};
  const done = {};
  for (const event of events) {
    if (!ORDER.includes(event.slot)) continue;
    if (event.event === "start") open[event.slot] = event.mono_ns;
    if (event.event === "end" && open[event.slot] != null && done[event.slot] == null) {
      done[event.slot] = { start: open[event.slot], end: event.mono_ns };
    }
  }
  return done;
}

function overlaps(events) {
  const done = intervals(events);
  assert.deepEqual(Object.keys(done).sort(), [...ORDER].sort());
  const latestStart = Math.max(...ORDER.map((slot) => done[slot].start));
  const earliestEnd = Math.min(...ORDER.map((slot) => done[slot].end));
  return latestStart < earliestEnd;
}

function sequentialDisjoint(events) {
  const done = intervals(events);
  let previousEnd = 0;
  for (const slot of ORDER) {
    assert.ok(done[slot].start > previousEnd, slot);
    previousEnd = done[slot].end;
  }
}

function expectedStatus(events) {
  const running = new Map();
  for (const event of events) {
    if (!ORDER.includes(event.slot)) continue;
    if (event.event === "start") running.set(event.slot, event.ts);
    if (event.event === "end") running.delete(event.slot);
  }
  if (running.size === 0) return "Nothing is running.";
  const parts = ORDER.filter((slot) => running.has(slot)).map(
    (slot) => `${LABELS[slot]} (started ${running.get(slot)})`,
  );
  return `Working on: ${parts.join("; ")}.`;
}

function median(values) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length / 2)];
}

function timeRun(mode, delayMs) {
  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-time-"));
  const jobs = writeJobs(dir, fourItems(delayMs));
  const started = Date.now();
  const result = run(["run", "--jobs", jobs, "--mode", mode], dir);
  const elapsed = Date.now() - started;
  assert.equal(result.payload.outcome, "merged", result.proc.stderr);
  assert.equal(result.payload.mode, mode);
  return { elapsed, dir, payload: result.payload };
}

async function waitFor(dir, ready, timeoutMs = 8000) {
  const started = Date.now();
  let last = "";
  while (Date.now() - started < timeoutMs) {
    const events = readLog(dir);
    if (ready(events)) return events;
    const path = join(dir, "helpers.jsonl");
    last = existsSync(path) ? readFileSync(path, "utf8") : "(no log yet)";
    await delay(20);
  }
  throw new Error(`log wait timed out: ${last}`);
}

test("6.0 PR #10 and RED-629 are present and Kanban is off", () => {
  const sms = readFileSync(smsScript, "utf8");
  const smsText = readFileSync(smsSkill, "utf8");
  const skill = readFileSync(skillPath, "utf8");
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  assert.match(sms, /HERMES_DELEGATED_CHILD_CONTEXT/);
  assert.match(sms, /red-390-v2/);
  assert.match(sms, /assert_not_delegated_child/);
  assert.match(sms, /refused_autonomous/);
  assert.match(smsText, /Why line/);
  assert.match(smsText, /HERMES_DELEGATED_CHILD_CONTEXT/);
  assert.match(skill, /RED-629/);
  assert.match(skill, /Kanban stays off/);
  assert.equal(config.issue, "RED-629");
  assert.equal(config.stacked_on_pull_request, 10);
  assert.equal(config.kanban.enabled, false);
  assert.equal(config.max_concurrent_children, 4);
  assert.equal(config.child_timeout_seconds, 120);
  assert.equal(config.token_cap, 200000);
  assert.deepEqual(config.order, ORDER);

  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-present-"));
  const jobs = writeJobs(dir, fourItems(0));
  const result = run(["run", "--jobs", jobs], dir);
  assert.equal(result.payload.outcome, "merged");
  assert.equal(result.payload.kanban, false);
  assert.equal(result.payload.max_concurrent, 4);
  assert.equal(result.payload.helpers_started, 4);
  assert.equal(result.payload.provider_called, false);
  assert.deepEqual(
    result.payload.parts.map((part) => part.slot),
    ORDER,
  );
});

test("6.1 helper start and end timestamps overlap in the log", () => {
  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-overlap-"));
  const delays = [800, 750, 700, 650];
  const jobs = writeJobs(dir, fourItems(delays));
  const result = run(["run", "--jobs", jobs, "--mode", "parallel"], dir);
  assert.equal(result.payload.outcome, "merged", result.proc.stderr);
  assert.deepEqual(
    result.payload.parts.map((part) => part.text),
    ORDER.map((slot) => `part-${slot}`),
  );
  const events = readLog(dir);
  assert.equal(events.filter((event) => event.event === "start").length, 4);
  assert.equal(events.filter((event) => event.event === "end").length, 4);
  assert.equal(overlaps(events), true);
  const stderr = result.proc.stderr || "";
  assert.match(stderr, /parallel-brief slot=priorities event=start ts=/);
  assert.match(stderr, /parallel-brief slot=followups event=end ts=/);

  const sequentialDir = mkdtempSync(join(tmpdir(), "parallel-brief-seq-"));
  const sequentialJobs = writeJobs(sequentialDir, fourItems(40));
  const sequential = run(["run", "--jobs", sequentialJobs, "--mode", "sequential"], sequentialDir);
  assert.equal(sequential.payload.outcome, "merged");
  assert.equal(sequential.payload.max_concurrent, 1);
  sequentialDisjoint(readLog(sequentialDir));
});

test("6.2 parallel brief median time beats sequential over 3 runs", { timeout: 60_000 }, () => {
  const parallel = [];
  const sequential = [];
  for (let runIndex = 0; runIndex < 3; runIndex += 1) {
    parallel.push(timeRun("parallel", 350).elapsed);
    sequential.push(timeRun("sequential", 350).elapsed);
  }
  const parallelMedian = median(parallel);
  const sequentialMedian = median(sequential);
  assert.ok(
    parallelMedian < sequentialMedian,
    `parallel median ${parallelMedian}ms vs sequential median ${sequentialMedian}ms (${parallel.join(",")} vs ${sequential.join(",")})`,
  );
});

test("6.3 working on answer matches the log", { timeout: 20_000 }, async () => {
  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-status-"));
  const empty = run(["status"], dir);
  assert.equal(empty.payload.text, "Nothing is running.");
  assert.equal(empty.payload.log_read, true);
  assert.equal(empty.payload.state_read, true);
  assert.equal(empty.payload.kanban, false);

  const jobs = writeJobs(dir, fourItems(2000));
  const child = spawn("python3", [script, "run", "--jobs", jobs, "--mode", "parallel"], {
    env: envFor(dir),
    stdio: ["ignore", "pipe", "pipe"],
  });
  const exitCode = new Promise((resolve) => child.on("exit", resolve));
  let childStdout = "";
  child.stdout.on("data", (chunk) => {
    childStdout += chunk;
  });
  try {
    await waitFor(dir, (events) => events.filter((event) => event.event === "start").length === 4);
    await delay(150);
    const statePath = join(dir, "state.json");
    const state = JSON.parse(readFileSync(statePath, "utf8"));
    state.helpers["invented-board"] = { status: "running", started_at: "1999-01-01T00:00:00.000Z" };
    writeFileSync(statePath, JSON.stringify(state));
    const events = readLog(dir);
    assert.equal(events.some((event) => event.event === "end"), false);
    const status = run(["status"], dir);
    assert.equal(status.payload.text, expectedStatus(events));
    assert.match(status.payload.text, /^Working on: priorities \(started /);
    assert.match(status.payload.text, /follow-ups \(started /);
    assert.equal(status.payload.ignored_state_helpers.includes("invented-board"), true);
    assert.doesNotMatch(status.payload.text, /invented|1999|Kanban|kanban/);
    assert.deepEqual(
      status.payload.helpers.map((helper) => helper.slot).sort(),
      [...ORDER].sort(),
    );
  } finally {
    const code = await exitCode;
    assert.equal(code, 0, childStdout);
  }
  const done = run(["status"], dir);
  assert.equal(done.payload.text, expectedStatus(readLog(dir)));
  assert.equal(done.payload.text, "Nothing is running.");
});

test("a helper asked to send a text or an email is refused", () => {
  for (const channel of ["sms", "email"]) {
    const dir = mkdtempSync(join(tmpdir(), "parallel-brief-send-"));
    const provider = join(dir, "provider.jsonl");
    const refused = run(["send", "--channel", channel], dir, {
      HERMES_DELEGATED_CHILD_CONTEXT: "1",
      PARALLEL_BRIEF_PROVIDER_LOG: provider,
    });
    assert.equal(refused.payload.outcome, "refused_autonomous");
    assert.equal(refused.payload.provider_called, false);
    assert.equal(refused.payload.channel, channel);
    assert.match(refused.payload.reason, /delegated child/);
    assert.equal(refused.proc.status, 2);
    assert.equal(existsSync(provider), false);
  }

  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-send-item-"));
  const marker = join(dir, "sent.txt");
  const items = fourItems(0);
  items[3] = {
    slot: "followups",
    action: "send",
    channel: "email",
    tokens: 1000,
    command: ["python3", "-c", `open(${JSON.stringify(marker)}, "w").write("sent")`],
  };
  const jobs = writeJobs(dir, items);
  const result = run(["run", "--jobs", jobs], dir, { PARALLEL_BRIEF_PROVIDER_LOG: join(dir, "provider.jsonl") });
  assert.equal(result.payload.outcome, "merged");
  assert.equal(result.payload.parts[3].text, "couldn't get follow-ups");
  assert.equal(result.payload.parts[0].ok, true);
  assert.equal(existsSync(marker), false);
  assert.equal(existsSync(join(dir, "provider.jsonl")), false);

  const smsDir = mkdtempSync(join(tmpdir(), "parallel-brief-sms-argv-"));
  const smsJobs = writeJobs(smsDir, [
    {
      slot: "priorities",
      tokens: 1000,
      command: ["python3", "/opt/data/skills/sms-send-confirmed/scripts/sms_send_confirmed.py", "send"],
    },
  ]);
  const smsResult = run(["run", "--jobs", smsJobs], smsDir);
  assert.equal(smsResult.payload.parts[0].text, "couldn't get priorities");
  assert.equal(smsResult.payload.provider_called, false);
});

test("a slow helper becomes couldn't get and does not block the others", () => {
  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-timeout-"));
  const items = fourItems(40);
  items[2] = { slot: "commitments", delay_ms: 5000, text: "too slow", tokens: 1000 };
  const jobs = writeJobs(dir, items);
  const started = Date.now();
  const result = run(["run", "--jobs", jobs], dir, { PARALLEL_BRIEF_TIMEOUT_SECONDS: "2" });
  const elapsed = Date.now() - started;
  assert.equal(result.payload.outcome, "merged", result.proc.stderr);
  assert.equal(result.payload.parts[0].text, "part-priorities");
  assert.equal(result.payload.parts[1].text, "part-meetings");
  assert.equal(result.payload.parts[2].text, "couldn't get commitments");
  assert.equal(result.payload.parts[3].text, "part-followups");
  assert.ok(elapsed < 6000, `elapsed ${elapsed}ms`);
});

test("the token cap skips the tail and a fifth helper does not start", () => {
  const dir = mkdtempSync(join(tmpdir(), "parallel-brief-tokens-"));
  const jobs = writeJobs(dir, fourItems(0, 70000));
  const result = run(["run", "--jobs", jobs], dir);
  assert.equal(result.payload.outcome, "merged");
  assert.equal(result.payload.helpers_started, 2);
  assert.equal(result.payload.parts[0].ok, true);
  assert.equal(result.payload.parts[1].ok, true);
  assert.equal(result.payload.parts[2].text, "couldn't get commitments");
  assert.equal(result.payload.parts[3].text, "couldn't get follow-ups");
  const starts = readLog(dir).filter((event) => event.event === "start").map((event) => event.slot);
  assert.deepEqual(starts.sort(), ["meetings", "priorities"]);

  const over = mkdtempSync(join(tmpdir(), "parallel-brief-fifth-"));
  const fifth = writeJobs(over, [
    ...fourItems(0),
    { slot: "notes", delay_ms: 0, text: "extra", tokens: 1 },
  ]);
  const refused = run(["run", "--jobs", fifth], over);
  assert.equal(refused.payload.outcome, "refused_over_cap");
  assert.equal(refused.payload.helpers_started, 0);
  assert.equal(refused.payload.kanban, false);
  assert.equal(existsSync(join(over, "helpers.jsonl")), false);
});
