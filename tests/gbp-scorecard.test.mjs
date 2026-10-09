// Contract + behaviour test for gbp-scorecard publish (no weasyprint, no network).
// The box image proves the full render. Here: SKILL.md tells the agent to batch the
// 14 section files, run render.py --publish, and reply with the printed link; and
// render.py's publish / skip paths copy an opaque PDF or exit 0 when the artifact
// env is missing. Third-party imports are stubbed so this runs in CI.
// Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, readdirSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { execFile } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const skillDir = join(here, "..", "skills", "gbp-scorecard");
const skill = readFileSync(join(skillDir, "SKILL.md"), "utf8");
const renderPy = join(skillDir, "assets", "render.py");

const MINI_PDF = Buffer.from(
  "%PDF-1.4\n" +
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n" +
    "2 0 obj\n<< /Type /Pages /Count 2 /Kids [3 0 R 4 0 R] >>\nendobj\n" +
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n" +
    "4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n" +
    "trailer\n<< /Root 1 0 R >>\n%%EOF\n",
  "utf8",
);

function frontmatter(text) {
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  assert.ok(fm, "frontmatter present");
  return fm[1];
}

function stubsDir() {
  const dir = mkdtempSync(join(tmpdir(), "gbp-stubs-"));
  writeFileSync(
    join(dir, "jinja2.py"),
    "class Environment:\n    pass\nclass FileSystemLoader:\n    pass\nclass StrictUndefined:\n    pass\ndef select_autoescape(*a, **k):\n    return None\n",
  );
  writeFileSync(
    join(dir, "jsonschema.py"),
    "class ValidationError(Exception):\n    def __init__(self, message=''):\n        super().__init__(message)\n        self.message = message\n        self.absolute_path = []\ndef validate(*a, **k):\n    return None\n",
  );
  return dir;
}

const stubs = stubsDir();

function run(mode, env, extra = []) {
  const code = `
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("gbp_render", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mode = sys.argv[2]
if mode == "usage":
    sys.argv = ["render.py"]
    mod.main()
elif mode == "publish-accepted":
    sys.argv = ["render.py", "/no/such/gbp-dir", "/tmp/gbp-out.pdf", "--publish"]
    mod.main()
elif mode == "publish-not-a-dir":
    sys.argv = ["render.py", "--publish", "dir", "out.pdf"]
    mod.main()
elif mode == "emit":
    pdf = Path(sys.argv[3])
    publish = sys.argv[4] == "1"
    if len(sys.argv) > 5 and sys.argv[5] == "collide":
        seen = []
        def fake(n):
            seen.append(n)
            return ("ab" * 12) if len(seen) == 1 else ("cd" * 12)
        mod.secrets.token_hex = fake
    mod.emit_result(pdf, publish)
else:
    raise SystemExit("unknown mode " + mode)
`;
  return new Promise((resolve) => {
    execFile(
      "python3",
      ["-c", code, renderPy, mode, ...extra],
      { env: { PATH: process.env.PATH, PYTHONPATH: stubs, ...env } },
      (err, stdout, stderr) => resolve({ code: err ? err.code ?? 1 : 0, stdout, stderr }),
    );
  });
}

function workdir() {
  const dir = mkdtempSync(join(tmpdir(), "gbp-pub-"));
  const pdf = join(dir, "report.pdf");
  const art = join(dir, "artifacts");
  mkdirSync(art);
  writeFileSync(pdf, MINI_PDF);
  return { dir, pdf, art };
}

test("frontmatter passes ARTIFACT_DIR and ARTIFACT_BASE_URL into the sandbox", () => {
  const fm = frontmatter(skill);
  assert.match(fm, /^name: gbp-scorecard$/m);
  assert.match(fm, /^env_passthrough: \[ARTIFACT_DIR, ARTIFACT_BASE_URL\]$/m);
  assert.match(fm, /^description: ".{40,}"$/m);
});

