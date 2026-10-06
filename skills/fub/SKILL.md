---
name: fub
description: "FUB CRM. NOT a Composio/connect-app app. Read and write. Follow Up Boss leads and people on this box: connect, look up, notes, and person fields."
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# Follow Up Boss (FUB)

**Follow Up Boss (also called FUB) is reached ONLY through this skill.** Do not open `connect-app`,
do not call `COMPOSIO_SEARCH_TOOLS` or `COMPOSIO_MANAGE_CONNECTIONS` for it, and do not use
`connect-mcp`. Do not ask the user to paste an API key. The user signs in once through
AdvisorReach; the token is then saved on this box and this skill's script uses it.

Everything goes through one script. Run it from your code execution sandbox, with this exact
absolute path (`$HERMES_HOME` is scrubbed from the sandbox; `/opt/data` is its value on every box):

    python3 /opt/data/skills/fub/scripts/fub.py <command>

Every command prints ONE JSON object. The script never prints the token — never try to read the files in `/opt/data/fub/` yourself, and never show a token, the API key, a system key, or a local path to the user.

Texting or emailing a lead is not a Follow Up Boss call. To text a lead, use `sms-send-confirmed`
only. This skill must not send texts, emails, or action plans.

## Step 1 — ALWAYS check first

    python3 /opt/data/skills/fub/scripts/fub.py status

- `"connected": true` → go to Step 3 (status finishes an approved sign-in itself).
  `account_id` is the Follow Up Boss account you can reach; `scope` is what you may do there.
  `system` is the registered system name, not a secret.
- `"pending": true, "waiting_for_user": true` → the user has not approved yet: ask them to
  finish signing in, do not send a new link.
- `"connected": false` without `pending` → Step 2.
- `"error": "credential directory is not private"` or `"credential storage is not private"` →
  stop. Do not chmod the files and do not read them.

`access_token_expired: true` is NOT a reason to reconnect: Step 3 refreshes it for you.

## Step 2 — Connect (only when not connected)

a. Get a link:

       python3 /opt/data/skills/fub/scripts/fub.py connect

   Text the user the `connect_url`, and tell them: open it, sign in to Follow Up Boss, approve,
   then text me "done". The link is good for the `expires_in_seconds` the script reports.

b. When they say they are done, run `status` (it saves the token the moment they have
   approved):

       python3 /opt/data/skills/fub/scripts/fub.py status

   - `"connected": true` → connected. Tell them the account (`account_id`) and carry on.
   - `"pending": true, "waiting_for_user": true` → they have not finished. Ask them to
     finish signing in and tell you when; do not send a new link yet.
   - `"connected": false` without `pending` → the link expired or failed. Run `connect`
     again and send the new link.

## Step 3 — Call Follow Up Boss

    python3 /opt/data/skills/fub/scripts/fub.py api <METHOD> '<path>' [--data '<json>'] [--confirm-write]

Always quote the path. The host is fixed at `https://api.followupboss.com/v1`. Pass a relative
path (`/people?limit=10`). The script adds the bearer token and `X-System`. It does not send
a system key. It refreshes the token itself when it is about to expire. Output:
`{"status": <http>, "body": ...}`, plus `retry_after` and `rate_limit` when Follow Up Boss
sends them.

Look up one person with a narrow query. Use `limit` of 100 or less (the API maximum). Prefer
the `next` cursor over a deep `offset`. Do not pass `fields=all`, and do not fire extra GETs
to guess an endpoint. Pages over 1 MiB come back as an error with no partial list.

If `body._metadata.nextLink` is present and it pointed at `api.followupboss.com`, the script
has rewritten it to a relative path. Pass that path to the next GET:

    python3 /opt/data/skills/fub/scripts/fub.py api GET '/people?limit=10&next=...'

You may also pass the original absolute `https://api.followupboss.com/v1/...` link; the script
rewrites it. Any other host is rejected.

Examples:

    # narrow people search
    python3 /opt/data/skills/fub/scripts/fub.py api GET '/people?limit=10&name=Jane'

    # one person
    python3 /opt/data/skills/fub/scripts/fub.py api GET '/people/4242'

    # add a note — only after they say yes
    python3 /opt/data/skills/fub/scripts/fub.py api POST '/notes' --confirm-write --data '{"personId": 4242, "subject": "Call", "body": "Call back Thursday"}'

    # update contact fields — only after they say yes
    python3 /opt/data/skills/fub/scripts/fub.py api PUT '/people/4242' --confirm-write --data '{"firstName": "Jane", "lastName": "Doe"}'

