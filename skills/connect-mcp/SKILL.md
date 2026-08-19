---
name: connect-mcp
description: Connect an outside service (Gmail, Notion, Canva, and similar) to this box so its tools become available. Use when the user asks to connect, link, hook up, or sign into a service, or when you need a tool from a service that is not connected yet. Sends the user a link they open in their own browser to sign in.
---

# Connect an outside service

Some services expose their tools over MCP and require the user to sign in first.
The sign-in has to happen in the user's own browser — you cannot do it for them,
and you never see their password or any authorization code.

The runtime gives you:

- `MCP_OAUTH_CONNECT_BASE_URL` — the page the user opens to finish signing in.
- The broker, reachable from your code execution sandbox at
  `http://127.0.0.1:8090` — it is what drives the sign-in.

## Procedure

1. Find the service's MCP endpoint URL. Ask the user for it if you do not know it;
   do not guess a URL.
2. Choose a short server name. If the user already has an account of this service
   connected and wants another, pick a DIFFERENT name that says which account it is
   (for example `notion-work` alongside `notion-personal`). Two accounts of the same
   service must never share a name — the name is how they are kept apart.
3. Register the server:
   `hermes mcp add <name> --url <url> --auth oauth`
4. Start a flow:
   `POST http://127.0.0.1:8090/flow` with `{"server": "<name>"}`.
   You get back a `nonce`.
5. Text the user exactly this link and nothing else on the line:
   `<MCP_OAUTH_CONNECT_BASE_URL>#<this-box-hostname>/<nonce>`
   Tell them it opens in their browser, that the first time they will be asked to add
   a small browser add-on, and that they should sign in with the account they want
   connected.
6. Wait. Poll `GET https://<this-box-hostname>/oauth/flow/<nonce>/status` every 15
   seconds, for up to 30 minutes.
   - `"reserved"` — they have not started yet. Say nothing.
   - `"armed"` — they are signing in right now. Say nothing.
   - `"authorized"` — tell them it is connected and name the service.
   - `"failed"` or `"expired"` — tell them it did not go through and offer to send a
     fresh link. Start over from step 4 with a new nonce; a nonce is single use.

## Rules

- Never ask the user for a password, a code, or anything from the address bar. The
  add-on handles that. If a user offers you a code, tell them not to send it.
- One connection at a time on a box. If a flow is already in progress, wait for it to
  finish before starting another.
- Never reveal the nonce link to anyone but the user who asked, and never repeat an
  old link — each one works once.
- Do not invent an MCP endpoint URL. If you do not know it, ask.
- Some services do not support automatic sign-up for apps like this one. If a flow
  keeps failing, say so plainly and stop retrying rather than sending link after link.
