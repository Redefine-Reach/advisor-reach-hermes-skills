---
name: publish-site
description: Put a real website live on the customer's own domain name, with a real, publicly-trusted SSL certificate. Use when the user asks to "make me a website", "put this on my domain", "publish my site", "get raylopezteam.com pointed at this", or otherwise wants their own domain serving something the agent has built. This is a two-turn process — do not promise a live URL in the same turn you start it.
---

# Publish Site

Put a website live on a domain the customer already owns. The runtime tells you three things through the environment:

- `ADVISORREACH_API_URL` — the base URL of the AdvisorReach API.
- `ADVISORREACH_API_KEY` — the bearer key scoped to this customer. Send it as `Authorization: Bearer <key>`.
- `SITE_DIR` — a writable directory. Files you place here, under a site's id, are what gets served once the site is published.

Both `ADVISORREACH_API_URL`/`ADVISORREACH_API_KEY` and `SITE_DIR` are provided to you in your operating context (see your `SOUL.md`). If you cannot find them, tell the user you cannot publish sites right now — do not guess a URL, a key, or a directory.

## Why this takes two turns

A certificate cannot be issued for a domain until that domain's nameservers have actually been changed and the change has propagated across the public internet — that can take anywhere from minutes to many hours. There is no way to shortcut this. Turn 1 gets the domain pointed at us; turn 2, once that has happened, gets the certificate and makes the site live. Never tell the customer their site is live at the end of turn 1 — it is not.

## The single most important thing this skill does

Changing a domain's nameservers moves the **entire domain**, not just a website — email included. The instant the change takes effect, anything at the old provider that was not copied into the new zone stops resolving: inbound and outbound mail (MX, SPF, DKIM, DMARC), any other subdomains, verification records other services rely on, all of it. A DNS zone cannot be read back from the outside — there is no way for you or the API to look at what a customer currently has — so the only way to avoid breaking something is to ask the customer directly, get a complete answer, and get their explicit confirmation before telling them to make the change. Treat this step as the point of highest consequence in the whole flow. Do not rush it, do not assume "just a website" means there's nothing else on the domain, and do not proceed on a vague or partial answer.

## Turn 1 — build the site, gather records, create the zone

1. **Build and stage the site.** Write the site's HTML (and any assets) into `SITE_DIR` under a new subdirectory you choose an id for. If the user already gave you finished HTML, use it as-is; otherwise produce a reasonable page from what they've described. Confirm this before moving on to DNS — there's no point walking them through a nameserver change for a site that isn't ready.

2. **Ask what DNS records the domain currently has.** Do not ask this abstractly — ask them to open their current DNS provider's control panel (whatever registrar or host they use today) and tell you what's listed, or, easier for most people, **take and send a screenshot of that records page**. Explicitly offer the screenshot option; most people find it much easier than reading records aloud. Look in particular for:
   - Any mail-related records: `MX`, and TXT records for SPF, DKIM, DMARC.
   - Any subdomains in use (e.g. `www`, `mail`, `app`, `blog`) and what they point to.
   - Any verification TXT records other services (email, Google Workspace, Microsoft 365, other SaaS tools) may have put there.
   - Whether DNSSEC is turned on at the registrar — if so, say clearly that it has to be turned off before the switch or the domain will stop resolving entirely, and confirm with them that they've done it (or ask them to reach out to their registrar to do it) before continuing.

   If their answer looks incomplete — e.g. they only mention a website record and this is clearly a business with email on the domain — say so plainly and ask them to check again rather than proceeding on a guess. It is always better to ask twice than to break someone's email.

3. **Create the zone and import what they gave you.** Call the API to create a DNS zone for their domain and hand it the records they described, e.g.:
   - `POST {ADVISORREACH_API_URL}/dns/v1/zones` with `{"domain": "<their domain>"}` → returns a zone id and the 4 nameservers to hand back.
   - `POST {ADVISORREACH_API_URL}/dns/v1/zones/{zone_id}/import` with the record set you gathered.
   All calls carry `Authorization: Bearer {ADVISORREACH_API_KEY}`.

4. **Show them the assembled record set and get explicit confirmation.** Before saying anything about nameservers, list back every record you're about to carry over — in plain language, not raw DNS syntax — and ask them to check it against what they actually have. Do not proceed to step 5 until they've confirmed it looks right or corrected it.

5. **Explain nameservers plainly, then hand them over.** Tell them, in these terms or ones just as direct: changing their domain's nameservers moves control of the *entire domain* to us, not just the website — their email included — and anything not just confirmed in step 4 will stop working the moment the change takes effect. Only after that warning has landed, give them the 4 nameservers from the zone-creation response and ask them to set those at their registrar, replacing whatever is there now. Tell them to message back once it's done — and that it can take a while (minutes to hours, occasionally longer) to take effect everywhere, so don't worry if it isn't instant.

## Turn 2 — confirm, publish, and hand back the URL

Triggered when the customer says the nameservers are set (e.g. "done", "I changed it").

6. **Poll delegation — do not assume it's done because they said so.** Call `GET {ADVISORREACH_API_URL}/dns/v1/zones/{zone_id}/delegation` and check that it reports the nameservers as observed on the public internet. If it isn't there yet, tell the customer it's still propagating and that you'll check again — do not publish, and do not claim it's live.

7. **Publish.** Once delegation is confirmed, call `POST {ADVISORREACH_API_URL}/sites/v1/sites` (if you haven't already registered the site) and then `POST {ADVISORREACH_API_URL}/sites/v1/sites/{site_id}/publish`. This is what triggers certificate issuance — it cannot happen before delegation because the certificate authority also has to be able to see that we control the domain.

8. **Wait for it to actually be serving, then confirm before replying.** Poll `GET {ADVISORREACH_API_URL}/sites/v1/sites/{site_id}/status` until it reports the site as serving with a live `https://` URL. If it fails or times out, tell the customer honestly that publishing hasn't finished yet rather than guessing at a URL.

9. **Reply with the live link.** Once — and only once — the API confirms the site is serving, reply with the `https://` URL from the status response. Nothing else about the process needs to be in that final message.

## Rules

- Never expose `SITE_DIR` or any other local/internal path to the user — only the final `https://` URL.
- Never claim a site is live, or give out its URL, before the API itself reports it as serving. A delegated domain, a created zone, or a "should be ready soon" is not the same thing as live — check `status` and believe what it says, not what seems likely.
- If the customer's description of their current DNS records seems incomplete or uncertain, say so and ask again rather than proceeding — a missed record breaks something real (usually email) the moment nameservers flip, and there is no way to undo that from the outside.
- Always warn about the nameserver change in plain terms — "this moves your whole domain, email included" — before asking them to make it. Do not bury this in a longer message where it can be skimmed past.
- Do not promise, or imply, that the site will be live in the same turn you hand over nameservers. It cannot be — say so.
- If the API reports an error at any step, tell the customer what's blocked in plain terms (e.g. "the nameservers haven't updated everywhere yet") rather than surfacing a raw error code.
