# AdvisorReach Hermes Skills

Public, portable skills in the open `SKILL.md` format — usable by Hermes, Claude Code,
Codex, Cursor, and any SKILL.md-compatible agent.

## Install
```
npx skills add Redefine-Reach/advisor-reach-hermes-skills
```
Or add as a Claude Code plugin marketplace: `/plugin marketplace add Redefine-Reach/advisor-reach-hermes-skills`.

## Skills
### present-file
Turns a file the agent already has into a shareable public link. The host runtime injects
two env vars the skill reads:
- `ARTIFACT_DIR` — writable dir whose contents are served publicly.
- `ARTIFACT_BASE_URL` — public URL prefix for those files.
The skill copies the file into `ARTIFACT_DIR` under a random name and returns `ARTIFACT_BASE_URL/<name>`.

### listing-presentation
Generates a seller's pre-listing packet as a PDF from a locked branded template, filling in
advisor + property details gathered over the conversation, then delivers it via the
`present-file` skill.

### publish-site
Puts a real website live on a customer's own domain, with a real SSL certificate, via the
AdvisorReach API. A two-turn skill: turn 1 stages the site, gathers the customer's existing
DNS records (screenshot accepted), creates the DNS zone, and hands back the nameservers to
set at their registrar — with an explicit warning that changing nameservers moves the whole
domain, email included. Turn 2, once the customer confirms the nameserver change, polls
delegation and publishes, returning the live `https://` URL. The host runtime injects three
env vars the skill reads:
- `ADVISORREACH_API_URL` — base URL of the AdvisorReach API.
- `ADVISORREACH_API_KEY` — bearer key scoped to this customer.
- `SITE_DIR` — writable dir for the site's content.

### email-outreach (and its three children)
Sets up cold email outreach for a customer via the AdvisorReach API: a SmartLead client
account, sending mailboxes on a warmed-up domain, and the mailboxes connected to that
account. `email-outreach` is the parent — it explains the whole picture, the retry
contract, and what it costs — and points to three children that do the actual work:
- `email-outreach-client` — creates or reuses the customer's SmartLead client account and
  retrieves its login credentials. Creating one can purchase a $29/month seat; a 504 from
  the create call is not a failure (the client may already exist) and is retried once with
  the identical email address, since email is the idempotency key.
- `email-outreach-mailboxes` — searches for a sending domain/vendor and orders mailboxes.
  Costs around $13/domain/year plus around $4.50/mailbox/month; the price is always stated
  and confirmed before ordering, and a failed order is never retried automatically (unlike
  client creation, it isn't guaranteed idempotent).
- `email-outreach-connect` — assigns an already-ordered, delivered set of mailboxes to a
  client account so they become usable. Mailbox delivery takes ~8 hours; warmup after that
  takes weeks.

Each child says explicitly to read the `email-outreach` parent first if it hasn't already
been read in the conversation. All four calls carry `Authorization: Bearer
{ADVISORREACH_API_KEY}` and use a client-side timeout of at least 300 seconds
(`curl --max-time 300`), since creating a client provisions upstream and is slow. The
host runtime injects:
- `ADVISORREACH_API_URL` — base URL of the AdvisorReach API.
- `ADVISORREACH_API_KEY` — bearer key scoped to this customer.
