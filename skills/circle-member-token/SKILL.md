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

**Before saying this box has no Circle members, actually look.** Run
`echo "${CIRCLE_MEMBERS_FILE:-<unset>}"` and `cat "$CIRCLE_MEMBERS_FILE"` and
report what they printed. Do NOT assert "CIRCLE_MEMBERS_FILE is not configured"
from memory or assumption — on 2026-09-14 two different boxes claimed exactly
that while the variable was set and the file was present with the right member
in it, and the same agent printed both correctly when asked to run the commands.
A claim about configuration is a measurement, not a guess.

If the variable really is unset, this box has no Circle members declared. Say
so — do not guess an email address. The variable is rendered only when members
exist, so its absence is the answer, not a missing configuration.

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
      "community_id": 592032
    }

**`access_token` is valid for roughly one hour.** Mint one when you start
working on someone's behalf and use it for that piece of work. Do not save it
for later, do not write it to a file, and do not carry it into a conversation
tomorrow — mint a fresh one. There is no penalty for minting again.

Use it against Circle's Member API as `Authorization: Bearer {access_token}`.

## Using the token

The Member API base URL is `https://app.circle.so/api/headless/v1`. To read the
member's own record:

    curl --max-time 30 \
      -H "Authorization: Bearer {access_token}" \
      https://app.circle.so/api/headless/v1/community_member

    {"id":87952792,"user_id":36492293,"public_uid":"cf2d7568","email":"ryan@getomega.ai","name":"Ryan Radomski",...}

**The endpoint noun is `community_member`, singular.** `community_members`,
`members`, and `members/me` are not endpoints — they do not exist on this API.

### ALWAYS send a User-Agent header

`app.circle.so` sits behind Cloudflare, which **bans Python's default
`Python-urllib/…` signature** and answers `403` with error code `1010`
("browser signature banned"). Any explicit User-Agent gets through. Measured on
a live box, 2026-09-14, same token and same URL:

| Request headers | Result |
|---|---|
| `Authorization` only (urllib default UA) | **403 / 1010** |
| `Authorization` + `Origin` + `Referer` (still urllib default UA) | **403 / 1010** |
| `Authorization` + any explicit `User-Agent` | **200** |
| `curl` (sends its own UA) | **200** |

So: `curl` works as-is. If you use Python, set the header explicitly —
`{"User-Agent": "advisorreach-box/1.0"}` is enough. Origin and Referer make no
difference; do not waste a retry on them.

**A `403` with code `1010` is a REAL Cloudflare block and means your User-Agent
was missing — it is not a permissions problem, not an expired token, and not an
unaccepted invitation.** Add the header and retry before concluding anything
about the member's account.

**Rule: a non-JSON body from `app.circle.so` means the path is wrong.** A bad
path returns Circle's SPA HTML with a `404` status — that one is not a block.
Check `content-type` before parsing. Distinguish the two:

- HTML body + `404` → wrong path. Re-read the endpoints above.
- JSON/text + `403` + `1010` → missing User-Agent. Add it and retry.

**Do not fall back to the Circle admin API.** The admin API is a different
credential with different scope. Falling back to it when a member-scoped read
fails silently defeats the point of a member-scoped token and makes the
feature untestable — if a member-scoped read fails, report the failure, don't
paper over it with admin access.

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
| `403` + code `1010` | Cloudflare banned the default `Python-urllib` User-Agent | Set an explicit `User-Agent` and retry — this is NOT a permissions or account problem |
| `502` | Circle rejected our credential | Report it — this is our configuration, not something you can fix |
| `504` | Circle was slow | Retry once; minting has no side effects, so a retry is safe |