**Writes need a yes.** Before any allowlisted write, tell the user exactly what you will create
or change and wait for yes. Only then pass `--confirm-write`. The flag alone is not approval.

The script also enforces a write allowlist. `--confirm-write` does not override it.

Allowed:

- `POST /notes` with only `personId` (positive integer), `body`, and optional `subject` and `isHtml`
- `PUT /people/{id}` with only `firstName`, `lastName`, `name`, `emails`, `phones`, `addresses`,
  `background`, and `price`

Refused, flag or not: `DELETE`, `PATCH`, `POST /events`, `POST /people`, action plans
(`/actionPlansPeople` and the rest of `/actionPlans`), `/textMessages`, `/emails`, `/webhooks`,
`/users`, `/oauthApps`, and any other write. `PUT /people/{id}` refuses `stage`, `source`,
`assignedUserId`, `tags`, and any field not in the list above — those can start Follow Up Boss
automation. If the error says writes are disabled, stop; do not look for another way to write.

Prefer `--data`. `--data-file` cannot read credential or token files, anything under
`/opt/data/fub/`, or a JSON file sitting directly in the Hermes home. If it refuses, use `--data`.

## Errors

| Output | Meaning | What to do |
|---|---|---|
| `"connected": false` from `api` | Not connected | Step 2 |
| `"reconnect": true` | Follow Up Boss no longer accepts the saved token | `disconnect`, then Step 2 |
| `status` 401 from `api` after the automatic retry | Same as above | `disconnect`, then Step 2 |
| `status` 403 from `api` | The connection's `scope` does not allow this call | Tell the user; do not retry |
| `status` 422 / 400 from `api` | Bad path or body | Fix the request; read `body` |
| `status` 429 from `api` | Rate limited. `retry_after` is seconds to wait. `rate_limit` has `limit`, `remaining`, `window`, and `context` | Wait `retry_after`, then retry once if this was a GET. Do not retry a write. Do not send other calls in between |
| `not on the write allowlist` / `DELETE is not allowed` | This write can message someone or start an action plan | Do not retry. Notes and the person fields listed above are the only writes |
| `credential storage is not private` | The saved token is readable by someone else | Stop. Do not read or chmod the file |
| `status` 502 / 504 from the refresh | Our side or Follow Up Boss was slow/unavailable | Retry the refresh once by running the same `api` command again; it is safe |

On a 429 the request was not processed. A write that returns `outcome_unknown: true` might have
landed; do not blindly repeat it. Ask the user before you reconcile.

To remove the saved token: `python3 /opt/data/skills/fub/scripts/fub.py disconnect`.

## AdvisorReach API FUB Mount

This skill authenticates to `$ADVISORREACH_API_URL` with `Authorization: Bearer $ADVISORREACH_API_KEY`.
Paths are namespaced under `/crm/v1/fub/` so they do not collide with the GoHighLevel mount at
`/crm/v1/connect`, `/crm/v1/claim`, and `/crm/v1/refresh`.

| Call | Body | 200 | Other |
|---|---|---|---|
| `POST /crm/v1/fub/connect` | empty | `{connect_url, state, expires_in_seconds}` | any other status is an error; nothing is stored |
| `POST /crm/v1/fub/claim` | `{"state": "<state from connect>"}` | token object below | `409` still waiting (pending file kept); `404` or `410` expired (pending file removed) |
| `POST /crm/v1/fub/refresh` | `{"refresh_token": "<saved refresh token>"}` | token object below | `409` means the user must reconnect (`reconnect: true`) |

`connect_url` must be `https`. Token object fields this skill stores:

- `access_token` (required) — Follow Up Boss OAuth access token, sent as `Authorization: Bearer`
- `refresh_token` (required)
- `expires_in` (required, seconds, integer ≥ 1)
- `system` (required) — registered `X-System` **name** only, sent as the `X-System` header
- `scope`, `account_id`, `user_id` (optional strings)

The mount keeps `X-System-Key`, the OAuth client secret, and any API key. If a response includes
those fields, this skill drops them and does not send `X-System-Key`. Follow Up Boss REST is
always `https://api.followupboss.com/v1` plus the relative path.
