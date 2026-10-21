# Joe Workshop 4 — Buyer Profile (client-profile) triage

**Date:** 2026-10-14  
**Source:** `joe-nuggets-2026-10-14` (Workshop 4 transcript, section 2: S1–S11)  
**Baseline:** `production` client-profile as of 2026-10-14 (`SKILL.md`, `scripts/cp.py`, `assets/template.html`, `assets/brief.schema.json`, `tests/client-profile.test.mjs`)

**Planning only.** This document does not change skill behavior until implemented PRs merge and ship under our release gates.

---

## Product decision (David, 2026-10-14 10:48 AM)

**Buyer Profile PDF may be up to two Letter pages.** The former one-page cap is **not** a planning constraint anymore (code still enforces one page until a follow-up implementation PR).

- **Page 1** stays the core brief: Snapshot, DISC read, how to talk, appointment playbook (opening, lead points, questions, avoid, close), and the main cited sections.
- **Page 2** is available for **household / couple** content (second person, “in the room together”) and a fuller **presentation block** (openers with “why this fits,” close / next step, optional data-pack prep, DISC stub pointers)—without relying on `trim_one_bullet` to delete Joe’s sections.

Implementation will require updating `SKILL.md`, `template.html`, `cp.py` render/trim logic, and tests; **out of scope for PR #51** (plan-only).

---

## Hard rules (non-negotiable for every item below)

| Rule | Implication for this plan |
|------|-------------------------|
| Public web info only | No MLS, county records, credit, or private social APIs. Exa search + snippets only; LinkedIn never fetched via contents. |
| No records lookup | S10 personas must be market-facing fiction/hypothesis from public listing context, not assessor or owner records. |
| No consent step; never “Reply YES” | S8 prefs apply silently from owner memory; no new SMS gates. Identity disambiguation keeps owner-only `Reply 1, 2 or NONE` for **which public profile**, not buyer consent. |
| Street address never in searches or PDF | S1 **cannot** put a property street into Exa queries or `brief.json`/template. Address may be accepted only to derive **city/metro** or to store a **redacted** anchor on intake; `cp.py` already strips `STREET_RE` from queries and brief text (`cp.py` redact/screen_brief; `SKILL.md` L27, L73). |
| Nothing about the subject hardcoded | No per-person literals in `cp.py` (names, employers, cities). Prompts and fixtures stay synthetic. |
| Fair Housing language stays | Validator `LEXICON` + `screen_brief` remain; new copy must stay hypothesis-only and cite-or-omit. |
| Nothing to pilots without David’s yes | All groups below are **design + repo work** until David approves pilot/SKILLS_REF advance (see README merge ≠ deploy). |

---

## Current skill snapshot (what Joe is asking to extend)

| Area | Today |
|------|--------|
| **Purpose** | One **named person** (household TBD) appointment brief; **shipped today:** one-page PDF max (`SKILL.md` L98; `template.html` L7, L32). **Approved target:** up to **two pages** (see product decision above). |
| **Intake** | `--name`, `--city`, `--type`, optional `--company`, `--role`, `--url`; **no** `--address` (`cp.py` `reject_address_flag`, `cmd_intake`). |
| **Identity** | Single `split_name` → first + last (`cp.py` L1303–1307); couples like “David and Nadine Marshall” collapse to one first/last pair. |
| **Search** | Up to 12 parallel Exa queries: LinkedIn, people, personal/company site, news, podcast, X (`SKILL.md` L108–127); banner shows query/source counts (`build_html` search notice). |
| **DISC / playbook** | `communication_style`, `how_to_communicate`, `appointment_playbook` (opening, 3 lead points, questions, avoid, close); listing adds `pricing_conversation` in schema. |
| **Guardrails** | Fixed `guardrail_notice` on PDF banner (`template.html` L36); SMS leads with “Verify before use.” only (`cmd_sms` L3655)—**not** “do not show the client.” |
| **Presentation** | Partially covered by playbook + `recommendations`; no required “why this opener fits the hunch” field. |
| **Memory / feedback** | Not in client-profile; ARIN-wide memory and learning-loop are separate concerns. |