test("§6 writes all 14 sections in one execute_code call and batches the research log", () => {
  assert.match(skill, /Write all 14 section files in \*\*one `execute_code` call\*\*/);
  assert.match(skill, /validate each section's JSON in code before writing/);
  assert.match(skill, /Do not call `write_file` once per file/);
  assert.match(skill, /research_log\.json` appends may be batched per 3–4 searches/);
  assert.doesNotMatch(skill, /one at a time/);
});

test("§7 runs render.py --publish and does not shell out to pdfinfo", () => {
  assert.match(skill, /assets\/render\.py "\$HERMES_HOME\/work\/gbp\/<first-last>" "\$HERMES_HOME\/work\/gbp\/<first-last>\/report\.pdf" --publish/);
  assert.match(skill, /pages=<n>/);
  assert.doesNotMatch(skill, /pdfinfo/);
});

test("§8 replies with the printed link and uses present-file only when publish is skipped", () => {
  assert.match(skill, /prints `render\.py: link`, reply with that link and the four tile numbers/);
  assert.match(skill, /with no other tool call first/);
  assert.match(skill, /only if it printed `render\.py: publish skipped`/);
  assert.match(skill, /Never state the local path/);
  assert.match(skill, /Opaque filenames only/);
  assert.doesNotMatch(skill, /Scorecard-Playbook/);
});

test("--publish is an optional final flag; a bare invocation still prints usage", async () => {
  const usage = await run("usage", {});
  assert.equal(usage.code, 1);
  assert.match(usage.stderr, /Usage: render\.py <report-dir> <out\.pdf> \[--publish\]/);

  const accepted = await run("publish-accepted", {});
  assert.equal(accepted.code, 2, accepted.stderr);
  assert.match(accepted.stderr, /missing section file/);
  assert.doesNotMatch(accepted.stderr, /Usage: render\.py/);

  const misplaced = await run("publish-not-a-dir", {});
  assert.equal(misplaced.code, 1);
  assert.match(misplaced.stderr, /Usage: render\.py/);
});

test("publish copies the PDF under an opaque name and prints the link and page count", async () => {
  const { pdf, art } = workdir();
  const r = await run("emit", {
    ARTIFACT_DIR: art,
    ARTIFACT_BASE_URL: "https://files.example/a/",
  }, [pdf, "1"]);
  assert.equal(r.code, 0, r.stderr);
  const lines = r.stdout.trim().split("\n");
  assert.match(lines[0], /^render\.py: wrote /);
  assert.equal(lines[1], "pages=2");
  const link = lines[2];
  const m = link.match(/^render\.py: link https:\/\/files\.example\/a\/([0-9a-f]{24}\.pdf)$/);
  assert.ok(m, link);
  const names = readdirSync(art);
  assert.deepEqual(names, [m[1]]);
  assert.deepEqual(readFileSync(join(art, m[1])), MINI_PDF);
});

test("a name collision uses open xb and picks a fresh opaque name", async () => {
  const { pdf, art } = workdir();
  writeFileSync(join(art, "abababababababababababab.pdf"), Buffer.from("taken"));
  const r = await run("emit", {
    ARTIFACT_DIR: art,
    ARTIFACT_BASE_URL: "https://files.example/a",
  }, [pdf, "1", "collide"]);
  assert.equal(r.code, 0, r.stderr);
  assert.match(r.stdout, /render\.py: link https:\/\/files\.example\/a\/cdcdcdcdcdcdcdcdcdcdcdcd\.pdf\n?$/);
  assert.equal(readFileSync(join(art, "abababababababababababab.pdf"), "utf8"), "taken");
  assert.deepEqual(readFileSync(join(art, "cdcdcdcdcdcdcdcdcdcdcdcd.pdf")), MINI_PDF);
});

test("publish skip: missing either env var prints the skip line, writes nothing, exits 0", async () => {
  const cases = [
    {},
    { ARTIFACT_DIR: "" },
    { ARTIFACT_BASE_URL: "https://files.example/a" },
    { ARTIFACT_DIR: "   ", ARTIFACT_BASE_URL: "https://files.example/a" },
  ];
  for (const env of cases) {
    const { pdf, art } = workdir();
    const r = await run("emit", env.ARTIFACT_DIR && env.ARTIFACT_DIR.trim() ? { ...env, ARTIFACT_DIR: art } : env, [pdf, "1"]);
    assert.equal(r.code, 0, r.stderr);
    assert.match(r.stdout, /^render\.py: wrote /m);
    assert.match(r.stdout, /^pages=2$/m);
    assert.match(r.stdout, /render\.py: publish skipped \(no ARTIFACT_DIR\)/);
    assert.doesNotMatch(r.stdout, /render\.py: link /);
    assert.deepEqual(readdirSync(art), []);
  }

  const { pdf, art } = workdir();
  const dirOnly = await run("emit", { ARTIFACT_DIR: art }, [pdf, "1"]);
  assert.equal(dirOnly.code, 0, dirOnly.stderr);
  assert.match(dirOnly.stdout, /publish skipped \(no ARTIFACT_DIR\)/);
  assert.doesNotMatch(dirOnly.stdout, /render\.py: link /);
  assert.deepEqual(readdirSync(art), []);
});

test("without --publish the wrote line and page count still print, and nothing is copied", async () => {
  const { pdf, art } = workdir();
  const r = await run("emit", {
    ARTIFACT_DIR: art,
    ARTIFACT_BASE_URL: "https://files.example/a",
  }, [pdf, "0"]);
  assert.equal(r.code, 0, r.stderr);
  assert.match(r.stdout, /^render\.py: wrote /);
  assert.match(r.stdout, /^pages=2$/m);
  assert.doesNotMatch(r.stdout, /link /);
  assert.doesNotMatch(r.stdout, /publish skipped/);
  assert.deepEqual(readdirSync(art), []);
});
