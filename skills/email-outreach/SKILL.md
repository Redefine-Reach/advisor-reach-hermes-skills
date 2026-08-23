---
name: email-outreach
description: Set up cold email outreach for the customer — a SmartLead client account, sending mailboxes on a warmed-up domain, and the mailboxes wired to that account. Use when the user asks to "set up email outreach", "start cold emailing", "get me sending cold emails", "set up SmartLead", or wants sending mailboxes/domains provisioned for outreach. This is the parent skill: it explains the whole picture and what it costs; the actual work is done by its three child skills.
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# Email Outreach (overview)

This skill explains what "setting up email outreach" means end to end, what it
costs, and how long each part takes. It does not itself call any API — it hands
off to three child skills, each of which does one part of the work:

- **`email-outreach-client`** — creates the customer's SmartLead client account
  (or reuses one that already exists) and retrieves its login credentials.
- **`email-outreach-mailboxes`** — finds and orders sending mailboxes on a domain
  (this is the part that spends money).
- **`email-outreach-connect`** — assigns ordered mailboxes to the client account
  so they are actually usable for sending.

Read this skill before any of the three children — it carries the retry
contract and the cost picture that all three depend on. Each child also says
this explicitly, in case you land on one directly.

## What the customer ends up with

A SmartLead client account, dedicated sending domain(s), and one or more
mailboxes on those domains, all connected to that account — ready to run cold
email campaigns from. This is infrastructure, not a finished campaign: getting
there does not by itself send any email.

## Turning copy into campaigns is not this skill set's job

None of the three child skills here creates a campaign, and none of them ever
will — that is deliberate, not a gap to improvise around.

Once the account/domain/mailbox infrastructure above exists and the customer
has drafted copy, **campaigns are created inside the customer's Omega
workspace, by the email-campaigns component's Design workflow — not by
calling SmartLead's API.** That workflow is the natural next step after this
skill set finishes: infrastructure here, campaigns there. If a task sounds
like "build/create the campaigns in SmartLead," it belongs to that workflow,
not to `email-outreach-client`, `email-outreach-mailboxes`, or
`email-outreach-connect`.

**Never call SmartLead's HTTP API directly to create, modify, or send
campaigns — not even to "check what's available" or "try different
endpoints."** If a task seems to need that, the answer is in the customer's
workspace guides, not in the vendor's API — go find it there instead of
inventing a request against `server.smartlead.ai`.

**Where to look:** the customer's workspace carries its own guides for this,
typically reachable from the workspace README via a skills/guides area (in
this ecosystem, `Skills/Email Campaigns`). Use the "Look before you ask"
workspace-first rule below and the `omega-navigation` skill to find your way
there — this skill set cross-references that workflow, it does not restate
its steps, gates, or invocation.

## Campaign management is iterative, not another one-shot step

The client account, domain, and mailboxes above are one-shot infrastructure —
built once and done. Campaign management is not, and carrying the one-shot
habit over is the mistake to avoid: it is an **iterative, human-in-the-loop**
process with no finish line. Copy gets drafted, shown to the customer, revised
from their feedback, and re-run — repeatedly, for as long as the customer
keeps refining it.

The customer's judgement is the authority on their own copy, not yours. Your
job there is to put drafts and results in front of them and act on what they
say back, not to run something to completion and report status.

The mechanics of that loop — which lever to pull, how to bound a run, what to
read back — live entirely in the workspace guides above. This skill set does
not restate them.

## Look before you ask — check the workspace first

Before any step below asks the customer for anything, check their Omega
workspace. In this skill set "the workspace" always means the customer's
**Omega workspace**, reached through the `query-omega` MCP tools
(`list_workspaces`, `ls`, `read`, `query`, `describe`, `run`, …) — never the
local filesystem, and never your own past session logs. If you're unsure how
to find your way around an Omega workspace, use the `omega-navigation`
skill first — it covers listing workspaces, finding the root README, and
following it out to `Notes/` and installed components.

Two things worth checking there before you ask the customer to retype them:

- **Business details** — company name, contact name/email, address, phone,
  real website — commonly live on a business-details page under `Notes/` in
  the workspace. `email-outreach-mailboxes` names the exact fields this can
  fill in.
- **Drafted campaign copy.** "We've got our copy drafted" usually means rows
  already exist in the `Data/Copy` table of the email-campaigns install in
  that same workspace — look there before treating it as something to ask
  about or write yourself.

Only ask the customer for what genuinely isn't in the workspace.

## Order of operations

