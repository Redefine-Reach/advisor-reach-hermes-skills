---
name: email-outreach-mailboxes
description: Find a sending domain and order cold-email mailboxes on it, through the AdvisorReach API. Use when the user asks to buy/order mailboxes, set up a sending domain, or add more sending capacity for email outreach. Part of the email-outreach skill set. This step costs real money and must never be run without telling the customer the price first.
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# Email Outreach — Mailboxes

If you have not read the `email-outreach` skill in this conversation, read it
first — it carries context you will otherwise miss, including why this
specific step is the one where money actually gets spent.

This skill finds an available domain and orders sending mailboxes on it. It
does **not** connect them to a client account — that is
`email-outreach-connect`, a separate step, run after the order exists.

## Endpoints

- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/vendors` — list available
  mailbox vendors.
- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/domains/search` —
  `?vendor_id=...&domain_name=...` — check whether a domain is available
  through a given vendor, and see its price.
- `POST {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders` — place the
  order. **MONEY. See the price rule below before ever calling this.**
- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders/{order_id}` — check
  an order's status.

All calls carry `Authorization: Bearer {ADVISORREACH_API_KEY}`. **Allow at
least 300 seconds for a response** (`curl --max-time 300`).

## The price rule — non-negotiable

Ordering costs **around $13/domain/year** plus **around $4.50/mailbox/month**.
**Always state the exact price the API/vendor search returns, and get the
customer's explicit confirmation, before calling the order endpoint.** A skill
that spends a customer's money without saying so first is not acceptable —
this is the one thing in this whole skill set you must never skip or rush.

## Ordering is NOT safely retryable — unlike client creation

Client creation is idempotent by email (see `email-outreach`'s retry
contract). Placing a mailbox order has no such guarantee here — a retried
order could buy a second domain or a second set of mailboxes. **If placing an
order times out, fails, or returns an ambiguous result, do not retry it
yourself.** Instead:

1. Check `GET .../orders/{order_id}` if you have an order id from a partial
   response — it may tell you the order actually went through.
2. If you have no order id and no way to tell, stop and tell the customer
   plainly that the order's outcome is unclear and that a human needs to check
   before trying again, rather than guessing and possibly double-buying.

## Procedure

1. Ask the customer which domain they want to send from (or help them pick one
   if they don't have a preference), and how many mailboxes.
2. List vendors, then search for the domain through a vendor. Read back the
   availability and price from the search result — don't estimate it yourself.
3. State the total cost in plain terms (domain price + mailboxes × monthly
   rate) and get explicit confirmation before proceeding.
4. Place the order. Do not retry on failure — see above.
5. Tell the customer mailbox delivery takes **around 8 hours**, and that after
   that, mailboxes still need to be connected to their SmartLead client
   (`email-outreach-connect`) before they're usable, and then go through
   **weeks** of warmup before they're trusted for real sending.

## Rules

- Never place an order before the customer has heard the exact price and
  confirmed.
- Never retry a failed or ambiguous order automatically.
- Never expose internal order/vendor ids to the customer — describe the
  domain, mailbox count, and price instead.
- A 404 on an order lookup means it does not exist for this customer — never
  treat it as a permissions issue.
