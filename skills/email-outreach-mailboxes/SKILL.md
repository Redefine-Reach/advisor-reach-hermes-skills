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

## STOP — do not spend the customer's money without their go-ahead

**Never spend the customer's money without their explicit go-ahead in the
current conversation.** Ordering a domain and mailboxes is a real, recurring
charge on their account, and orders are not reversible or safely retryable.
Before calling the order endpoint: state exactly what you are about to buy,
what it costs up front and per month, and wait for the customer to say yes.

**"Set it up for us" authorises the setup, not the spend.** Listing vendors,
searching domains, creating the client account, installing the connector, and
wiring the adapter are all free and reversible — do them without asking again.
Placing the order is the one step that is neither, and it needs its own,
separate yes, in this conversation, after the price has been stated. Silence,
a previous approval, or a general "go ahead and set this up" is **not**
consent to a purchase.

If you cannot get a clear answer, stop and leave the order unplaced — there is
never a reason to buy ahead of permission. This applies to any future paid
step in this skill set too, not just this one endpoint.

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

## The order body — this is the vendor's contract, copy it exactly

`POST .../mailboxes/orders` sends SmartLead's own `smart-senders/place-order`
body. This is a verbatim copy of the vendor's documented schema — do not
improvise a different shape:

```json
{
  "vendor_id": 2,
  "forwarding_domain": "example.com",
  "user_details": {
    "email": "...", "firstName": "...", "lastName": "...", "company": "...",
    "country": "...", "city": "...", "addressLineOne": "...", "addressLineTwo": "",
    "postalCode": "...", "state": "...", "phoneCc": "+1", "phone": "...",
    "languagePreference": "en"
  },
  "domains": [
    { "domain_name": "...",
      "mailbox_details": [
        { "mailbox": "first.last@...", "first_name": "...", "last_name": "..." }
      ] }
  ]
}
```

**Required:** `vendor_id`, `forwarding_domain`, `user_details`, `domains`;
within `user_details` everything except `addressLineTwo`; within each domain,
`domain_name` and `mailbox_details`; within each mailbox, `mailbox`,
`first_name`, `last_name`.
**Optional:** `addressLineTwo`, `profile_pic`, `parent_account_id`.

**Pin the formats — this is where an agent is most likely to get it wrong.**
The vendor's own example uses full names, not codes (`"India"`, `"Karnataka"`,
`"+91"`):

- `country` and `state` are **full names**, not two-letter codes.
- `phoneCc` carries the leading `+`, and is **separate** from `phone`.
- `phone` is **digits only**.
- `languagePreference` is `en`.

### Ordering needs details only the customer can give you

The purchase request carries their real billing address, and you will not
find it in the workspace by guessing — do not invent it and do not use
placeholder values. Ask for: company name, first and last name, email, street
(line one, and line two if they have one), city, state/region, postcode,
country, and a phone number with its country code. Read the whole set back to
them together with the price before you order. `forwarding_domain` is the
customer's real website — the lookalike domain you are buying will forward
there. If they will not share the billing details, stop and tell them the
order cannot proceed; a rejected order is not safely retryable.

### Most of `user_details` is NOT a customer question

A competent agent derives `email`, `firstName`/`lastName`, `company`, `city`,
`state`, `country`, `phoneCc`, `languagePreference`, and `forwarding_domain`
from the customer's own workspace business/brand pages — they are public
facts about the business, not billing secrets. **Only `addressLineOne` (and
`addressLineTwo` if they have one), `postalCode`, and `phone` genuinely
require asking** — and even those may already be recorded in the workspace
(see below). Asking for nine fields you could have derived is both slower and
more error-prone than reading them off the customer's own pages.

### Check the workspace before asking

Before asking the customer for billing details, check their **Omega
workspace** — via the `query-omega` MCP tools (`ls`, `read`, `describe`, …),
never the local filesystem — for a business-details page (commonly under
`Notes/`). See "Look before you ask" in the `email-outreach` parent skill for
the general rule, and the `omega-navigation` skill for how to find your way
around an unfamiliar workspace. If the business-details page has the fields
you need, read them from there and confirm them with the customer rather than
asking them to retype anything. Only ask for what is genuinely missing.

## Order one domain first

Order one domain with a single mailbox first, even if more are wanted. The
first order for an account proves the billing details and the vendor's
requirements; ordering several at once multiplies the cost of getting one
field wrong. Once the first is delivered and attached, ordering more is
routine.

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
