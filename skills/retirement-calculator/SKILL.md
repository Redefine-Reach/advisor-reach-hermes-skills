---
name: retirement-calculator
description: "Give the user a Dave Ramsey-style retirement calculator as a web page — a shareable link — and change it on request. Use when asked for a retirement calculator, 'how much will I have when I retire', a nest egg / compound growth / 401k projection page, a Ramsey calculator, or to change a calculator you already gave them (different defaults, an extra field, colors, wording). Starts from a locked AdvisorReach-branded template and delivers via the present-file skill (or publish-site if they want it on their own domain)."
---

# Retirement Calculator (branded template → link, edited on request)

Give the user a working retirement calculator page and a link to it. The page is a single self-contained HTML file: five inputs (current age, retirement age, current savings, monthly contribution, expected annual return — default 10%), a live projected nest egg, contributed-vs-growth split, and a year-by-year chart. It is already AdvisorReach-branded and needs no fill-in — there are no placeholders to replace.

## 1. Stage a working copy (first time only)
Read nothing yet — just copy. The template is `assets/retirement-calculator.html` (it lives next to this skill). Copy it, unchanged, to `$HERMES_HOME/work/retirement-calculator.html` (`$HERMES_HOME` is your home dir; create the `work` dir if missing). If `$HERMES_HOME/work/retirement-calculator.html` already exists, keep it — that is the user's current calculator; do not overwrite it with the template.

Never edit `assets/retirement-calculator.html` itself. Only the working copy changes.

## 2. Deliver — ALWAYS via the present-file skill
Do NOT hand the user a local path, and do NOT name or serve the file yourself. **Invoke the `present-file` skill** (in this same skills set) on `$HERMES_HOME/work/retirement-calculator.html`, and tell it to use EXACTLY this name: `Retirement-Calculator.html`. Reply with just the link it returns.

The name is fixed on purpose: present-file overwrites a file of the same name, so every re-delivery lands at the same link and anything the user already shared keeps working.

If the user asks for the calculator on their own domain, use the `publish-site` skill instead: stage the working copy as `index.html` under the site's directory in `SITE_DIR` and follow publish-site's two-turn rules (never claim it is live before publish-site's status says so).

## 3. Changes on request
When the user asks for a change — a different default (e.g. "make the default return 8%"), an extra input, different colors or wording, a different headline — edit `$HERMES_HOME/work/retirement-calculator.html` directly with your file tools. HTML, CSS and the JavaScript are all yours to change. Keep the change small and exactly what was asked. Then re-read the file once to confirm the edit is present, and deliver it again exactly as in step 2 (same name, `Retirement-Calculator.html`), so the link does not change. Reply with the same link and one sentence saying what changed.

Where things are in the file:
- Input defaults are the `value="…"` attributes on the five `<input>` fields (`id="age"`, `id="retireAge"`, `id="savings"`, `id="monthly"`, `id="rate"`).
- Colors are the CSS variables at the top of `<style>` (`--night`, `--gold`, `--cream`, …).
- The math is the `project()` function between `// @calc-begin` and `// @calc-end`.
- Copy lives in the `<section class="hero">`, the `<div class="nudge">` and the `<p class="disclaimer">`.

Keep the AdvisorReach header and footer unless the user explicitly asks to remove them.

## Rules
- Never expose `$HERMES_HOME`, `ARTIFACT_DIR`, `SITE_DIR` or any local path to the user — only the link.
- The delivered name is always `Retirement-Calculator.html`. Never invent a new name for a revision.
- Do not add inflation, taxes, Social Security or withdrawal modelling unless the user asks — the point of this page is that it is simple.
- If a file operation fails, stop and tell the user plainly what you could not do. Do not retry with different paths or work around it with shell commands.
