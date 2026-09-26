---
name: smartlead-campaigns
description: "SmartLead cold-email campaigns: see, stats, write, launch. Use for ANY question or task about the customer's SmartLead campaigns, emails, sequences, leads, mailboxes, opens or replies. Works directly against SmartLead — not the OmegaAI MAB/Design workflow."
required_environment_variables:
  - ADVISORREACH_API_URL
  - ADVISORREACH_API_KEY
---

# SmartLead campaigns

**This skill is the ONLY way to see or change the customer's SmartLead campaigns.** It talks
to SmartLead directly with the customer's own SmartLead account. Do NOT use the OmegaAI
MAB / "Email Campaigns" Design pipeline, `Component Installs/Email Campaigns`, the
`Docs/AdvisorReach/email-campaigns` manual, or `connect-app` / Composio for campaigns — that
system is retired, and its tables are not the customer's campaigns. Setting up the account and
mailboxes in the first place is the `email-outreach` skill; everything after that is here.

Everything goes through one script, run from your code execution sandbox with this exact
absolute path (`$HERMES_HOME` is scrubbed from the sandbox; `/opt/data` is its value on every box):

    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py <command>

Every command prints ONE JSON object. The script fetches the account's API key itself and never
prints it — never ask for, show, or write down a SmartLead API key or password.

## See what's there (safe — no yes needed)

    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py account
    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py campaigns
    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py stats <campaign_id>
    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py sequences <campaign_id>
    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py mailboxes

- `campaigns` → `id`, `name`, `status` (`DRAFTED` = never sent, `ACTIVE` = sending, `PAUSED`,
  `COMPLETED`). When you report them, give the count by status and the names that matter — a
  customer with dozens of drafts wants "83 drafts, nothing sending yet", not 83 names.
- `stats` → `sent_count`, `open_count`, `reply_count`, `bounce_count`, … (SmartLead returns
  them as strings).
- `sequences` → the emails of a campaign in order: `seq_number`, `subject`, `email_body`,
  `delay_in_days` (days after the previous email).
- `mailboxes` → the sending addresses; `sending_ok`/`receiving_ok` false means the mailbox needs
  fixing before any campaign can send from it.

## Write a campaign (ask first)

Show the user exactly what you will create — name, every email's subject and body, the
mailbox it sends from, the schedule — and do it only after they say yes.

1. Create a draft: `smartlead.py create "<name>"` → `campaign_id`.
2. Write its emails: save a JSON list to a file, then
   `smartlead.py save-sequences <campaign_id> --file <path>`. Each item:
   `{"seq_number": 1, "seq_delay_details": {"delay_in_days": 0}, "subject": "…", "email_body": "…"}`
   (next emails: `seq_number` 2, 3… with the days to wait). `{{first_name}}` is the merge field.
3. Pick the mailbox: `smartlead.py attach-mailboxes <campaign_id> <mailbox_id>` (ids from `mailboxes`).
4. Set when it sends: `smartlead.py schedule <campaign_id> --timezone America/New_York`
   (defaults: Mon–Fri, 09:00–17:00, 20 minutes between emails, 50 new leads a day; override with
   `--days 1,2,3,4,5 --start-hour 09:00 --end-hour 17:00 --min-minutes-between 20
   --max-new-leads-per-day 50`).
5. Add leads: a JSON list of `{"email": "…", "first_name": "…", "last_name": "…"}` in a file, then
   `smartlead.py add-leads <campaign_id> --file <path>`.

## Send or stop (ask first, every time)

    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py start <campaign_id>
    python3 /opt/data/skills/smartlead-campaigns/scripts/smartlead.py pause <campaign_id>

`start` sends real email to real people. Say which campaign, how many leads, and from which
mailbox, and start only after an explicit yes. `pause` stops sending; also only on request.

## Sample emails / copy

To show example emails, write them yourself in the conversation (or from an existing campaign's
`sequences`); if the user wants a document, write it to a file and share it with the
`present-file` skill. Nothing reaches SmartLead until they approve and you run the steps above.

## Errors

| Output | Meaning | What to do |
|---|---|---|
| `no SmartLead account yet` | The account was never created | Use the `email-outreach` skill |
| `several SmartLead accounts` | More than one account | Ask which, then pass `--client-id <id>` before the command |
| `"status": 401` | SmartLead rejected the key | Report it — this is our configuration |
| `"status": 404` | Wrong campaign id | Re-run `campaigns` and use an id from it |
| `"status": 400/422` + `error` | SmartLead refused the request | Read `error`, fix the input, retry once |
