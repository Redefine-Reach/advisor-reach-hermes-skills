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
