// Hermetic test for the retirement-calculator template's projection model.
// Extracts the `// @calc-begin` … `// @calc-end` block from the shipped asset
// (no DOM, no browser) and asserts the math. Run: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const asset = process.env.CALC_ASSET
  || join(here, "..", "skills", "retirement-calculator", "assets", "retirement-calculator.html");
const html = readFileSync(asset, "utf8");

const m = html.match(/\/\/ @calc-begin[\s\S]*?\n([\s\S]*?)\/\/ @calc-end/);
assert.ok(m, "asset must carry the @calc-begin/@calc-end markers");
const project = new Function(m[1] + "\nreturn project;")();

test("no {{tokens}} — the asset ships ready to serve", () => {
  assert.equal(html.includes("{{"), false);
});

test("AdvisorReach branding is present", () => {
  assert.ok(html.includes('<span class="wordmark-name">AdvisorReach</span>'));
  assert.ok(html.includes("--night: #171411"));
});

test("no external scripts — only the Google Fonts stylesheet leaves the page", () => {
  assert.equal((html.match(/<script[^>]*\ssrc=/g) || []).length, 0);
  const links = html.match(/<link[^>]*href="https?:\/\/[^"]+"/g) || [];
  for (const l of links) assert.match(l, /fonts\.(googleapis|gstatic)\.com/);
});

test("defaults (30→65, $25k, $500/mo, 10%) project a nest egg above the contributions", () => {
  const r = project({ age: 30, retireAge: 65, savings: 25000, monthly: 500, rate: 10 });
  assert.equal(r.ok, true);
  assert.equal(r.contributed, 25000 + 500 * 35 * 12); // 235,000
  assert.ok(r.total > r.contributed);
  assert.ok(Math.abs(r.total - (r.contributed + r.growth)) < 1e-6);
  assert.equal(r.series.length, 36); // age 30..65 inclusive, one point per year
  assert.equal(r.series[0].age, 30);
  assert.equal(r.series[35].age, 65);
});

test("0% return: total equals contributions exactly", () => {
  const r = project({ age: 40, retireAge: 50, savings: 1000, monthly: 100, rate: 0 });
  assert.equal(r.ok, true);
  assert.equal(r.total, 1000 + 100 * 120);
  assert.equal(r.growth, 0);
});

test("monthly compounding matches the closed-form future value", () => {
  // FV = PV(1+i)^n + PMT * ((1+i)^n - 1) / i, i = r/12, n = months
  const r = project({ age: 25, retireAge: 65, savings: 10000, monthly: 300, rate: 8 });
  const i = 0.08 / 12, n = 480;
  const fv = 10000 * Math.pow(1 + i, n) + 300 * (Math.pow(1 + i, n) - 1) / i;
  assert.ok(Math.abs(r.total - fv) < 0.01, `${r.total} vs ${fv}`);
});

test("retirement age not after current age is an error", () => {
  const r = project({ age: 65, retireAge: 65, savings: 1, monthly: 1, rate: 10 });
  assert.equal(r.ok, false);
  assert.equal(r.error, "Retirement age must be after your current age.");
});

test("negative inputs clamp to 0 and the return caps at 30%", () => {
  const r = project({ age: 30, retireAge: 31, savings: -5, monthly: -5, rate: 99 });
  assert.equal(r.ok, true);
  assert.equal(r.contributed, 0);
  assert.equal(r.total, 0);
  const capped = project({ age: 30, retireAge: 31, savings: 1000, monthly: 0, rate: 99 });
  const at30 = project({ age: 30, retireAge: 31, savings: 1000, monthly: 0, rate: 30 });
  assert.equal(capped.total, at30.total);
});
