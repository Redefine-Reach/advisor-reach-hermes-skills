---
name: circle-member-token
description: "Circle community (circle.so): read, search, post, comment as a box member — mint a member token, find a post, comment on it. Use for ANY Circle request; Circle is AdvisorReach's own community, NOT a Composio/connect-app app."
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
  - CIRCLE_MEMBERS_FILE
---

# Circle — member access token

**Circle is AdvisorReach's own community at `https://advisorreach.circle.so`
(circle.so), and this skill is the ONLY way to reach it.** It is not a Composio
app: do not open `connect-app`, do not call `COMPOSIO_SEARCH_TOOLS` for it, and
do not ask the user for a link before you have looked. When someone says
"Circle", "the community", "Ryan's post", or "comment on the post", start here.

This box's Circle community members are a JSON array of
`{"handle": ..., "email": ..., "name": ...}`. Find the list by trying these
sources IN ORDER and using the first that yields a non-empty array:

1. `$CIRCLE_MEMBERS_FILE`, if that variable is set and non-empty:

       cat "$CIRCLE_MEMBERS_FILE"

2. The fixed default path — the box always mounts the file here:

       cat /opt/box/circle/members.json

3. The API, which returns the same list from the same source (the box's
   Terraform customer file), so it cannot disagree with the file:

       curl --max-time 30 -H "Authorization: Bearer $ADVISORREACH_API_KEY" \
         "$ADVISORREACH_API_URL/circle/v1/members"

Read the list from whichever source works, then find the email for the person
someone names.

**Do NOT conclude "this box has no Circle members" from `$CIRCLE_MEMBERS_FILE`
being unset.** The `execute_code`/terminal sandbox strips some environment
variables: measured 2026-09-16 on `ryan-radomski`, `CIRCLE_MEMBERS_FILE` was
absent from the sandbox `os.environ` while set in the box's real process env,
and `/opt/box/circle/members.json` was still readable. So an unset variable is a
sandbox artifact, not the answer. Only conclude there are no members if ALL
THREE sources above are absent or return an empty list — and never guess an
email address.

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

## Finding a post

**You read Circle by acting AS one of this box's members.** The members list is
ONLY the people this box may act as (mint a token for) — it is NOT a limit on what
you can READ. A member access token reads the ENTIRE community: every space and
every post, by ANY author, including people who are not in this box's members
list. So to find "Ryan's post" you do NOT need Ryan to be a member of this box —
you mint a token AS your own member (e.g. the box's member from `members.json`)
and read Ryan's posts with it. **Never reply that you can't access someone's
posts because they aren't a member of this box — that is wrong; your own member
token sees everyone.** And do it now, in this turn: mint the token and search —
do not answer that you "will find it first".

Every call below is `https://app.circle.so/api/headless/v1/...` with
`Authorization: Bearer {access_token}` and an explicit `User-Agent`. Endpoint
paths are from Circle's Member API spec
(`https://api-headless.circle.so/api/headless_client/v1/swagger.yaml`).

1. **Resolve the author** (a name like "Ryan"):

       curl --max-time 30 -H "Authorization: Bearer {access_token}" \
         -H "User-Agent: advisorreach-box/1.0" -H "Content-Type: application/json" \
         -X POST https://app.circle.so/api/headless/v1/search/community_members \
         -d '{"search_text": "Ryan", "per_page": 10}'

   Read `records[].id` (the `community_member_id`) and `records[].name`.

2. **List that author's posts** and pick the one the user means:

       curl --max-time 30 -H "Authorization: Bearer {access_token}" \
         -H "User-Agent: advisorreach-box/1.0" \
         "https://app.circle.so/api/headless/v1/community_members/{community_member_id}/posts?per_page=50"

   Each record has `id`, `name` (the title), `body_plain_text`, `space.slug`,
   `url`. **Match on meaning, not on the literal words** — a request like
   "Ryan's post about Total Expert" usually means the post that *asks* about
   CRMs ("Share your CRMS!"), because Total Expert is the user's answer, not
   the title. Read `body_plain_text` before deciding.

3. **Fallback — browse by space** when the author is unknown:

       curl --max-time 30 -H "Authorization: Bearer {access_token}" \
         -H "User-Agent: advisorreach-box/1.0" https://app.circle.so/api/headless/v1/spaces

   then, per space (`slug` or `id`):

       curl --max-time 30 -H "Authorization: Bearer {access_token}" \
         -H "User-Agent: advisorreach-box/1.0" \
         "https://app.circle.so/api/headless/v1/spaces/{space_slug}/posts?per_page=50"

4. **Search is title-only and is a helper, not the primary path.**
   `GET /api/headless/v1/search?search_text={words}` matches post titles;
   measured 2026-09-17: `total expert` → 0 results while the intended post was
   "Share your CRMS!"; `CRMS` → 1. Use it to confirm, never to conclude "no
   such post".

If nothing matches, reply with the titles you found (step 2) and ask which one.
Never invent a post, and never ask for a link before you have listed the posts.

## Commenting on a post

1. Draft the comment and show it to the user with the post title and URL.
   **Post only after they say yes** — a comment is visible to the whole
   community and is written as the member, not as you.
2. Create it:

       curl --max-time 30 -H "Authorization: Bearer {access_token}" \
         -H "User-Agent: advisorreach-box/1.0" -H "Content-Type: application/json" \
         -X POST "https://app.circle.so/api/headless/v1/posts/{post_id}/comments" \
         -d '{"comment": {"body": "We use Total Expert."}}'

   A `200` returns the `comment` (`id`, `post_id`, `body_text`, …). Reply with
   the post `url` so the user can see it. To answer an existing comment instead
   of the post, `POST /api/headless/v1/comments/{comment_id}/replies` with the
   same body shape.

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
