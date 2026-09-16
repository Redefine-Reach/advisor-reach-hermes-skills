// Hermetic contract test for the `video` skill (no ffmpeg, no docker, no network).
// Asserts the SKILL.md the box will load keeps its shape: valid frontmatter, every
// tagged recipe is a single non-interactive ffmpeg/curl/ffprobe line, every MP4-producing
// recipe is phone-playable (libx264 + aac + faststart), nothing tells the agent to install
// software, and the vendored upstream reference is byte-identical to the pinned commit.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "..", "skills", "video");
const skill = readFileSync(join(dir, "SKILL.md"), "utf8");

// One fenced block per `recipe=<name>` tag: "```bash recipe=trim" … "```".
function recipe(name) {
  const m = skill.match(new RegExp("^```bash recipe=" + name + "\\n([\\s\\S]*?)^```", "m"));
  assert.ok(m, `recipe=${name} block must exist`);
  return m[1].trim();
}
const RECIPES = ["vars", "download", "probe", "trim", "compress", "vertical", "gif", "thumbnail", "audio", "caption", "concat", "synth"];
const MP4_RECIPES = ["trim", "compress", "vertical", "caption", "concat", "synth"];

test("frontmatter has name: video and a non-empty description", () => {
  const fm = skill.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  assert.match(fm[1], /^name: video$/m);
  assert.match(fm[1], /^description: ".{40,}"$/m);
});

test("every recipe block exists exactly once and is a single command line", () => {
  for (const r of RECIPES) {
    const count = skill.split("```bash recipe=" + r + "\n").length - 1;
    assert.equal(count, 1, `recipe=${r} appears once`);
    if (r === "vars") continue;
    const body = recipe(r);
    assert.equal(body.split("\n").length, 1, `recipe=${r} is one line`);
    assert.match(body, /^(ffmpeg -hide_banner -loglevel error -y |ffprobe -v error |curl -sSL )/, `recipe=${r} is non-interactive`);
  }
});

test("vars block defines WORK, ART, IN, OUT with the box's real paths", () => {
  const v = recipe("vars");
  assert.match(v, /^WORK=\/opt\/data\/work\/video; mkdir -p "\$WORK"$/m);
  assert.match(v, /^ART=\/opt\/data\/artifacts; mkdir -p "\$ART"$/m);
  assert.match(v, /^IN="\$WORK\/in\.mp4"$/m);
  assert.match(v, /^OUT="\$ART\/Clip\.mp4"$/m);
});

test("every MP4 recipe is phone-playable: libx264 + pix_fmt yuv420p + faststart, aac or copy audio", () => {
  for (const r of MP4_RECIPES) {
    const body = recipe(r);
    assert.ok(body.includes("-movflags +faststart"), `${r}: faststart`);
    assert.ok(body.endsWith('"$OUT"'), `${r}: writes $OUT`);
    if (r === "concat") { assert.ok(body.includes("-c copy"), "concat copies streams"); continue; }
    assert.ok(body.includes("-c:v libx264 -preset veryfast -crf 2"), `${r}: libx264`);
    assert.ok(body.includes("-pix_fmt yuv420p"), `${r}: yuv420p`);
    assert.ok(body.includes("-c:a aac -b:a 96k") || body.includes("-c:a copy"), `${r}: aac/copy audio`);
  }
});

test("no install instructions leak into the box skill", () => {
  const body = skill.replace(/^---\n[\s\S]*?\n---\n/, "");
  for (const bad of ["brew install", "apt-get", "apt install", "sudo ", "pip install", "npm install"]) {
    assert.equal(body.includes(bad), false, `SKILL.md must not say "${bad}"`);
  }
});

test("delivery follows the present-file contract and the SMS length rule", () => {
  assert.ok(skill.includes("`present-file`"), "names present-file");
  assert.ok(skill.includes("ARTIFACT_DIR"), "names ARTIFACT_DIR");
  assert.ok(skill.includes("ARTIFACT_BASE_URL"), "names ARTIFACT_BASE_URL");
  assert.ok(skill.includes("Under 600 characters"), "SMS length rule");
});

test("vendored upstream reference is byte-identical to the pinned commit", () => {
  const sha = (p) => createHash("sha256").update(readFileSync(join(dir, "references", p))).digest("hex");
  assert.equal(sha("ffmpeg-usage.md"), "f233ed0381d4d95c2fff259b87e0402eb438afe601e6b2cc777392d1d3db9e6b");
  assert.equal(sha("LICENSE-ffmpeg-usage"), "51ab4825620bd69b26cad6a88b8a9d1af6f0014ca97c6945cdcc8fd5845ee9cd");
  assert.ok(skill.includes("b88cb5ce08337ab55c66c67674100b8de29cf232"), "SKILL.md records the pinned commit");
});
