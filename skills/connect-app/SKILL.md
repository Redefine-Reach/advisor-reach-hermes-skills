---
name: connect-app
description: Connect any outside app Composio supports (Gmail, Google Calendar, Notion, Slack, HubSpot, LinkedIn, Canva, GitHub, and hundreds more) to this box through Composio so its tools become available, and use those tools once connected. Use when the user asks to connect, link, hook up, or sign into an app, or when you need something from an app that is not connected yet. Sends the user one sign-in link they open in their own browser.
---

# Connect an outside app (Composio)

**Not for Circle.** Circle (circle.so) is AdvisorReach's own community, not a Composio app — use the `circle-member-token` skill for anything in Circle.

This box has a `composio` MCP server. It gives you four tools:

- `COMPOSIO_MANAGE_CONNECTIONS` — check whether an app is connected, or start connecting it.
- `COMPOSIO_SEARCH_TOOLS` — find the right tool for a task (e.g. "list recent gmail messages").
- `COMPOSIO_GET_TOOL_SCHEMAS` — the exact arguments a found tool takes.
- `COMPOSIO_MULTI_EXECUTE_TOOL` — run one or more found tools.

(Your runtime may show them prefixed, e.g. `mcp__composio__COMPOSIO_MANAGE_CONNECTIONS`.
Same tools.) If you do not have these tools at all, this box is not enabled for
Composio — use the `connect-mcp` skill instead.

The sign-in happens in the user's own browser on a page hosted by Composio. You never
see their password, a code, or a token, and neither does this box.

## Procedure — connecting

1. Identify the app's Composio toolkit slug — the lowercase app name (`gmail`,
   `googlecalendar`, `googledrive`, `notion`, `slack`, `hubspot`, `linkedin`, `canva`,
   `github`, `outlook`, `googlesheets`, and hundreds more). Every Composio app is available
   on this box. If unsure of the slug, call `COMPOSIO_SEARCH_TOOLS` with the app's name and
   use the toolkit it returns; if `COMPOSIO_MANAGE_CONNECTIONS` says the slug is unknown,
   tell the user the app is not available (or offer `connect-mcp` if they have an MCP URL).
2. Call `COMPOSIO_MANAGE_CONNECTIONS` with `{"toolkits": ["<slug>"]}` **once**.
   - If the result for that toolkit says the connection is already **active**, tell the
     user it is connected and go to "Using the app".
   - Otherwise it returns a `redirect_url` like `https://connect.composio.dev/link/lk_…`
     with status `initiated`.
3. Text the user that one link, in one message, e.g.
   "Tap this to sign in to Gmail — it works once and expires in 10 minutes:
   https://connect.composio.dev/link/lk_…"
   Tell them to sign in with the account they want connected and to reply here when done.
4. Wait for them to say they finished. **Do not call `COMPOSIO_MANAGE_CONNECTIONS`
   again to "check"** — each call mints a NEW link and invalidates nothing; the user
   would end up with a pile of links. Check by using the app (step 5).
5. When they say it is done, do the task they asked for (see "Using the app"). If the
   tool call fails because the app is not connected, the sign-in did not complete:
   call `COMPOSIO_MANAGE_CONNECTIONS` once more for a fresh link and repeat step 3.
   If it fails twice, say so plainly and stop — do not keep sending links.

## Using the app

1. `COMPOSIO_SEARCH_TOOLS` with a plain description of the task and the toolkit.
2. `COMPOSIO_GET_TOOL_SCHEMAS` for the tool(s) you will call, if the search result did
   not already include arguments.
3. `COMPOSIO_MULTI_EXECUTE_TOOL` with properly formed `arguments`.
4. Reply to the user in plain text — they are reading a text message. Summarize; do not
   paste raw JSON.

## Rules

- Never ask the user for a password, a code, or anything from the address bar.
- One link per app per attempt, and never repeat an old link — each works once.
- Never reveal the link to anyone but the user who asked.
- Anything that sends, posts, deletes, or changes data in the user's account
  (send an email, post to Slack, create a calendar event, update a HubSpot record)
  needs the user's explicit "yes" first, with a one-line summary of exactly what will
  be sent or changed. Reading is fine without asking.
- If `COMPOSIO_MANAGE_CONNECTIONS` says a toolkit slug is unknown, do not guess another
  spelling — tell the user the app is not available.
