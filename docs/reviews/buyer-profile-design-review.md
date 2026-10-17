# Buyer/Client Profile skill: independent design review

Date: October 14, 2026. Reviewer: Cursor cloud agent, read-only review.

Scope: `skills/client-profile` at skills `production` commit `5d9fbb8` (after PR #39), and the
`render_file` box plugin in `Redefine-Reach/google-cloud-gke-customer-boxes`, read on two
branches: the default branch (box PR #97 merged) and `cursor/arin-render-file-search-ddeb`
(unmerged). Nothing was merged, deployed, or changed on any box. The only change in this PR is
this document.

Method: I read the code, ran the contract tests (`node --test tests/*.test.mjs`, 232 pass), and
reproduced tonight's last failure locally. The repro runs the real `cp.py` with the plugin's
environment filtering, against a fake Exa server on localhost that rejects the proxy token
outside the proxy path, using a synthetic contact ("Riley Example", example.com). The repro
script is described in the appendix.

## Short answer

The root problem is the one you suspected, plus a second one that would have bitten even a
single-tool design.

1. **The LLM is the control flow.** A profile over text needs 7 to 10 `render_file` calls
   across two SMS turns, in a fixed order, while carrying a random hex `client_id` between
   turns. Each time the model skipped or reordered a step, code was added to make later steps
   repair it. That code exists twice (in `cp.py` and in the plugin), with different
   environment rules, and that is exactly how the PR #39 failure happened.
2. **The search layer reports failures as "no match".** Any Exa error (401, 500, timeout,
   unreachable) is written to `search.json` as `couldnt_find`. That stored failure is then
   reused by every later step. A test in the suite asserts that an HTTP 500 must produce
   `couldnt_find`. So the owner was told "couldn't find" for what was really a configuration
   fault, and the tests stayed green.

The fix is one deterministic `profile` operation that does intake, search, filtering and
identity end to end with one environment, and returns one of five explicit statuses. After
that, one `write` operation takes only Joe's four sections from the LLM and renders,
publishes and returns the SMS text. That is two tool calls in the normal case, and three when
the owner has to pick between two people.

## What happened tonight, mapped to causes

| Failure | Immediate cause | Structural cause |
|---|---|---|
| Exa 401, base URL ignored | `cp.py` read `EXA_API_BASE` but not the box proxy variable `EXA_BASE_URL` | Exa config lives in three places (process env, plugin-filtered env, `config.json`), and key and base are resolved independently |
| Sections missing | The schema lets Joe's four sections be empty arrays (they print "None recorded."), while the DISC read, three lead points and one to three objections are required. The one-page trim loop then cuts Joe's sections down to one item but never touches the DISC read, the lead points or the close | The brief has about 15 headings on one 8pt page. Joe asked for four |
| Other David Marshalls merged into one person | The name match accepts first and last name anywhere in the page, not as a phrase, so loose pages entered and had to be grouped | Identity is decided in three places with three rule sets (search grouping, `identity candidates`, `brief validate`) |
| ARIN skipped `op: search`, identity said "couldn't find" | The model went straight to identity. On the merged plugin (box PR #97), `search` is not even in the tool's `op` enum, so the model could not call it | The LLM is expected to sequence the pipeline, and the skill text and the deployed plugin disagree on which ops exist |
| Anchor filter dropped his own LinkedIn | The company had to appear in the page's opening text, and Exa highlights were ignored | Anchor rules are tuned per incident, with no recorded replay set gating changes |
| PR #39 auto-search got 401 and said `couldnt_find` | Identity, confirm, validate and render now search in-process, but the plugin gives those ops no Exa env. `cp.py` then pairs the stale `exa_api_key` that the installer copied into `config.json` with the default base `https://api.exa.ai`. That returns 401, which is written as `couldnt_find` and cached | Search can be triggered from any op, but the secret is attached per op. Errors are collapsed into "no match" and persisted |

The last row is reproduced in the appendix. In a non-search op, `cp.py` resolves the base to
`https://api.exa.ai` and still finds a key (the one in `config.json`). The in-process search
gets a 401 and writes `search.json` with `status: couldnt_find`. On the next turn the plugin
sees that `search.json` exists, skips its own search, and `identity_candidates` returns
`couldn't find` from the cached failure.

## 1. What is structurally wrong

### 1a. The LLM orchestrates a state machine over SMS

The happy path today is: intake, search, identity candidates, then a text to the owner
("Reply 1, 2 or NONE"), even when there is only one candidate. After the owner replies come
identity confirm, evidence render, writing a brief JSON with 17 required fields, validate (possibly twice),
and render. Every step is a separate model decision, and the model must carry the
`client_id` across the SMS turn. The plugin's own tool description gives conflicting guidance:
it says `slug` is "the advisor's or client's first-last name", but client-profile ops reject
anything that is not a hex id.

When a step was skipped, the response was to add self-healing into later steps:
`ensure_search` in four `cp.py` commands, `ensure_client_search` in three plugin ops, the
`own_pipeline_complete` and `later_different_person` checks, `intake_name` stamps, and
`refuse_unnamed_reuse`. Each patch is reasonable on its own. Together they produce a
distributed state machine with two independent auto-search paths, and the two paths do not
get the same environment.

So yes: the root problem is that a model drives six or more steps instead of calling one tool.
A deterministic pipeline should be code, and the model should be used only where judgment
or writing is needed.

### 1b. The environment is attached to op names, not to the code that needs it

Keeping the Exa key out of render subprocesses is a good goal. But the plugin grants it by op
name (`op == "search"`), while `cp.py` can start a search from five commands. The capability
and the code path drifted apart as soon as auto-search was added. On top of that:

- `cp_install.py` copies `EXA_API_KEY` into `config.json` once (`if "exa_api_key" not in
  existing`), never refreshes it, and never records `EXA_BASE_URL`.
- `cp.py` takes the key from env first and then `config.json`. It takes the base from env first
  and then defaults to `https://api.exa.ai`. A key from one source can be paired with a base
  from another. A proxy token sent to the public Exa endpoint is always a 401.
- The plugin strips `ARTIFACT_DIR` and `ARTIFACT_BASE_URL` from every `cp.py` call, so
  `cp.py deliver` depends on the same `config.json` snapshot. If that snapshot is missing,
  `sms-summary` fails with the `artifacts.local` placeholder error.

### 1c. Errors are collapsed, and failures are cached

In `cmd_search`, any `ExaError` calls `write_couldnt_find`. One failing query also throws away
the results of the queries that already succeeded. Because the failure is written to
`search.json`, later steps treat it as a completed search. `ensure_search` only raises when
no file was written, so an auth failure becomes a stored "no match" with no error. The test
`a search error or zero results does not render a brief from owner notes` asserts that HTTP
500 yields `error: couldnt_find`, so the suite enforces the conflation.

The search runs six to eight queries one after another, each with a 25-second timeout, plus a
`/contents` call. The plugin kills the subprocess at 120 seconds. On a slow Exa day the plugin
returns its generic "can't make that file" line, and the reason is lost.

### 1d. Eight state files with invariants between them

Each client has `intake.json`, `search.json`, `evidence.json`, `candidates.json`,
`identity.json`, `brief.json`, `brief.validation.json` and `delivery.json`. Correctness
depends on invariants between them (names stamped on search and identity, every evidence row
carrying a candidate number, a confirmed status on rows), plus a scan of every other client
folder by `created_at`. Most of that code exists to stop the model from reusing the wrong
record. A deterministic per-person record key would remove the need for it.

### 1e. Two repos, three artifacts, and tests that mock the seam

What runs on a box is the image's plugin, plus the skills tree baked in at `SKILLS_REF`, plus
anything a files-only install put under `/opt/data/skills`. The production Dockerfile pins
`SKILLS_REF=ea394ea`, which is skills PR #30. The merged plugin has no `search` op, passes no
Exa env, and still lists four `consent_*` ops that the skill removed. The search op, the Exa
pass-through and the pre-search exist only on the unmerged plugin branch. I could not verify
which combination tonight's test box ran, and that uncertainty is part of the problem.

Neither side tests the seam. The skills tests pass `EXA_*` and `ARTIFACT_*` straight into
every `cp.py` call. The plugin tests run against an empty stub `cp.py` and a fake runner. The
failure lives in the gap between the two, so both suites were green.

### 1f. The output contract drifted from Joe's design

Joe asked for four sections: Client stated, Observations, Hypotheses, Recommendations. The
schema requires 17 top-level fields. The template prints about 15 headings, and the SKILL
text describes a third layout ("Snapshot, Personality / DISC read, How to talk to them,
Appointment playbook, and Sources"). Joe's four sections have no minimum and may be empty,
while three lead points, one to three objections and the DISC read are required. When the
page overflows, the trim loop cuts Joe's sections down to one item each, but it never cuts the
DISC read, the opening, the lead points or the close. "Sections missing" is a predictable result
of that design, not bad luck.

## 2. A design that works reliably by text

Principle: code owns the pipeline, and the LLM writes prose. One environment, one record per
person, one status vocabulary, and exact owner-facing lines returned by the tool.

### Call 1: `profile` (deterministic, the only op that touches Exa)

```
render_file {kind: "client-profile", op: "profile", slug: "david-marshall",
             cp: {name, city, company?, urls?, type?, pick?}}
```

`cp.py profile` does intake, search, filtering, grouping and the identity decision in one
process. The record key is the slug derived from the name, plus a short hash of
company+city, so the model never carries a random id. A repeat call within 24 hours with the
same inputs reuses the stored search results. That is how the pick turn works without
searching again. It returns exactly one of:

| status | When | Tool returns | Owner hears (`say`, sent verbatim) |
|---|---|---|---|
| `ready` | One person, at least one anchored source | `identity` (level, basis), numbered `sources`, the fenced `evidence` block, and the four-section instructions | nothing yet; the model calls `write` next |
| `needs_disambiguation` | Two or more distinct people pass the anchor | up to three `choices` with short labels | "I found 2 David Marshalls: 1) … 2) … Reply 1 or 2." |
| `needs_anchor` | Name hits exist, none tie to the company, a given link, or the city | counts only | "I found pages for David Marshall but none tie to AdvisorReach or Phoenix. Send his LinkedIn or company site." |
| `no_match` | Every query returned HTTP 200 and no page carries the full name | counts only | "couldn't find" |
| `search_unavailable` | No key, 401/403, unreachable, timeout, or all queries failed | `reason`: `no_key`, `auth`, `unreachable`, `timeout`, `rate_limited` | "Search isn't working on my side right now, so I didn't build the profile." |

Rules that make the statuses true:

- `no_match` is possible only when every query succeeded. Any 401 or 403 is
  `search_unavailable/auth` immediately, because it is a configuration fault and should be
  loud. If some queries fail for other reasons, keep what came back and record
  `searches_failed: N`. The brief banner then says "4 of 6 searches ran".
- A failed search is never stored as a result. The next call searches again.
- Run the queries in parallel (or cap the total budget) so the whole op finishes well inside
  the plugin's 120-second limit. If the budget runs out, return
  `search_unavailable/timeout`, not the generic line.

### Call 2: `write` (the only op that takes LLM output)

```
render_file {kind: "client-profile", op: "write", slug: "david-marshall",
             cp: {sections: {client_stated: [...], observations: [...],
                             hypotheses: [...], recommendations: [...]}}}
```

Each item is `{text, sources: [n]}`, where `n` is a source number from Call 1. That is easier
for the model than copying `ev_` hex ids. `cp.py write` validates the four sections (one to
three items each, every item cited, the fair-housing screen, and no phone or address). On
failure it returns the errors and the model retries once. On success it renders the
one-page PDF. The plugin then checks the page count and publishes through its existing
`publish()` helper, the same proven path used by GBP Scorecard and listing-packet. It returns
`sms_text`. `cp.py` composes the header, the identity line, the search banner, the guardrail
line and the Sources list itself. The model never writes those.

If the "Client stated" section has no source, the model writes "Nothing public in his own
words." as the single item, citing nothing. The validator accepts exactly that sentence there.

### What the model does

On the first text, the model calls `profile`. It then either sends `say` verbatim and stops,
or (on `ready`) writes the four sections from the evidence block and calls `write`. When the
owner replies "2", it calls `profile` again with `pick: 2`, then `write`. That gives two or
three tool calls per profile, no hex ids, and no ordering for the model to get wrong. The
SKILL.md shrinks from about 200 lines of procedure to roughly 60 lines: when to use it,
refusals, the two calls, the four-section prompt, and the fair-housing rules.

### Environment and config

- The plugin passes `EXA_API_KEY` and `EXA_BASE_URL` to `profile` only. With one op doing all
  search, per-op gating becomes correct by construction. `write` never searches.
- `cp.py` reads Exa settings from the environment only, as a pair. If `EXA_BASE_URL` is set it
  is used with `EXA_API_KEY`. The public default base is used only when no proxy variable
  exists. Delete the `config.json` `exa_api_key` fallback, and stop the installer from
  writing it.
- Publishing moves to the plugin (`publish()` already reads `ARTIFACT_DIR` and
  `ARTIFACT_BASE_URL` from its own environment), so `cp.py` no longer needs them.

### State

Use one file per person (`profile.json`) holding the intake, the search results with
`ran_at`, the dropped pages with a reason, the people found, the pick, the sections, and the
delivery. Search results are only reused when the inputs match and the search is under 24 hours
old. "Forget" deletes the folder and the artifact, as today.

## 3. Anchor and identity logic: grade and simplest rule

**Grade: C minus.** It is careful and heavily tested, but it is solving a problem that the
name match creates, and the rules disagree with each other.

What I verified directly against `cp.py`:

- The name match is too loose. `full_name_match` accepts the first and last name anywhere in
  roughly 1,000 characters. "Riley Smith and Ann Example spoke" matches "Riley Example". That
  lets namesakes and unrelated pages in, and the anchor layer then has to throw them out.
- The company match is too literal. With company "AdvisorReach", a page that says "Advisor
  Reach" is dropped.
- Without a company, a city typed without a state can never pass. With city "Phoenix", a page
  saying "Phoenix, Arizona" is dropped, because the rule needs a role (which the plugin's
  intake cannot even send) or a state parsed from the city field. "Phoenix, AZ" passes.
- The common-name gate overrides the strongest anchor. "David Smith" with a company is still
  blocked with `need_profile_link` until the owner sends a URL.
- Identity is decided three times. Search grouping (`same_person`, the LinkedIn and X counts,
  `conflict`), `identity candidates` (the name match plus the common-name gate) and
  `brief validate` (source counts and match counts) can each reach a different answer about
  the same pages.

Yes, name disambiguation is over-engineered. The common-name lists, the state table, the role
signal, the X-profile grouping, the `conflict` flag and `need_profile_link` can all go. The
simplest robust rule is:

1. **Search narrowly.** Put the company (or the given URL's domain) in every query, as today.
   Let the search engine do most of the disambiguation.
2. **Name.** Keep a page only if the full name appears as a phrase: "David Marshall",
   "David J. Marshall", "Marshall, David", case-insensitive.
3. **Anchor.** Keep a page only if one of these is true:
   - its URL or host matches a link the owner gave;
   - the company, normalized to lowercase letters and digits ("advisorreach"), appears in the
     normalized title, text, highlights or host;
   - when no company was given, the city appears in the page.
4. **People.** Count distinct LinkedIn `/in/` profiles among the anchored pages. Zero or one
   means one person: pick them automatically with no owner question. Two or more means
   `needs_disambiguation`, labeled from each LinkedIn title. Pages without a profile attach to
   the only person or, if there are several, are left out.
5. **Confidence (shown, not a gate).** High needs two or more anchored sources, including an
   owner link or a company match. Medium is one source. The owner's pick is shown as
   "Owner-picked".
6. Dropped name-matching pages are only counted: "N other pages with this name were left out."

That is about 40 lines of code in place of roughly 400. Lock it with a recorded replay set:
the real Exa responses from tonight's smoke, saved as synthetic-safe fixtures, with the
expected kept and dropped URLs. Every rule change must pass that set.

## 4. Top five changes, in priority order

Delivery facts that apply to all five: skills reach a production box only through the
`SKILLS_REF` pin in `docker/sms-box/Dockerfile`, which is baked at image build time. So
"skills-only" still needs a `SKILLS_REF` bump and an image rebuild before any customer box sees
it. It does not need plugin code changes. Everything below is blocked from live boxes by the
October 11 to 19 freeze. All of it can be built, tested on a kind box with the skills override
mount, and reviewed before then.

| # | Change | Size | Where it ships |
|---|---|---|---|
| 1 | Honest search errors and one config source | Small: about 60 lines in `cp.py`, 5 in `cp_install.py`, one test inverted, three tests added | Skills-only |
| 2 | One `profile` op (intake, search, identity) and remove in-process auto-search from the other commands | Medium: new command of about 200 lines that mostly reuses existing helpers; about 300 lines deleted | Skills-only interim, then a plugin op |
| 3 | Joe's four sections as the whole LLM contract | Medium: schema rewrite, template rewrite, validator trim, fixtures | Skills-only |
| 4 | Simplest identity rule plus a recorded replay set | Medium: net deletion; one new fixture set | Skills-only |
| 5 | Plugin: `profile` and `write` ops, publish in the plugin, one seam test | Small in code (about 80 lines), but gated | Box image rebuild |

**1. Make search failures honest, and use one config source.** In `exa_post`, raise typed
errors: auth for 401/403, rate limit for 429, unavailable for 5xx, timeouts and network
errors. In `cmd_search`, map any auth error to `search_unavailable` with `reason: auth`. Keep
partial results when some queries fail, and never call `write_couldnt_find` on an error. Do
not store a failed search as a result. Resolve key and base as a pair from the environment,
and ignore `config.json` `exa_api_key`. Stop the installer from writing it. Invert the test
that expects HTTP 500 to mean `couldnt_find`, and add tests for 401, a partial failure, and
"key in config.json but no env". This alone turns tonight's last failure from a false "couldn't
find" into a true "search isn't working", and fixes the cache poisoning.

**2. Add one `profile` command, and stop auto-searching elsewhere.** `cp.py profile --name
--city [--company] [--url ...] [--type] [--pick N]` returns the five statuses above, each
with a `say` line. Delete `ensure_search` from identity, confirm, validate and render. In the
new flow those steps no longer exist for the owner path, so nothing can start a search without
the environment. Interim path without a plugin change: the unmerged plugin branch already
maps `op: search` to `cp.py search <id>` with Exa env. Make `cp.py search` perform the
search and identity decision together, auto-picking a single person. The text flow is then
intake, search, brief, render: four calls with no identity round trip in the common case. On
the merged plugin there is no search op at all, so even this interim needs the branch plugin.

**3. Make Joe's four sections the whole LLM contract.** The schema becomes
`client_stated`, `observations`, `hypotheses`, `recommendations`, each one to three items of
`{text, sources: [n]}`. The DISC read, if kept, is one hypothesis item rather than its own
block. `cp.py` builds the header, identity, search banner, guardrail and Sources. The
template has those four sections plus header and sources, so it fits one Letter page at a
readable size without the trim loop. Keep the fair-housing screen in code.

**4. Replace the anchor and identity logic with the simple rule in section 3, and gate it
with a replay set.** Delete the common-name lists, `need_profile_link`, the state table, the
role signal, X grouping, `conflict`, `later_different_person` and the `intake_name` stamps.
Record tonight's Exa responses (rewritten to synthetic names and example.com hosts) as
fixtures, with the expected kept and dropped URLs for "David Marshall, Phoenix,
AdvisorReach"-shaped intakes: with a company, with a URL, with a state only, and with a city
only.

**5. Plugin: expose `profile` and `write`, publish in the plugin, and test the seam.** Replace
the ten client-profile ops with `profile` (gets the Exa env) and `write` (no secrets). Do
page counting and publishing with the existing `pdf_pages` and `publish` helpers. Remove the
stale `consent_*` ops and the "slug is first-last name" text from the client-profile
description, or make it true by deriving the record key from the name. Add one box-repo test
that runs the real `cp.py` through `run()` with `child_env` against a local fake Exa. That is
the test that would have caught tonight's last failure. This needs a box image rebuild and a
fleet roll, so it cannot reach live boxes until the freeze ends on October 19.

## What I would not change

- Public information only, no consent step, and no contact with the lead.
- The untrusted-evidence fences and the fair-housing checks in code.
- "couldn't find" reserved for a real no-match. The new design makes that rule enforceable
  rather than aspirational.
- Fixed argv in the plugin, and no secrets in render subprocesses.

## Appendix: reproduction of the PR #39 failure

The script lives outside the repo (`/tmp/boxrev/repro.py` on the review VM). It starts a fake
Exa on localhost that accepts the proxy token only under `/exa-proxy/`, as the box proxy does,
and returns 401 elsewhere. It writes `config.json` the way `cp_install.py` leaves it (key
copied, no base). It builds each subprocess environment the way the plugin's `child_env` does
(Exa variables only for `op == "search"`). Results at skills `5d9fbb8`:

- In a non-search op, `cp.exa_base()` is `https://api.exa.ai` and `cp.exa_key()` is set (from
  `config.json`).
- With the Exa env (the owner path when the model calls `op: search`): `status: done`, one
  source kept.
- When the model skips search and calls `identity_confirm`, the in-process search gets a 401.
  The reply is `{"ok":false,"error":"unknown_candidate"}`, and `search.json` now says
  `couldnt_find`.
- On the next turn, the plugin's `identity_candidates` sees that `search.json` exists, skips
  search, and returns `{"status":"couldnt_find","message":"couldn't find"}`.

Edge checks against `cp.py` functions: no company with city "Phoenix" drops a page that says
"Phoenix, Arizona" (passes with "Phoenix, AZ"); company "AdvisorReach" drops a page that says
"Advisor Reach"; "Riley Smith and Ann Example" counts as a full-name match for "Riley Example";
"David Smith" is treated as a common name and blocked without a profile link.
