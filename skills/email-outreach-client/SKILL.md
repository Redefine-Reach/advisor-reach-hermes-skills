---
name: email-outreach-client
description: Create or look up the customer's SmartLead client account (the account cold-email mailboxes get attached to), and retrieve its login credentials. Use when the user asks to set up their SmartLead account, get a SmartLead login, or as the first step of setting up email outreach. Part of the email-outreach skill set.
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# Email Outreach — Client Account

If you have not read the `email-outreach` skill in this conversation, read it
first — it carries context you will otherwise miss, including the retry
contract this skill depends on and the overall cost picture.

This skill creates (or reuses) the customer's SmartLead client account — the
account that sending mailboxes get connected to later by
`email-outreach-connect` — and gets its login credentials.

## Endpoints

- `GET {ADVISORREACH_API_URL}/smartlead/v1/clients` — list this customer's
  existing client accounts. Check this first; do not create a second account
  for a customer who already has one unless they explicitly ask for another.
- `POST {ADVISORREACH_API_URL}/smartlead/v1/clients` — create one, body
  `{"name": "...", "email": "...", "company": "..."}` (`company` optional).
  **Usually free** — it only costs $29/month if the account's shared seat
  pool has none free, which you cannot check in advance (see `email-outreach`'s
  "What it costs"). Treat this as a normal free setup step, not a spend to ask
  permission for.
- `GET {ADVISORREACH_API_URL}/smartlead/v1/clients/{client_id}/api-key` —
  retrieve login credentials for an existing client account.

All calls carry `Authorization: Bearer {ADVISORREACH_API_KEY}`. **Allow at
least 300 seconds for a response** (`curl --max-time 300`) — creation
provisions upstream and is genuinely slow.

## Procedure

1. List existing clients. If the customer already has one and hasn't asked for
   a new one, use it — skip straight to step 4.
2. Confirm with the customer the name, email, and (optionally) company to
   create the account under — the same kind of confirmation you'd give any
   workspace fact you're about to act on. **Do not ask them to approve a
   possible $29/month seat charge first** — you have no way to check seat
   availability before or after this call, so asking answers nothing and only
   stalls the rest of the (free) setup. See `email-outreach`'s "What it costs"
   for why this step is treated differently from ordering mailboxes.
3. Create the client.
   - **On 504:** this is not a failure. Follow the retry contract in
     `email-outreach` exactly — re-issue the identical request once, same
     email address, no other changes. If the retry also fails, stop and tell
     the customer honestly rather than trying a third time or changing
     anything about the request.
   - **On a failure whose message mentions seats being exhausted or a
     configured ceiling:** that is a real billing wall, not a maybe — stop
     and tell the customer plainly rather than retrying with different values.
   - On success, treat it as free by default. This API does **not** report
     back whether a seat was purchased — do not claim it was free or that it
     cost money either way; you don't know, and neither claim is yours to make.
4. Retrieve the login credentials via the api-key endpoint (or use the ones
   returned directly by a successful creation call, if you just created it —
   no need to call api-key again in that case).
5. Hand the customer their SmartLead login (email + password/key), and tell
   them this account exists but has no sending mailboxes yet — that's the next
   step (`email-outreach-mailboxes`, then `email-outreach-connect`).

## Rules

- Never claim an account was created before the API confirms it (a 200/201
  response with a client back) — a 504 is not a confirmation either way; treat
  it exactly as the retry contract says, not as success or failure.
- Never expose the internal SmartLead client id to the customer. Refer to the
  account by the customer's own name/email, not by id.
- If listing returns another customer's data, or a lookup for a specific
  client 404s, that means it does not exist for this customer — never treat it
  as a permissions problem to route around.
- Do not create a second client account for a customer just because the first
  lookup was slow or ambiguous — check again rather than guessing.
