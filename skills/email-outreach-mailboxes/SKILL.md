---
name: email-outreach-mailboxes
description: Use when the user asks to buy/order mailboxes, set up a sending domain, add more sending capacity for email outreach, check on a mailbox order's status, or wants ordered mailboxes assigned/connected once an order finishes.
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

## Check before you buy — orders are recurring, not one-shot

Before placing a new order, call `GET .../mailboxes/orders` and look for one
that already covers what the customer is asking for. Orders carry a real,
recurring monthly charge — placing a duplicate because you didn't check is a
second bill for something the customer already has, not a harmless retry.
This is a separate check from the consent rule above: consent covers "don't
spend without a yes," this covers "don't spend because you forgot you
already did." Do both, in this order — check first, then, if a new order is
genuinely needed, get the go-ahead before placing it.

If you cannot tell from the order list whether an existing order already
covers the request — ambiguous domain names, an order in a state you can't
interpret, multiple plausible matches — **stop and ask the customer** rather
than ordering to be safe. Placing an order to avoid the awkwardness of
asking is exactly the mistake this check exists to prevent.

**If `GET .../mailboxes/orders` itself fails** — errors, times out, returns
something you can't parse — say so and stop. Do not infer whether an order
already exists from any other endpoint, and never from
`POST .../mailboxes/orders` itself: that endpoint is not a diagnostic tool,
it is the one that spends money, and a failed check is not license to place
a probing order to find out what's going on.

## Endpoints

- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/vendors` — list available
  mailbox vendors.
- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/domains/search` —
  `?vendor_id=...&domain_name=...` — check whether a domain is available
  through a given vendor, and see its price.
- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders` — list every
  order the caller has placed, each with its live vendor `status`. This is
  the only way to discover an order you did not just place yourself in this
  conversation — check it before assuming no order exists, and use it to
  poll a pending order's status (see "The order lifecycle" below).
- `POST {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders` — place the
  order. **MONEY. See the price rule below before ever calling this.**
  **The only request you may ever send to this endpoint is the one order
  body you have already had approved. Never send it to test it, to see what
  it returns, or to find out why a different call failed.** An empty or
  placeholder body is still a call to the live place-order route — being
  rejected before it reaches the vendor is luck, not a safeguard, and this
  rule does not depend on what the body contains.

  | Excuse | Reality |
  |--------|---------|
  | "An empty POST isn't buying anything, so the money rule doesn't apply." | The money rule is about consent to spend, not about whether this particular call happened to fail. This is the *only* live route to a real charge — probing it to diagnose an unrelated 405 is still a call you were never authorised to make, whether or not it happened to get rejected first. |
- `GET {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders/{order_id}` — check
  one order's status.
- `POST {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders/{order_id}/finish`
  — assign a **completed** order's mailboxes to the caller's client. This is
  the call `email-outreach-connect` makes; see "The order lifecycle" below
  for when it can succeed.

`order_id` is a **string** (e.g. `SS-117116818593238-325640-55`), not a
number — don't cast it or reformat it.

All calls carry `Authorization: Bearer {ADVISORREACH_API_KEY}`, but the
budget depends on what the call actually does:

- **Reads** (`GET .../vendors`, `GET .../domains/search`,
  `GET .../orders/{order_id}`) are lookups, not upstream provisioning —
  measured 2026-08-28 at **0.073s**. Give them a short budget, generous over
  that: `curl --max-time 10`. A read that hasn't answered in 10 seconds isn't
  "still working" — it's a fault to report, not a reason to wait longer or
  retry with a bigger number.
- **`GET .../orders` is the exception: `curl --max-time 60`.** It looks like
  the other reads and is not one. The service asks the vendor for each
  order's live status **one order at a time**, so the call costs roughly
  *(number of your orders)* x *(one vendor round-trip)* — and when the vendor
  is slow or unreachable, each of those is a connect timeout of several
  seconds rather than milliseconds. The 0.073s above was measured against an
  empty list, where that per-order work never ran. A few orders and a
  degraded vendor is the realistic worst case, and 60s covers it.
  **This does not weaken the rule above.** Past 60 seconds it is still a
  fault to report, not patience to extend — and a slow answer here is
  informative in itself: statuses come back `null` when the vendor could not
  be reached, so the orders are still listed and still yours.
- **Place the order** (`POST .../orders`) **allow at least 300 seconds for a
  response** (`curl --max-time 300`) — like client creation, this provisions
  a real order with the vendor and is genuinely slow.
- **Finish** (`POST .../orders/{order_id}/finish`) also **allow at least 300
  seconds** (`curl --max-time 300`) — it isn't measured, and unlike the
  reads above it's a real state change (assigning mailboxes to a client), so
  treat it conservatively until someone measures it, the same as creation.

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

The purchase request carries their real contact/registrant details — the
domain vendor requires an accurate registrant record to register a domain,
the same way any registrar does — and you will not find all of it in the
workspace by guessing — do not invent it and do not use placeholder values.
Ask for: company name, first and last name, email, street (line one, and line
two if they have one), city, state/region, postcode, country, and a phone
number with its country code. Read the whole set back to them together with
the price before you order. `forwarding_domain` is the customer's real
website — the lookalike domain you are buying will forward there. If they
will not share these details, stop and tell them the order cannot proceed; a
rejected order is not safely retryable.

### If asked, say what these details actually are

These are **not** a payment method — the agency's own SmartLead account is
charged for the order, never the customer's. `user_details` becomes the
domain's registration record (required to register the domain, the same as
any registrar requires) and also seeds the mailbox account. For a `.com`
domain, that record is not published in public WHOIS/RDAP by default — it has
been redacted since the GDPR-era WHOIS changes — but it is not fully private
either, since accredited requesters can still see it. Don't tell a customer
it's their billing/card information, and don't promise the record stays
private forever; state plainly what it is and what it is used for.

### Most of `user_details` is NOT a customer question

A competent agent derives `email`, `firstName`/`lastName`, `company`, `city`,
`state`, `country`, `phoneCc`, `languagePreference`, and `forwarding_domain`
from the customer's own workspace business/brand pages — they are public
facts about the business, not information you need to interrogate the
customer for. **Only `addressLineOne` (and
`addressLineTwo` if they have one), `postalCode`, and `phone` genuinely
require asking** — and even those may already be recorded in the workspace
(see below). Asking for nine fields you could have derived is both slower and
more error-prone than reading them off the customer's own pages.

### Check the workspace before asking

Before asking the customer for these registrant/contact details, check their **Omega
workspace** — via the `query-omega` MCP tools (`ls`, `read`, `describe`, …),
never the local filesystem — for a business-details page (commonly under
`Notes/`). See "Look before you ask" in the `email-outreach` parent skill for
the general rule, and the `omega-navigation` skill for how to find your way
around an unfamiliar workspace. If the business-details page has the fields
you need, read them from there and confirm them with the customer rather than
asking them to retype anything. Only ask for what is genuinely missing.

## Order one domain first

Order one domain with a single mailbox first, even if more are wanted. The
first order for an account proves the registrant/contact details and the vendor's
requirements; ordering several at once multiplies the cost of getting one
field wrong. Once the first is delivered and attached, ordering more is
routine.

## The order lifecycle — it will not be assigned yet, and cannot be

Placing an order does not make mailboxes usable, and there is no way to make
it usable sooner. The sequence is fixed:

1. **Order.** Right after `POST .../orders` succeeds, the order exists but is
   still processing upstream — it is not delivered, and it cannot be assigned
   to a client yet. Don't imply otherwise to the customer.
2. **Wait, and poll.** Delivery takes **around 8 hours**. Poll
   `GET .../mailboxes/orders` (or `GET .../orders/{order_id}`) and read the
   order's `status` field. There is no way to speed this up by polling more
   often.
3. **Finish, once `status` is `completed`.** Only then does
   `POST .../orders/{order_id}/finish` (what `email-outreach-connect` calls)
   succeed in assigning the order's mailboxes to the client.

**Calling `finish` (or checking readiness) before the order is `completed`
gets a `409` from the service.** That is the service correctly telling you
the order isn't ready — not a bug, not a failure, and not something to work
around by retrying, changing arguments, or investigating further. Treat a
409 here exactly like the ~8 hour wait it represents: tell the customer the
order is still processing and to expect it to be ready in about 8 hours,
then stop for now.

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

0. Call `GET .../mailboxes/orders` and check whether an existing order
   already covers what the customer is asking for (see "Check before you
   buy" above). Only continue to a new order if it genuinely doesn't.
1. Ask the customer how many mailboxes they want. For the domain, prefer
   searching first over asking cold: listing vendors and searching a couple of
   lookalike candidates (based on the customer's real domain/business name) is
   free, so you can present two or three domains that are actually available
   right now rather than asking the customer to guess a name blind and finding
   out later it's taken. Only ask them to nominate a domain outright if you
   have no reasonable candidate to search from.
2. List vendors, then search for the domain(s) through a vendor. Read back the
   availability and price from the search result — don't estimate it yourself.
3. State the total cost in plain terms (domain price + mailboxes × monthly
   rate) and get explicit confirmation before proceeding.
4. Place the order. Do not retry on failure — see above.
5. Tell the customer mailbox delivery takes **around 8 hours** and the order
   cannot be assigned before then (see "The order lifecycle" above). Once
   `status` is `completed`, mailboxes still need to be connected to their
   SmartLead client (`email-outreach-connect`'s `finish` call) before they're
   usable, and then go through **weeks** of warmup before they're trusted for
   real sending.

## Rules

- Never place an order before checking `GET .../mailboxes/orders` for one
  that already covers the request (see "Check before you buy").
- Never place an order before the customer has heard the exact price and
  confirmed.
- Never retry a failed or ambiguous order automatically.
- Never expose internal order/vendor ids to the customer — describe the
  domain, mailbox count, and price instead.
- A 404 on an order lookup means it does not exist for this customer — never
  treat it as a permissions issue.
- A 409 on `finish` means the order is still processing, not broken — see
  "The order lifecycle."
