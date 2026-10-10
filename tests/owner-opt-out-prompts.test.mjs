// Hermetic scan: owner prompts and SKILL.md must not tell the owner to reply
// with a carrier opt-out keyword. No network. Reads the skills tree only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const skillsDir = join(root, "skills");

const KEYWORD =
  "stop|stopall|unsubscribe|cancel|end|quit|revoke|optout|opt-out";

const PATTERNS = [
  new RegExp(
    `\\b(?:reply|replying|respond|responding)\\s+(?:with\\s+)?(?:the\\s+word\\s+|back\\s+)?[\`'"]?(?:${KEYWORD})\\b`,
    "gi",
  ),
  new RegExp(
    `\\b(?:reply|replying|respond|responding)\\b(?:\\s+\\S+){0,8}?\\s+to\\s+[\`'"]?(?:${KEYWORD})\\b`,
    "gi",
  ),
  new RegExp(
    `\\b(?:reply|replying)\\b[^\\n.]{0,180}\\bor\\s+[\`'"]?(?:${KEYWORD})\\b`,
    "gi",
  ),
  new RegExp(
    `\\btext\\s+(?:me\\s+|us\\s+|back\\s+)[\`'"]?(?:${KEYWORD})\\b`,
    "gi",
  ),
];

function isProhibition(sentence) {
  return /\b(never|do not|don't|dont|must not)\b/i.test(sentence);
}

function sentenceAt(text, index) {
  const before = text.slice(0, index);
  const breaks = [before.lastIndexOf(". "), before.lastIndexOf("! "), before.lastIndexOf("? "), before.lastIndexOf("\n")];
  let start = 0;
  for (const found of breaks) {
    if (found < 0) continue;
    const next = text[found] === "\n" ? found + 1 : found + 2;
    if (next > start) start = next;
  }
  const after = text.slice(index);
  const endRel = after.search(/[.!?\n]/);
  const end = endRel < 0 ? text.length : index + endRel;
  return text.slice(start, end);
}

export function findOptOutReplyInstructions(text) {
  const hits = [];
  const seen = new Set();
  for (const re of PATTERNS) {
    re.lastIndex = 0;
    let match;
    while ((match = re.exec(text)) !== null) {
      const sentence = sentenceAt(text, match.index);
      if (!isProhibition(sentence)) {
        const snippet = sentence.replace(/\s+/g, " ").trim();
        if (snippet && !seen.has(snippet)) {
          seen.add(snippet);
          hits.push(snippet);
        }
      }
      if (match[0].length === 0) re.lastIndex += 1;
    }
  }
  return hits;
}

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "__pycache__") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, acc);
    else if (/\.(md|py|mjs|js|html)$/.test(name)) acc.push(path);
  }
  return acc;
}

function scanFile(path) {
  const raw = readFileSync(path, "utf8");
  const collapsed = raw.replace(/[ \t]*\n[ \t]*/g, " ");
  return [...new Set([...findOptOutReplyInstructions(raw), ...findOptOutReplyInstructions(collapsed)])];
}

test("detector flags an instruction to reply with an opt-out keyword", () => {
  const cancel = findOptOutReplyInstructions("Reply anything else to cancel.");
  assert.equal(cancel.length, 1);
  assert.match(cancel[0], /Reply anything else to cancel/);

  const quoted = findOptOutReplyInstructions("Suggested replying 'cancel'.");
  assert.equal(quoted.length, 1);
  assert.match(quoted[0], /replying 'cancel'/);

  const stop = findOptOutReplyInstructions("text me STOP");
  assert.equal(stop.length, 1);
  assert.match(stop[0], /text me STOP/);

  assert.deepEqual(
    findOptOutReplyInstructions("Never tell the owner to reply `Stop` or `STOP`."),
    [],
  );
  assert.deepEqual(findOptOutReplyInstructions("Reply SEND to send, or NO to drop it."), []);
  assert.deepEqual(
    findOptOutReplyInstructions("reply and stop. Say that lists are not sent this way."),
    [],
  );
  assert.deepEqual(
    findOptOutReplyInstructions("The recipient can still opt out with their carrier."),
    [],
  );
});

test("skills do not tell the owner to reply with an opt-out keyword", () => {
  const files = walk(skillsDir);
  const skillDocs = files.filter((path) => path.endsWith("SKILL.md"));
  assert.ok(skillDocs.length > 0, "expected SKILL.md files under skills/");
  const hits = [];
  for (const path of files) {
    for (const snippet of scanFile(path)) {
      hits.push(`${relative(root, path)}: ${snippet}`);
    }
  }
  assert.deepEqual(hits, []);
});
