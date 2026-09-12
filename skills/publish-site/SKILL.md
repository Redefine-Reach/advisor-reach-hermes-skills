---
name: publish-site
description: Put a real website live on the customer's own domain name, with a real, publicly-trusted SSL certificate. Use when the user asks to "make me a website", "put this on my domain", "publish my site", "get raylopezteam.com pointed at this", or otherwise wants their own domain serving something the agent has built. This is a two-turn process — do not promise a live URL in the same turn you start it.
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
  - SITE_DIR
---

# Publish Site

Put a website live on a domain the customer already owns. The runtime tells you three things through the environment:

- `ADVISORREACH_API_URL` — the base URL of the AdvisorReach API.
- `ADVISORREACH_API_KEY` — the bearer key scoped to this customer. Send it as `Authorization: Bearer <key>`.
- `SITE_DIR` — a writable directory. Files you place here, under a site's id, are what gets served once the site is published.

Both `ADVISORREACH_API_URL`/`ADVISORREACH_API_KEY` and `SITE_DIR` are provided to you in your operating context (see your `SOUL.md`). If you cannot find them, tell the user you cannot publish sites right now — do not guess a URL, a key, or a directory.

## Why this takes two turns

The customer's domain's DNS is already hosted with us — that part isn't something this skill arranges, and there is no nameserver change to ask for. What still takes real time is Cloudflare validating domain control and issuing a publicly-trusted certificate for the site's hostname once we've added the records it needs to see; that can take anywhere from minutes to a couple of hours, and there's no way to shortcut it. Turn 1 builds the site and kicks off publishing; turn 2, once the certificate is actually active, makes the site live. Never tell the customer their site is live at the end of turn 1 — it is not.

## What this does — and doesn't — touch on the customer's domain

Because we already host the customer's DNS, publishing a site never involves a nameserver change and never touches anything else already on the domain. The publish flow itself adds exactly three records into the zone we manage, and nothing else:

- a `www` CNAME pointing at `customers.advisorreach.ai` — our shared reverse-proxy edge, which is what actually serves the site and is what Cloudflare issues the certificate for;
- a TXT record Cloudflare uses to validate domain control before it will issue that certificate;
- an apex (bare-domain) A record pointing at our ingress, whose only job is to 301-redirect visitors to `https://www.<their domain>` — a bare domain can't be a CNAME, so this is how someone typing the domain without `www` still lands on the real site.

None of this replaces or migrates anything: mail (MX, SPF, DKIM, DMARC), other subdomains, and any verification records the customer already has stay exactly as they are. There's no need to inventory the customer's DNS before proceeding, and no warning to deliver about moving control of the domain — that risk doesn't exist in this flow.

Deleting a site (`DELETE /sites/{id}`) fully tears down its resources — the Cloudflare custom hostname, the `www` CNAME + apex A + `_acme-challenge` TXT in the customer's GCP zone, and the k8s Ingress + its TLS secret.

## Cloudflare-for-SaaS: the self-zone caveat (you cannot test on a subdomain of advisorreach.ai)

A customer site is reverse-proxied by registering **`www.<customer-domain>`** (U.19) as a **custom hostname** on our
`advisorreach.ai` Cloudflare zone and CNAME-ing `www` (in the GCP zone we host) to `customers.advisorreach.ai`; the
apex `<customer-domain>` gets an A → LB that 301-redirects to `www` (a bare apex can't be a custom hostname — it
can't CNAME, U.7). This works ONLY when the customer domain is **NOT itself a zone in our Cloudflare account**. A hostname that is a subdomain of `advisorreach.ai` (e.g.
`sites-test.advisorreach.ai`) is resolved by Cloudflare *in-zone* — it
follows our own zone's DNS and uses that as the origin, which lands on a Cloudflare anycast IP → **Error 1000
"DNS points to prohibited IP"** (403). It is NEVER SaaS-routed. Proven by a sentinel test (point the hostname's own
record at an unreachable IP → the edge returns 522, following the hostname's OWN DNS, not the SaaS fallback).
Therefore: **onboard/validate on a real external customer domain whose DNS we host in GCP (NS-delegated to our
Cloud DNS) — never on a `*.advisorreach.ai` subdomain.** The fallback origin `proxy-fallback.advisorreach.ai` MUST
stay **proxied** (Cloudflare uses its content IP `34.58.195.165` as the origin; a DNS-only fallback origin is
rejected with Error 1040).

## Turn 1 — build the site and publish

1. **Build and stage the site.** Write the site's HTML (and any assets) into `SITE_DIR` under a new subdirectory you choose an id for. If the user already gave you finished HTML, use it as-is; otherwise produce a reasonable page from what they've described. Confirm this before moving on — there's no point publishing a site that isn't ready. Paths serve clean — a file staged as `about.html` is reachable at both `/about` and `/about.html`, so link internally however reads best; you don't need to add the `.html` extension.

2. **Register and publish the site.** Call the API to register the site and publish it — this is what triggers the `www` CNAME/TXT/apex-A records being added and the certificate being requested:
   - `POST {ADVISORREACH_API_URL}/sites/v1/sites` (if you haven't already registered the site) with the site's domain.
   - `POST {ADVISORREACH_API_URL}/sites/v1/sites/{site_id}/publish`.
   All calls carry `Authorization: Bearer {ADVISORREACH_API_KEY}`.

3. **Tell the customer what happens next, plainly.** Let them know their site is being set up and a certificate is being issued for it, that this can take a little while (minutes, occasionally longer), and that nothing else about their domain — email included — is affected. Tell them you'll confirm once it's actually live; don't ask them to do anything to their DNS, because there's nothing for them to do.

## Turn 2 — confirm and hand back the URL

Triggered either by the customer checking back in, or by you following up once enough time has passed.

4. **Wait for it to actually be serving, then confirm before replying.** Poll `GET {ADVISORREACH_API_URL}/sites/v1/sites/{site_id}/status` until it reports the site as serving with a live `https://` URL (this is also when the certificate has finished issuing). If it fails or times out, tell the customer honestly that publishing hasn't finished yet rather than guessing at a URL.

5. **Reply with the live link.** Once — and only once — the API confirms the site is serving, reply with the `https://` URL (the `www.<their domain>` form) from the status response. Nothing else about the process needs to be in that final message.

## Rules

- Never expose `SITE_DIR` or any other local/internal path to the user — only the final `https://` URL.
- Never claim a site is live, or give out its URL, before the API itself reports it as serving. A registered site or a "should be ready soon" is not the same thing as live — check `status` and believe what it says, not what seems likely.
- Do not promise, or imply, that the site will be live in the same turn you publish it. It cannot be — say so.
- Don't ask the customer to change anything on their domain's DNS or nameservers — this flow never requires it, and telling them otherwise will only confuse them.
- If the API reports an error at any step, tell the customer what's blocked in plain terms (e.g. "the certificate hasn't finished issuing yet") rather than surfacing a raw error code.
