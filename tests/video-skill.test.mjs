// Hermetic contract test for the `video` skill and the vendored `ffmpeg-skill` (no ffmpeg,
// no docker, no network). Asserts the SKILL.md the box will load keeps its shape: valid
// frontmatter, every tagged recipe is one non-interactive line, every editing recipe goes
// through ffmpeg-skill's scripts (exactly one raw `ffmpeg` line, the source generator),
// no install instructions, delivery via present-file, and that the vendored ffmpeg-skill
// is byte-identical to the pinned upstream commit (manifest hash over every file).
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const skillsDir = join(here, "..", "skills");
const dir = join(skillsDir, "video");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");

// One fenced block per `recipe=<name>` tag: "```bash recipe=trim" … "```".
function recipe(name) {
  const m = skill.match(new RegExp("^```bash recipe=" + name + "\\n([\\s\\S]*?)^```", "m"));
  assert.ok(m, `recipe=${name} block must exist`);
  return m[1].trim();
}
const RECIPES = ["vars", "download", "synth", "probe", "reels", "trim", "join", "overlay", "caption", "gif", "audio", "thumbnail", "export", "check"];
const TOOL_RECIPES = ["probe", "reels", "trim", "join", "overlay", "caption", "gif", "audio", "thumbnail", "export", "check"];
const PINNED = "cecf37ca8194a83bacf5a564700112f73656c26d";
const MANIFEST_SHA = "7a63856a6499b232264095573f875db4af90a36e300912af79fca06649934fc6";

test("frontmatter has name: video and a non-empty description", () => {
  const fm = skill.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  assert.match(fm[1], /^name: video$/m);
  assert.match(fm[1], /^description: ".{40,}"$/m);
});

test("every recipe block exists exactly once; non-vars recipes are one line", () => {
  for (const r of RECIPES) {
    const count = skill.split("```bash recipe=" + r + "\n").length - 1;
    assert.equal(count, 1, `recipe=${r} appears once`);
    if (r === "vars") continue;
    assert.equal(recipe(r).split("\n").length, 1, `recipe=${r} is one line`);
  }
});

test("vars block pins the box's literal paths and the agent settings ffmpeg-skill recommends", () => {
  const v = recipe("vars");
  assert.match(v, /^SK=\/opt\/data\/skills\/ffmpeg-skill$/m);
  assert.match(v, /^WORK=\/opt\/data\/work\/video; mkdir -p "\$WORK"; cd "\$WORK"$/m);
  assert.match(v, /^ART=\/opt\/data\/artifacts; mkdir -p "\$ART"$/m);
  assert.match(v, /^export FFMPEG_SKILL_NO_OVERWRITE=1 PYTHONWARNINGS=ignore$/m);
});

test("every editing recipe goes through ffmpeg-skill's scripts; synth is the only raw ffmpeg line", () => {
  for (const r of TOOL_RECIPES) {
    assert.match(recipe(r), /^python3 "\$SK\/scripts\/[a-z_]+\.py" /, `${r}: python3 "$SK/scripts/<name>.py"`);
  }
  assert.match(recipe("synth"), /^ffmpeg -hide_banner -loglevel error -y -f lavfi /, "synth is the lavfi generator");
  assert.match(recipe("download"), /^curl -sSL --max-time 120 --max-filesize 209715200 -o "\$WORK\/in\.mp4" "\$URL"$/);
  const rawLines = skill.split("\n").filter((l) => /^ffmpeg /.test(l));
  assert.equal(rawLines.length, 1, "exactly one raw ffmpeg command line in the whole skill");
});

test("writing recipes ask for --json-brief and write into $ART", () => {
  for (const r of ["reels", "trim", "join", "overlay", "caption", "gif", "audio", "export"]) {
    const body = recipe(r);
    assert.ok(body.includes("--json-brief"), `${r}: --json-brief`);
    assert.ok(body.includes('-o "$ART/$NAME.'), `${r}: -o "$ART/$NAME.<ext>"`);
  }
});

test("no install instructions leak into the box skill", () => {
  const body = skill.replace(/^---\n[\s\S]*?\n---\n/, "");
  for (const bad of ["brew install", "apt-get", "apt install", "sudo ", "pip install", "npm install", "npx "]) {
    assert.equal(body.includes(bad), false, `SKILL.md must not say "${bad}"`);
  }
});

test("delivery follows the present-file contract and the SMS length rule", () => {
  assert.ok(skill.includes("`present-file`"), "names present-file");
  assert.ok(skill.includes("ARTIFACT_DIR"), "names ARTIFACT_DIR");
  assert.ok(skill.includes("ARTIFACT_BASE_URL"), "names ARTIFACT_BASE_URL");
  assert.ok(skill.includes("Under 600 characters"), "SMS length rule");
});

test("vendored ffmpeg-skill is byte-identical to the pinned commit (manifest hash)", () => {
  const root = join(skillsDir, "ffmpeg-skill");
  const files = [];
  (function walk(d) {
    for (const e of readdirSync(d)) {
      const p = join(d, e);
      if (statSync(p).isDirectory()) walk(p); else files.push(p);
    }
  })(root);
  // Same construction as `find ffmpeg-skill -type f | LC_ALL=C sort | xargs sha256sum | sha256sum`:
  // one "<sha256>  <path>\n" line per file, byte-sorted by path, hashed as a whole.
  files.sort((a, b) => (relative(skillsDir, a) < relative(skillsDir, b) ? -1 : 1));
  const manifest = files.map((p) => createHash("sha256").update(readFileSync(p)).digest("hex") + "  " + relative(skillsDir, p) + "\n").join("");
  assert.equal(files.length, 70, "70 vendored files");
  assert.equal(createHash("sha256").update(manifest).digest("hex"), MANIFEST_SHA);
  const up = readFileSync(join(root, "SKILL.md"), "utf8");
  assert.match(up, /^name: ffmpeg-skill$/m);
  assert.ok(skill.includes(PINNED), "video/SKILL.md records the pinned commit");
});