Joe’s **four buyer personas / four marketing pages** (N1–N6) are **out of scope** for this skill’s identity brief; captured as **S10 / separate skill**.

---

## Size key

| Size | Effort (engineering) | Typical scope |
|------|----------------------|---------------|
| **S** | ~2–6 hours | Prompt + SMS/copy, small `cp.py`/`SKILL.md`, tests only |
| **M** | ~8–16 hours | Schema + validate + template/layout, or intake flags + tests |
| **L** | ~24–40+ hours | Multi-person identity, new PDF layout, or new skill |

---

## Per-change triage (S1–S11)

### S1 — Couple + address intake (Joe N11, N19)

| | |
|--|--|
| **What it changes** | `SKILL.md` intake/render_file table; `cp.py` `cmd_intake`, `build_queries`, possibly `intake.json` fields (`partner_name?`, `property_locality?`); agent clarifying questions (one turn). **Not** `template.html` unless we show “household” on PDF (avoid street). |
| **Size** | **M** (~10–14 h) |
| **Dependencies** | Policy lock on address handling (city-only derivation). Optional: S7 for clearer search narrative. |
| **Risks** | “Property address” in owner message → must redact before search/PDF; couples break `split_name` and identity loop; false confidence if two people share one candidate. |
| **vs today** | Address explicitly refused (`SKILL.md` L27, L73); single-person name model. |
| **Recommended order** | **#4 in “now”** (after S6, S7, S3 prompt alignment). |

**Plan note:** Invite “both names” in **one** intake string or optional second name field; run **two** identity passes or one household brief (see S2). For address, accept only if script strips to **city/region** for queries and never renders street on PDF.

---

### S2 — Dual-person brief (Joe N14, N19)

| | |
|--|--|
| **What it changes** | `brief.schema.json`, `evaluate_brief`, `template.html`, `trim_one_bullet`, synthesis prompt in `SKILL.md`; likely **two** search/confirm cycles or dual sections in one JSON; tests in `client-profile.test.mjs`. |
| **Size** | **L** (~30–40 h) |
| **Dependencies** | S1; **two-page PDF** (David approved) for dual DISC + “in the room together” on page 2. |
| **Risks** | Fair Housing on “decision-maker” / spouse dynamics; identity merge bugs; render must fail or warn if content exceeds two pages. |
| **vs today** | One subject per `client_id`; one `NAME` in template. |
| **Recommended order** | **#1 in “next”** (after S1 prototype). |

---

### S3 — Presentation recommendations + “why this fits” (Joe N13, N16)

| | |
|--|--|
| **What it changes** | `SKILL.md` synthesis prompt; optional schema extension (`cited` + `rationale` or playbook subfields); `template.html` (playbook bullets); validate rules in `cp.py` if mandatory. |
| **Size** | **M** (~8–12 h) |
| **Dependencies** | None; shares **page 2** with S2 couple block and S4 data-pack when those ship. |
| **Risks** | Model omits rationale unless schema requires it; two-page hard cap still needs layout discipline. |
| **vs today** | Opening/leads/avoid/close exist; no per-line style rationale. |
| **Recommended order** | **#2 in “now”** (high Joe value, fits current sections). |

---

### S4 — C-ready “data pack” prep bias (Joe N8)

| | |
|--|--|
| **What it changes** | `SKILL.md` synthesis; possibly new `recommendations` or `appointment_playbook` subsection; **not** inventing comps—agent-facing checklist only; template slot or bullet under Recommendations. |
| **Size** | **M** (~8–10 h) |
| **Dependencies** | S3; fits naturally on **page 2** with presentation/openers block. |
| **Risks** | Model invents numbers/tables not in evidence → Fair Housing and trust; must stay “prepare these before you go,” never hand to client. |
| **vs today** | Generic recommendations; listing has `pricing_conversation` only. |
| **Recommended order** | **#3 in “next”.** |

---

### S5 — Explicit D/I/S/C tactics (Joe N9, N14)

