---
name: email-outreach
description: Use when the user asks to "set up email outreach", "start cold emailing", "get me sending cold emails", "set up SmartLead", or wants sending mailboxes/domains provisioned for outreach.
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
there does not by itself send any email. A one-off email from the advisor's own
Gmail is not this setup and not a SmartLead campaign. Use `email-send-confirmed`.
Do not call `GMAIL_SEND_EMAIL`.

## Campaigns: the `smartlead-campaigns` skill

None of the three child skills creates a campaign. Once the account and mailboxes exist,
everything about campaigns — seeing them, their stats, writing the emails, adding leads,
starting and pausing — is the **`smartlead-campaigns`** skill, which works directly against
SmartLead with this customer's own SmartLead account (its API key comes from the AdvisorReach
API; you never handle it). The old OmegaAI MAB / "Email Campaigns" Design pipeline and its
`Docs/AdvisorReach/email-campaigns` manual are retired: do not read them, do not fire them, and
never treat `Component Installs/Email Campaigns` data as the customer's campaigns.

Campaign work is iterative and human-in-the-loop, not a one-shot step: drafts go in front of the
customer, get revised from what they say, and nothing is created or sent without their yes.

## Looking up business details in the customer's workspace

`email-outreach-mailboxes` needs **business details** — company name, contact name/email,
address, phone, real website. They commonly live on a business-details page under `Notes/` in
the customer's Omega workspace, reached through the `query-omega` MCP tools (`read`, `query`, …)
— never the local filesystem and never your own past session logs. Only ask the customer for
what genuinely isn't there.

**Never read or report a credential page.** `Notes/SmartLead Login` (and any page holding a
password, API key, or portal login) is OFF-LIMITS — do not `read` it, do not quote it, do not
tell the customer their password or where it lives. Nothing you do needs the portal password:
the child skills and `smartlead-campaigns` authenticate with `ADVISORREACH_API_KEY`. If the
customer asks for their login, tell them it lives in their own workspace and they can open it
themselves.

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

**These calls do not share one timeout budget** — each child skill states
its own, because "genuinely slow" is true of the calls that provision or
change something upstream (client creation, placing a mailbox order,
finishing an order) and false of the calls that just look something up
(listing clients, listing/checking orders, searching vendors/domains) —
those measured under 0.1s against the local API on 2026-08-28. See each
child skill's "Endpoints" section for its specific budgets and the reasons
behind them; do not assume `--max-time 300` applies to a call just because
it applies to another call in the same skill.

**A call that exceeds its stated budget is a fault to report, not patience
to extend.** Don't retry it with a longer timeout, don't treat the wait
itself as evidence the call is "still working," and don't start diagnosing
why — see "Stop and hand back" below.

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

## Waiting on a step you fired

Firing a coordinator step is asynchronous. The call returning means the work STARTED, never
that it finished. Re-firing does not speed it up — `on-event [{}]` carries no step key, so
each call resets the pipeline back to Manager.

While you wait, do exactly this: sleep, then re-read the real source with the real tool — the
coordinator log, the data table, the campaign — and say what changed since last time.

    while true; do echo "--- $(date) ---"; sleep 60; done

That command is the whole loop. Do NOT add a `grep`, a `jq`, an `until`, a `break`, or a
success string to it. A filter is a decision about what matters, made before you have seen
anything — so the failure you did not predict produces no match, and silence looks exactly
like still-running.

Read the source yourself on every wake and judge it yourself. Waiting is not investigating:
re-reading the same source on an interval is correct; varying a call to see what sticks is the
self-debugging the stop rule forbids.

## Stop and hand back — you are not a debugger

This applies across all four skills in this set, on top of the narrower
retry contracts above (the 504 retry-once-by-email rule, the "ordering is
not safely retryable" rule). Those are specific, bounded exceptions for
named situations. This section is the general backstop for everything else.

If a tool or API call fails, you get **one** corrected retry, and only when
the error names a specific field or value you clearly got wrong or omitted.
Otherwise — and always on the second failure of the same call — stop.

You must never: retry the same call more than once; vary the arguments to
see what sticks; make a call whose purpose is to characterize or diagnose a
failure rather than do the actual work; call an unrelated tool to
investigate what went wrong; or work around a failing tool by switching how
you make the call — curl, raw HTTP, a direct API call, a different endpoint
on the same route. **This holds regardless of whether that transport is one
of your normal tools.** Curl is the sanctioned way to call these APIs, not
an exemption from this rule — a diagnostic call made with your normal,
sanctioned transport is still a diagnostic call, and still forbidden. If you
have made more than 3 tool calls without forward progress, stop even if
nothing has actually errored.

**A step that returns nothing, or a run that produces no result, is not an
error and not an invitation to investigate.** Treat it the same as a clear
failure: report plainly what you observed (or didn't) and stop — do not
start reasoning about why it might have happened or try the same thing
again with different arguments to see if that changes anything.

A failing or empty call means something upstream needs a human's attention
— not that you should work around it. When you stop, tell the customer
plainly, in their own terms (not internal ids, error codes, or endpoint
names), what you were trying to do and that it didn't work, and that you're
handing it back rather than continuing to try things. It's fine to say you
don't know why it failed.

**Self-audit before you tell the customer anything went cleanly.** Look back
over what you actually did. If you did retry a single call more than once,
did vary arguments to see what would stick, did make a call just to
investigate rather than to do the work, or did reach for any transport
other than your normal tools — say so plainly to the customer instead of
presenting the outcome as a clean success. Reporting something as fine
after having flailed to get there is worse than reporting the flailing
itself, because it hides the problem from the person who needs to know
about it.
