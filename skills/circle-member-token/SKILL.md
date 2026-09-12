---
name: circle-member-token
description: Get a Circle access token that acts as one of this box's team members, so you can read or post in the Circle community as that person. Use when asked to do something in Circle on behalf of a named teammate.
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
  - CIRCLE_MEMBERS_FILE
---

# Circle — member access token

This box's Circle community members are listed in the file named by
`$CIRCLE_MEMBERS_FILE` (on a normal box: `/opt/box/circle/members.json`):

    cat "$CIRCLE_MEMBERS_FILE"

A JSON array of `{"handle": ..., "email": ..., "name": ...}`. Read it to find
the email for a person someone names.

**If `CIRCLE_MEMBERS_FILE` is not set, this box has no Circle members declared.**
Say so — do not guess an email address, and do not go looking for the file
anyway. The variable is rendered only when members exist, so its absence is the
answer, not a missing configuration.

## Getting a token

    POST {ADVISORREACH_API_URL}/circle/v1/auth-token
    Authorization: Bearer {ADVISORREACH_API_KEY}
    Content-Type: application/json

    {"email": "someone@example.com"}

The email must be one from `members.json`. Any other address returns `404` —
including a real Circle member who belongs to a different box.

`GET {ADVISORREACH_API_URL}/circle/v1/members` returns the same list the file
holds, if you would rather ask than read the file. Both come from the same
source (the box's Terraform customer file), so they cannot disagree.

Use `curl --max-time 30`. This is one hop to Circle and back, not a provisioning
call; if it has not answered in 30 seconds it is a fault to report, not a reason
to retry with a bigger number.

## The token expires in about an hour

The response looks like:

    {
      "access_token": "...",
      "refresh_token": "...",
      "access_token_expires_at": "...",
      "refresh_token_expires_at": "...",
      "community_member_id": 87952792,
      "community_id": 1
    }

**`access_token` is valid for roughly one hour.** Mint one when you start
working on someone's behalf and use it for that piece of work. Do not save it
for later, do not write it to a file, and do not carry it into a conversation
tomorrow — mint a fresh one. There is no penalty for minting again.

Use it against Circle's Member API as `Authorization: Bearer {access_token}`.

## What this does NOT do

- **It does not create, rename or remove members.** Membership is managed in
  Terraform. If someone asks you to add a teammate to Circle, say that it is a
  change to `terraform/customers/<box>.yaml` and not something you can do.
- **It does not let you act as someone outside this box.** The API checks the
  requested email against this box's own list before doing anything.

## Errors

| Status | Meaning | What to do |
|---|---|---|
| `404` | The email is not one of this box's members | Re-read `$CIRCLE_MEMBERS_FILE`; do not retry with a guessed address |
| `502` | Circle rejected our credential | Report it — this is our configuration, not something you can fix |
| `504` | Circle was slow | Retry once; minting has no side effects, so a retry is safe |