| | |
|--|--|
| **What it changes** | `SKILL.md` synthesis prompt; may extend `how_to_communicate` or DISC section text; no new Exa targets. |
| **Size** | **S–M** (~4–8 h) |
| **Dependencies** | S3 (same narrative as playbook). |
| **Risks** | Stereotyping if not tied to citations; keep “hypothesis only” (`template.html` L59). |
| **vs today** | DISC is free-text `disc_hypothesis`; tactics implied not structured. |
| **Recommended order** | **#3 in “now”** (prompt-only first). |

---

### S6 — Private-use / Fair Housing banner (Joe N12, N18)

| | |
|--|--|
| **What it changes** | `cmd_sms` (`cp.py` ~L3630+); `template.html` banner copy (still no street); `SKILL.md` SMS + synthesis; optional second banner line in `build_html`. |
| **Size** | **S** (~3–5 h) |
| **Dependencies** | None. |
| **Risks** | SMS 300-char cap (`SKILL.md` L182); wording must not sound like legal advice. |
| **vs today** | PDF has guardrail const; SMS does not say “for you only / do not show client.” |
| **Recommended order** | **#1 in “now”** (compliance + Joe clip alignment). |

---

### S7 — Named public-source sweep in report (Joe N15)

| | |
|--|--|
| **What it changes** | `build_html` search notice; `SKILL.md` synthesis (Sources / snapshot); optional `search.json` summary of targets hit (linkedin, x, news, podcast, company site); tests for banner text. |
| **Size** | **S** (~4–6 h) |
| **Dependencies** | None. |
| **Risks** | Over-claiming (“all social”) when Exa returned zero for a channel—must list **found** channels only. |
| **vs today** | Banner: “Searched N queries and kept M sources”; individual URLs in Sources. |
| **Recommended order** | **#2 in “now”.** |

---

### S8 — Persist agent presentation preferences (Joe N13, N20)

| | |
|--|--|
| **What it changes** | Mostly **outside** client-profile: ARIN memory / learning-loop / box `USER.md` policy; thin hook in `SKILL.md` (“read owner prefs before synthesize”). Optional `config.json` `presentation_prefs` later. |
| **Size** | **L** (~24–32 h cross-cutting) |
| **Dependencies** | Memory product design; S3 field names stable. |
| **Risks** | Storing PII in memory; implying consent; prefs that encourage steering. |
| **vs today** | No per-agent defaults in skill. |
| **Recommended order** | **#4 in “next”.** |

---

### S9 — DISC playbook stubs (Joe N17)

| | |
|--|--|
| **What it changes** | New static assets under `skills/client-profile/assets/` (e.g. `playbooks/disc-c-listing.md`); `SKILL.md` + synthesis (“see stub C”); optional PDF appendix or link in SMS—not four pages. |
| **Size** | **M** (~12–16 h) |
| **Dependencies** | S5 tone; legal review of generic stubs. |
| **Risks** | Generic playbooks read as steering; keep stubs short or link-out if page 2 fills up. |
| **vs today** | No reusable per-style assets. |
| **Recommended order** | **#2 in “next”.** |

---

### S10 — Four listing buyer personas (Joe N1–N6) — **separate skill**

| | |
|--|--|
| **What it changes** | **New skill** (e.g. `listing-buyer-personas`): own `SKILL.md`, script, multi-page PDF or deck export, property **locality** intake (city/market, not street in search). **Do not** extend `client-profile` identity search. |
| **Size** | **L** (~40–60 h new skill) |
| **Dependencies** | Product name, David yes, image/stock policy, Fair Housing review for “likely buyer” framing. |
| **Risks** | Conflated with named-person brief; protected-class targeting in personas; seller-facing vs agent-only (Joe wants 4 pages **in listing presentation**—still agent-built, not automated outreach). |
| **vs today** | Not implemented; client-profile is **named appointment** brief only. |
| **Recommended order** | **Separate track**; kickoff after S6+S7 ship, not blocked on S2. |

---

### S11 — Inaccuracy feedback loop (Joe ~N20, workshop close)