1. `email-outreach-client` — get or create the SmartLead client account.
2. `email-outreach-mailboxes` — search for a vendor/domain and order mailboxes.
   **This step costs real money — see below. Never do it without telling the
   customer the price first and getting them to confirm.**
3. `email-outreach-connect` — assign the ordered mailboxes to the client account.

Do these in order. Steps 2 and 3 both need a client account to exist first.

## Timing — say this plainly, do not let the customer expect it sooner

- **Mailbox delivery** (the mailbox actually existing and reachable after
  ordering) takes **around 8 hours**. It is not instant, and it is not
  something you can poll faster by trying more often.
- **Domain/mailbox warmup** — the period before a new mailbox is trusted enough
  by inboxes to send real outreach reliably — takes **weeks**, not days. This
  happens automatically after mailboxes are connected; there is nothing further
  for you to do to speed it up, and no API call confirms "warmup is done" —
  just tell the customer to expect it.

Never imply either step is done sooner than the API confirms, and never imply
warmup is a one-time step you completed rather than an ongoing period the
mailbox is still going through.

## What it costs

- **Client account creation** is usually **free**. The AdvisorReach account
  shares a pool of pre-purchased SmartLead seats across all its customers, and
  creating a client only costs **$29/month** if that shared pool has no free
  seat left when you create it — most of the time it does, so most of the time
  this step costs nothing.

  **You cannot check the seat count yourself before calling create-client.**
  The endpoint that reports it (`/api/v1/seats`) lives on SmartLead's internal
  admin API, gated by an admin key you do not hold — your customer-scoped
  `ADVISORREACH_API_KEY` cannot reach it, and the create-client response does
  not report back whether a seat was purchased either. Given that, do not
  stall this step on a "this might cost $29" question you have no way to
  answer: treat client creation like the other free, reversible setup steps
  and proceed. The `email-outreach-mailboxes` "explicit go-ahead" rule is
  about the order step, which genuinely does have a known, quoted, irreversible
  cost — it does not apply here.

  The one real signal you do get: if create-client fails with an error whose
  message mentions seats being exhausted or a configured ceiling, that is an
  actual billing wall the account has hit — stop and tell the customer
  plainly, and do not retry with different values to route around it. And
  because you cannot confirm a seat purchase succeeded either, never tell the
  customer this step "was free" — you genuinely do not know; only their own
  account or invoice can confirm it.

- **Ordering mailboxes** costs **around $13/domain/year** plus **around
  $4.50/mailbox/month**. Unlike client creation, this price is not a maybe —
  the domain-search response quotes it exactly before you spend anything.
  `email-outreach-mailboxes` must always state the exact price quoted by the
  API and get the customer's confirmation before placing the order — never
  place it silently.

A step that *might* cost money is not the same as a step that *does*. Work out
which one you're looking at — check what's actually determinable — before
treating a possible cost as a certain one. Blanket caution is not free: it
stalls the customer on a question you may already be able to answer, or, as
with the seat check above, may never be able to get an answer to at all.
Never place an order without the customer having been told the exact,
quoted cost first.

## Calling the AdvisorReach API

All three child skills call `{ADVISORREACH_API_URL}/smartlead/v1/...` with
`Authorization: Bearer {ADVISORREACH_API_KEY}`.

**Allow at least 300 seconds for a response** (`curl --max-time 300`, or the
equivalent read timeout in whatever HTTP client you use). Creating a client is
slow because it provisions upstream — cutting the request off early does not
mean it failed, it means you stopped waiting.

## The retry contract — read this before any child skill retries anything

If a call to **create a client** returns **504**, that is *not* a failure — the
client may already have been created upstream and the response simply didn't
come back in time. **Re-issue the identical request once, with the exact same
email address.** The email address is the idempotency key on the far side: the
same email converges on the same client and will not create a duplicate or
spend money twice. Never change the email between the original attempt and the
retry, and never retry more than once — if the second attempt also times out or
fails, stop and tell the customer honestly rather than looping.

This contract applies specifically to the create-client call. It does not make
mailbox ordering safe to retry — see `email-outreach-mailboxes` for why that one
is different.

## Rules

- Never claim any part of this is done before the API confirms it — a 200
  response for one step is not evidence the next step happened.
- Never expose internal ids (client ids, order ids, database ids) to the
  customer — only names, domains, addresses, and money amounts they gave you or
  that are meaningful to them.
- A 404 from any of these endpoints means "not found or not yours" — never
  treat it as a permissions error to work around; it means the thing does not
  exist for this customer, full stop.
- If anything is unclear about a customer's intent (which domain, how many
  mailboxes, which client if they have more than one), ask — do not guess and
  proceed, especially where money is involved.
