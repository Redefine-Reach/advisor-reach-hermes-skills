---
name: ghl
description: "GoHighLevel (GHL/LeadConnector) CRM: connect, read, write contacts, locations and any GHL API call with the token saved on this box. Use for ANY GoHighLevel/GHL/LeadConnector request; NOT a Composio/connect-app app."
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# GoHighLevel (GHL)

**GoHighLevel (also called GHL, HighLevel, or LeadConnector) is reached ONLY through this
skill.** Do not open `connect-app`, do not call `COMPOSIO_SEARCH_TOOLS` or
`COMPOSIO_MANAGE_CONNECTIONS` for it, and do not use `connect-mcp`. The user signs in once;
the token is then saved on this box and this skill's script uses it for every call.

Everything goes through one script. Run it from your code execution sandbox, with this exact
absolute path (`$HERMES_HOME` is scrubbed from the sandbox; `/opt/data` is its value on every box):

    python3 /opt/data/skills/ghl/scripts/ghl.py <command>

Every command prints ONE JSON object. The script never prints the token — never try to read
the files in `/opt/data/ghl/` yourself, and never show a token, the API key, or a local path
to the user.

## Step 1 — ALWAYS check first

    python3 /opt/data/skills/ghl/scripts/ghl.py status

- `"connected": true` → go to Step 3 (status finishes an approved sign-in itself).
  `location_id` is the GoHighLevel sub-account you can reach; `scope` is what you may do there.
- `"pending": true, "waiting_for_user": true` → the user has not approved yet: ask them to
  finish signing in, do not send a new link.
- `"connected": false` without `pending` → Step 2.

`access_token_expired: true` is NOT a reason to reconnect: Step 3 refreshes it for you.

## Step 2 — Connect (only when not connected)

a. Get a link:

       python3 /opt/data/skills/ghl/scripts/ghl.py connect

   Text the user the `connect_url`, and tell them: open it, pick the GoHighLevel sub-account
   (location) you want me to work in, approve, then text me "done". The link is good for 30
   minutes.

b. When they say they are done, run `status` (it saves the token the moment they have
   approved):

       python3 /opt/data/skills/ghl/scripts/ghl.py status

   - `"connected": true` → connected. Tell them which location you are connected to
     (`location_id`) and carry on with what they asked.
   - `"pending": true, "waiting_for_user": true` → they have not finished. Ask them to
     finish signing in and tell you when; do not send a new link yet.
   - `"connected": false` without `pending` → the link expired or failed. Run `connect`
     again and send the new link.

## Step 3 — Call GoHighLevel

    python3 /opt/data/skills/ghl/scripts/ghl.py api <METHOD> '<path>' [--data '<json>']

`{locationId}` anywhere in the path or the `--data` body is replaced with the connected
location. Always quote the path. The script adds the token and GHL's required `Version: 2021-07-28` header, and
refreshes the token itself when it is about to expire. Output: `{"status": <http>, "body": ...}`.

Examples (GHL API v2, base `https://services.leadconnectorhq.com`):

    # the connected sub-account
    python3 /opt/data/skills/ghl/scripts/ghl.py api GET '/locations/{locationId}'

    # list / search contacts
    python3 /opt/data/skills/ghl/scripts/ghl.py api GET '/contacts/?locationId={locationId}&limit=20'
    python3 /opt/data/skills/ghl/scripts/ghl.py api GET '/contacts/?locationId={locationId}&query=smith'

    # one contact
    python3 /opt/data/skills/ghl/scripts/ghl.py api GET '/contacts/<contactId>'

    # create a contact
    python3 /opt/data/skills/ghl/scripts/ghl.py api POST '/contacts/' --data '{"locationId": "{locationId}", "firstName": "Jane", "lastName": "Doe", "email": "jane@example.com"}'

    # update a contact
    python3 /opt/data/skills/ghl/scripts/ghl.py api PUT '/contacts/<contactId>' --data '{"tags": ["buyer"]}'

**Writes need a yes.** Before any `POST`, `PUT`, `PATCH` or `DELETE`, tell the user exactly
what you will create or change and do it only after they say yes.

## Errors

| Output | Meaning | What to do |
|---|---|---|
| `"connected": false` from `api` | Not connected | Step 2 |
| `"reconnect": true` | GoHighLevel no longer accepts the saved token (app removed or access revoked) | `disconnect`, then Step 2 |
| `status` 401 from `api` after the automatic retry | Same as above | `disconnect`, then Step 2 |
| `status` 403 from `api` | The connection's `scope` does not allow this call | Tell the user; do not retry |
| `status` 422 / 400 from `api` | Bad path or body | Fix the request; read `body` |
| `status` 502 / 504 from the refresh | Our side or GoHighLevel was slow/unavailable | Retry once; it is safe |

To remove the saved token: `python3 /opt/data/skills/ghl/scripts/ghl.py disconnect`.