| | |
|--|--|
| **What it changes** | `SKILL.md` owner workflow (“tell ARIN what was wrong”); `wrong-identity` / audit already exist; tie-in to learning-loop + optional `cp.py` flag on evidence row (`low_trust_source`); confidence downgrades in `evaluate_brief`. |
| **Size** | **M** (~10–14 h) |
| **Dependencies** | S8 optional; governance for what gets remembered. |
| **Risks** | Feedback stores client names in memory; agents blame brief for Fair Housing violations. |
| **vs today** | `wrong-identity` deletes client; no structured “field X was wrong.” |
| **Recommended order** | **#3 in “next”.** |

---

## Recommended implementation order (within groups)

1. **S6** → **S7** → **S3** + **S5** (prompt/banner; no schema explosion)  
2. **S1** (intake only; city derivation; document couple limitations until S2)  
3. **S4** → **S9** → **S11** → **S8**  
4. **S2** after two-page template/render PR lands (David decision removes layout blocker)  
5. **S10** as parallel product line, not a client-profile PR

---

## Schedule (calendar days from Thu 2026-10-15)

Assumes one implementer; parallel work possible after “now” bundle.

| Day | Date | Focus |
|-----|------|--------|
| **D0** | Thu Oct 15 | Lock triage (this doc); David review gate for pilot scope; start S6 + S7 PRs. |
| **D1** | Fri Oct 16 | Ship S6/S7; draft S3/S5 prompt PR; spike two-page template wireframe (no fleet ship yet). |
| **D2** | Mon Oct 19 | S1 design: couple + locality fields; no street in queries; tests. |
| **D3** | Tue Oct 20 | S1 implementation PR; begin S4 or S9 stub copy (product choice). |
| **D4** | Wed Oct 21 | **End “this week”** — merge window for now-bundle; **no SKILLS_REF** without David. |
| **D5–D7** | Oct 22–24 | **Next:** S4, S9 assets, S11 workflow doc + light code. |
| **D8+** | Oct 27+ | S2 spike (dual brief); S10 skill charter + mock PDF wireframe. |

---

## Grouping summary

### Now (this week: D0–D4)

| ID | Item | Size |
|----|------|------|
| S6 | Private-use banner in SMS + PDF emphasis | S |
| S7 | Named public-source sweep in report | S |
| S3 | Mandatory presentation lines + “why this fits” | M |
| S5 | D/I/S/C tactics in synthesis | S–M |
| S1 | Couple/locality intake (no street in search/PDF) | M |

### Next

| ID | Item | Size |
|----|------|------|
| S2 | Dual-person brief + in-room section | L |
| S4 | C-ready data-pack prep bias | M |
| S9 | DISC playbook stubs | M |
| S11 | Inaccuracy feedback loop | M |
| S8 | Persist presentation prefs (ARIN memory) | L |

### Separate skill (not client-profile)

| ID | Item | Size |
|----|------|------|
| S10 | Four listing buyer personas (2 local / 2 OOT), marketing plan, four presentation pages | L (new skill) |

---

## Pilot / fleet impact

| Question | Answer |
|----------|--------|
| Does this plan alone change pilot boxes? | **No** — documentation only until code merges and `SKILLS_REF` advances with **David’s yes**. |
| Which changes affect advisors first after roll? | S6/S7/S3/S5 (copy and PDF); S1 (intake questions); later S2/S10 change workflow shape. |
| SKILLS_REF / Dockerfile | Unchanged by this PR; any implementation PR that ships behavior must follow README two-repo pin + fleet roll process. |

---

## Open decisions for David / product

1. **Couples:** One PDF with two people (S2) vs two linked briefs (smaller S1-only). **Resolved:** up to **two pages** in one PDF is allowed; page 2 for couple + presentation.  
2. **Address:** City/metro only from property mention vs optional `--locality` field never stored as street.  
3. **S10** agent-only personas vs export slides for listing deck.  
4. **Pilot cohort** and date for first SKILLS_REF bump after “now” bundle (includes two-page render change when implemented).

---

## References

- Workshop nuggets: uploaded `joe-nuggets-2026-10-14_5c3c.md` (section 2: S1–S11).  
- Skill entrypoints: `skills/client-profile/SKILL.md`, `skills/client-profile/scripts/cp.py`, `skills/client-profile/assets/template.html`.  
- Recent validation fix (context): PR #50 — auto-fill `appendix.sources` (reduces validate retry loops; separate from Joe content).
