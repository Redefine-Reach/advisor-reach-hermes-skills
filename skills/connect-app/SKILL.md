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
   `github`, `outlook`, `googlesheets`, and hundreds more). Use the Composio tool
   results to establish availability. If unsure of the slug, call
   `COMPOSIO_SEARCH_TOOLS` with the app's name and
   use the toolkit it returns; if `COMPOSIO_MANAGE_CONNECTIONS` says the slug is unknown,
   tell the user the app is not available (or offer `connect-mcp` if they have an MCP URL).
2. See what is already connected: `COMPOSIO_MANAGE_CONNECTIONS` with
   `{"toolkits": [{"name": "<slug>", "action": "list"}]}`. It returns each connected account's
   id, alias and status, and has no side effects.
   - One ACTIVE account and the user wants to use the app → go to "Using the app".
   - The user wants to add ANOTHER account of the same app (a second Gmail, a personal
     calendar) → ask what to call it if they did not say ("work"? "personal"?), then step 3
     with that alias. If the existing account has no alias yet, first name it:
     `{"toolkits": [{"name": "<slug>", "action": "rename", "account_id": "<id from list>", "alias": "work"}]}`.
   - Nothing connected → step 3 (an alias is optional for the first account; use one if the
     user gave a name).
3. Start the connection **once**: `COMPOSIO_MANAGE_CONNECTIONS` with
   `{"toolkits": [{"name": "<slug>", "action": "add", "alias": "<alias or omit>"}]}`.
   It returns a `redirect_url` like `https://connect.composio.dev/link/lk_…` with status
   `initiated`. (Boxes can hold up to 3 accounts per app; a 4th `add` is refused — offer to
   `remove` one first, with the user's explicit yes.)
4. Text the user that one link, in one message, e.g.
   "Tap this to sign in to Gmail as your personal account — it works once and expires in 10 minutes:
   https://connect.composio.dev/link/lk_…"
   Tell them to sign in with the account they want connected and to reply here when done.
5. Wait for them to say they finished. Then confirm with ONE `action: "list"` call that the new
   account is ACTIVE (this is the only "check" — never repeat `add` to check; each `add` mints a
   new link). If it is not active, `add` once more for a fresh link and repeat step 4. If it
   fails twice, say so plainly and stop — do not keep sending links.

## Using the app

1. `COMPOSIO_SEARCH_TOOLS` with a plain description of the task and the toolkit.
2. `COMPOSIO_GET_TOOL_SCHEMAS` for the tool(s) you will call, if the search result did
   not already include arguments.
3. `COMPOSIO_MULTI_EXECUTE_TOOL` with properly formed `arguments` — and, when the app has
   more than one connected account, `"account": "<alias or id>"` on each tool:
   - the user named one ("my personal gmail", "the work calendar") → use that alias;
   - they did not, and the request only makes sense for one → ask once, briefly ("Work or
     personal Gmail?"), then pass it;
   - they did not and either would do (e.g. "do I have any unread mail") → run the tool once
     per account and label the results.
   With a single connected account, omit `account`.
4. Reply to the user in plain text — they are reading a text message. Summarize; do not
   paste raw JSON.

## Rules

- Never ask the user for a password, a code, or anything from the address bar.
- One link per app per attempt, and never repeat an old link — each works once.
- Never reveal the link to anyone but the user who asked.
- Anything that sends, posts, deletes, or changes data in the user's account
  (send an email, post to Slack, create a calendar event, update a HubSpot record)
  requires explicit authorization for that exact action and scope. Reuse valid,
  current authorization for the named action and account. Confirm only when
  authorization is missing or the scope has materially changed, summarizing exactly
  what will be sent or changed **and which account it goes from** when there are
  several. Reading relevant information is fine without asking.
- `action: "remove"` deletes a connected account — only with the user's explicit yes, and
  never to "fix" a failed sign-in.
- If `COMPOSIO_MANAGE_CONNECTIONS` says a toolkit slug is unknown, do not guess another
  spelling — tell the user the app is not available.
- If the tool call is rejected because `toolkits` must be a list of strings, this box has not
  been restarted since multi-account was switched on: use `{"toolkits": ["<slug>"]}` for
  this session and tell the user a second account will be possible after the next update.
