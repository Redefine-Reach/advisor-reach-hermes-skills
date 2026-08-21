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

- `POST {ADVISORREACH_API_URL}/smartlead/v1/mailboxes/orders/{order_id}/assign`
  — body `{"client_id": ...}`. Assigns the mailboxes in that order to that
  client.

Carries `Authorization: Bearer {ADVISORREACH_API_KEY}`. **Allow at least 300
seconds for a response** (`curl --max-time 300`).

## Before you call this

You need both:
- The order to have actually delivered. Mailbox delivery takes **around 8
  hours** after ordering — check `GET .../mailboxes/orders/{order_id}` first
  if you're not sure it's ready. Do not attempt to assign mailboxes that
  haven't delivered yet; tell the customer to wait instead.
- A client account that already exists (`email-outreach-client`). If the
  customer doesn't have one yet, that has to happen first — this skill does
  not create one for them.

If either of these was done in an earlier turn, don't just assume it's still
true — check current state rather than reusing something you remember from
earlier in the conversation, especially the order's delivery status.

## Procedure

1. Confirm the order has delivered (check status if unsure).
2. Confirm which client account the mailboxes should go to — if the customer
   has more than one client account, ask which one; never guess.
3. Assign the order to that client.
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
