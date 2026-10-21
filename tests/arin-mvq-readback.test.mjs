// RED-681: the production sms_stage read-back ("You're about to send this text ...") is tool output,
// not ARIN's own words. Its body is drafted text; header, Why, Missing and footer lines are neither,
// so the length (R2) and hedge (R4) checks don't fire on them. Shape of syn-017 (Oct 20 ARIN TEST
// run), made-up wording only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const mz = join(here, "..", "evals", "milestone-zero");

const PRELUDE = `
from grader.scorer import grade_case
from grader.config import load_grader_config
from grader.routes.deterministic import split_draft
cfg = load_grader_config()
def G(case, reply):
    case.setdefault("id", "t"); case.setdefault("synthetic", True); case.setdefault("category", "follow_up")
    return grade_case(case, {"assistant_text": reply, "outbound_log": []}, config=cfg, route_name="")
CASE = {"draft_expected": True, "input": {
    "owner_text": "text sam a short hello, just say im around if they need anything",
    "context_turns": [{"role": "owner", "content": "sam bought on elm st last spring, 555-010-0950"},
                      {"role": "arin", "content": "Got it. Sam 555-010-0950, bought last spring."}]}}
READBACK = "\\n".join([
    "You're about to send this text from ARIN's number (+15550100000) to +15550100950.",
    "Hi Sam, just checking in. I'm around if you need anything at all with the Elm St place, big or small, any time this fall.",
    "Why: Sam bought on Elm St last spring, from your own text.",
    "Reply SEND to confirm you authorize this one message and that the recipient may receive it.",
    "Reply SEND to send, DROP to discard.",
    "The recipient can still opt out with their carrier.",
])
`;

function py(body) {
  const res = spawnSync("python3", ["-c", PRELUDE + body + "\nprint('ok')"], {
    cwd: mz, encoding: "utf8",
    env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1", ARIN_MVQ_GRADER_MODEL_ROUTE: "" },
  });
  assert.equal(res.status, 0, res.stdout + res.stderr);
  assert.match(res.stdout, /ok/);
}

test("read-back body is drafted text; header, Why and footer are not ARIN's own words", () => py(`
own, drafted = split_draft(READBACK)
assert own.strip() == "", repr(own)
assert drafted.startswith("Hi Sam, just checking in."), repr(drafted)
assert "Why:" not in drafted and "SEND" not in drafted and "opt out" not in drafted
`));

test("syn-017 shape: staged read-back no longer fails length or hedge (passes 10/10)", () => py(`
g = G(dict(CASE), READBACK)
assert g["line_scores"] == [2, 2, 2, 2, 2], (g["line_scores"], g["line_reasons"])
assert g["line_reasons"][4] == "why_present" and g["line_reasons"][2] == "draft_staged_send"
assert g["pass"] and not g["gates"]["Why"], g
`));

test("ARIN's own words around a read-back are still checked", () => py(`
g = G(dict(CASE), "I think this works for Sam.\\n" + READBACK)
assert g["line_scores"][3] == 1 and g["line_reasons"][3] == "hedged_claim", g["line_reasons"]
long_own = "Here is what I did. " * 25
g = G(dict(CASE), long_own + "\\n" + READBACK)
assert g["line_scores"][1] == 0, g["line_reasons"]
g = G(dict(CASE), READBACK + "\\n\\nI think Sam will like it.")
assert g["line_scores"][3] == 1, g["line_reasons"]
`));

test("a read-back with no Why line still fails gate Why; Draft-to path unchanged", () => py(`
no_why = "\\n".join(l for l in READBACK.splitlines() if not l.startswith("Why:"))
g = G(dict(CASE), no_why)
assert g["gates"]["Why"] and g["line_reasons"][4] == "draft_missing_why", g["line_reasons"]
own, drafted = split_draft("Draft to Sam: Hi Sam, hello.\\nWhy: Sam bought last spring.\\nReply SEND to send.")
assert drafted == "Hi Sam, hello." and "Why:" in own
`));
