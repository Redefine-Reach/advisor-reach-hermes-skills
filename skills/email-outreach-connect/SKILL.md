---
name: email-outreach-connect
description: Assign already-ordered mailboxes to the customer's SmartLead client account so they become usable for sending. Use when the user has an order for mailboxes and a SmartLead client account and wants them wired together, or asks why their mailboxes "aren't showing up" in their account. Part of the email-outreach skill set — the last of the three steps.
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# Email Outreach — Connect Mailboxes to Client

If you have not read the `email-outreach` skill in this conversation, read it
first — it carries context you will otherwise miss, including why the two
things being wired together here (a client account, and an order of
mailboxes) had to be created by two separate earlier skills.

This is the last step: it takes an order of mailboxes that already exists
(`email-outreach-mailboxes`) and a client account that already exists
(`email-outreach-client`), and connects them. Neither of those two skills does
this for you — a customer can have both a client and an order and still have
nothing usable until this step runs.

## Endpoint

- `POST {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders/{order_id}/finish`
  — body `{"client_id": ...}`. Assigns the mailboxes in that order to that
  client. (The service also accepts this same call at `.../assign` — `finish`
  is the current name, use it.)

`order_id` is a **string** (e.g. `SS-117116818593238-325640-55`), not a
number.

Carries `Authorization: Bearer {ADVISORREACH_API_KEY}`. **Allow at least 300
seconds for a response** (`curl --max-time 300`).

## Before you call this

You need both:
- **The order to be `completed`, not just delivered-eventually.** Mailbox
  delivery takes **around 8 hours** after ordering, and the order cannot be
  finished before then. Check its `status` with `GET .../mailboxes/orders`
  (lists all the caller's orders) or `GET .../mailboxes/orders/{order_id}`
  first if you're not sure — don't call `finish` speculatively. See
  `email-outreach-mailboxes`'s "The order lifecycle" section for the full
  sequence, including why a `409` here means "still processing," not
  broken — it is the expected answer for roughly the first 8 hours, not a
  failure to retry around.
- A client account that already exists (`email-outreach-client`). If the
  customer doesn't have one yet, that has to happen first — this skill does
  not create one for them.

If either of these was done in an earlier turn, don't just assume it's still
true — check current state rather than reusing something you remember from
earlier in the conversation, especially the order's delivery status.

## Procedure

1. Confirm the order's `status` is `completed` (check `GET .../mailboxes/orders`
   if unsure — see "Before you call this" above).
2. Confirm which client account the mailboxes should go to — if the customer
   has more than one client account, ask which one; never guess.
3. Call `finish` to assign the order to that client. If it returns `409`, the
   order isn't `completed` yet — tell the customer to wait, don't retry.
4. Tell the customer the mailboxes are now connected to their account, and
   remind them plainly that this does not mean they're ready to send real
   outreach yet — warmup takes **weeks**, and there's no API call that tells
   you when it's "done"; it's just something that happens automatically over
   that time.

## Rules

- A 404 for either the order or the client id means it does not exist for
  this customer — never treat it as a permissions problem, and never try a
  different id to "see if that one works."
- Never expose internal order or client ids to the customer — refer to things
  by domain name, mailbox count, and the client's own name/email.
- Never claim mailboxes are connected before the API confirms the assignment
  succeeded.
- Don't re-run the assignment "just in case" if you're unsure whether it
  already happened — check the order's status first.
- A `409` from `finish` means the order is still processing — expected for
  roughly the first 8 hours, not an error to retry around.
