# AdvisorReach Hermes Skills

Public, portable skills in the open `SKILL.md` format — usable by Hermes, Claude Code,
Codex, Cursor, and any SKILL.md-compatible agent.

## Install
```
npx skills add Redefine-Reach/advisor-reach-hermes-skills
```
Or add as a Claude Code plugin marketplace: `/plugin marketplace add Redefine-Reach/advisor-reach-hermes-skills`.

## Skills
### connect-app
Connects an outside app (Gmail, Google Calendar, Google Drive, Notion, Slack, HubSpot, LinkedIn,
Canva) through the box's `composio` MCP tools: one `COMPOSIO_MANAGE_CONNECTIONS` call yields a
single-use, 10-minute hosted sign-in link the agent texts the user; the agent then finds and runs
the app's tools via `COMPOSIO_SEARCH_TOOLS` / `COMPOSIO_MULTI_EXECUTE_TOOL`. No browser add-on.
Falls back to `connect-mcp` for apps Composio does not cover.

### browser-use
Teaches the agent it has a **local** headless-Chromium browser (`browser_navigate`, `browser_snapshot`,
`browser_click`, `browser_type`, …) — not a cloud provider — and when to prefer it over web search/scrape, with
a STOP-on-error rule so it never scripts a browser via `execute_code`.

### computer-use
Teaches the agent it has a **local** virtual desktop (`computer_use` via `cua-driver` on an X11/Xvfb display) —
screenshot, click, type — when to prefer the browser tools instead, and a STOP-on-error rule so it never drives
the desktop via `execute_code`.

### present-file
Turns a file the agent already has into a shareable public link. The host runtime injects
two env vars the skill reads:
- `ARTIFACT_DIR` — writable dir whose contents are served publicly.
- `ARTIFACT_BASE_URL` — public URL prefix for those files.
The skill copies the file into `ARTIFACT_DIR` under a random name and returns `ARTIFACT_BASE_URL/<name>`.

### listing-presentation
Generates a seller's pre-listing packet as a PDF from a locked branded template, filling in
advisor + property details gathered over the conversation, then delivers it via the
`present-file` skill.

### gbp-scorecard
Generates a four-page "Digital + AI Scorecard · GBP Playbook" for a named real-estate advisor from
public sources only (state license board, brokerage directory, portals, social, reviews, local press
via the box's Exa search): bio, 24-month production as published, 15 channel scores, Google Business
Profile field-by-field, and a 90-day game plan. Locked template (`assets/template.html`) rendered by
`assets/render.py` (jinja2 + weasyprint) from small per-section JSON files; delivered via `present-file`.

### publish-site
Puts a real website live on a customer's own domain, with a real SSL certificate, via the
AdvisorReach API. A two-turn skill: turn 1 stages the site, gathers the customer's existing
DNS records (screenshot accepted), creates the DNS zone, and hands back the nameservers to
set at their registrar — with an explicit warning that changing nameservers moves the whole
domain, email included. Turn 2, once the customer confirms the nameserver change, polls
delegation and publishes, returning the live `https://` URL. The host runtime injects three
env vars the skill reads:
- `ADVISORREACH_API_URL` — base URL of the AdvisorReach API.
- `ADVISORREACH_API_KEY` — bearer key scoped to this customer.
- `SITE_DIR` — writable dir for the site's content.

### email-outreach (and its three children)
Sets up cold email outreach for a customer via the AdvisorReach API: a SmartLead client
account, sending mailboxes on a warmed-up domain, and the mailboxes connected to that
account. `email-outreach` is the parent — it explains the whole picture, the retry
contract, and what it costs — and points to three children that do the actual work:
- `email-outreach-client` — creates or reuses the customer's SmartLead client account and
  retrieves its login credentials. Creating one can purchase a $29/month seat; a 504 from
  the create call is not a failure (the client may already exist) and is retried once with
  the identical email address, since email is the idempotency key.
- `email-outreach-mailboxes` — searches for a sending domain/vendor and orders mailboxes.
  Costs around $13/domain/year plus around $4.50/mailbox/month; the price is always stated
  and confirmed before ordering, and a failed order is never retried automatically (unlike
  client creation, it isn't guaranteed idempotent).
- `email-outreach-connect` — assigns an already-ordered, delivered set of mailboxes to a
  client account so they become usable. Mailbox delivery takes ~8 hours; warmup after that
  takes weeks.

Each child says explicitly to read the `email-outreach` parent first if it hasn't already
been read in the conversation. All four calls carry `Authorization: Bearer
{ADVISORREACH_API_KEY}` and use a client-side timeout of at least 300 seconds
(`curl --max-time 300`), since creating a client provisions upstream and is slow. The
host runtime injects:
- `ADVISORREACH_API_URL` — base URL of the AdvisorReach API.
- `ADVISORREACH_API_KEY` — bearer key scoped to this customer.

### retirement-calculator
Gives the customer a simple retirement calculator web page — five inputs (ages, savings,
monthly contribution, expected return), a live projected nest egg and a growth chart —
from a locked AdvisorReach-branded template in `assets/`, delivered as a link via
`present-file` under the fixed name `Retirement-Calculator.html` (or on the customer's
own domain via `publish-site`). The agent then suggests concrete tweaks (defaults, an
employer-match field, their own CTA, colors, their domain); change requests are edits to
the agent's working copy, re-delivered under the same name so the link never changes.
The template's math has a hermetic test: `node --test tests/*.test.mjs`.
