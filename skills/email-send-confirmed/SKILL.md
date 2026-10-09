---
name: email-send-confirmed
description: "Email one person from the advisor's Gmail. Show recipient, subject, a body preview, and a Why line, and send only after they reply SEND."
required_environment_variables:
  - TELNYX_SMS_ALLOWED_USERS
optional_environment_variables:
  - TELEGRAM_ALLOWED_USERS
---

# Email send confirmed

This is the only path that may email a third party from the advisor's Gmail.
It is one plain-text message, from one connected Gmail account, after the
owner confirms. The script calls Composio `GMAIL_SEND_EMAIL` itself. You do
not.

You do not send any other way. Never call `GMAIL_SEND_EMAIL`,
`GMAIL_REPLY_TO_THREAD`, `GMAIL_FORWARD_MESSAGE`, `GMAIL_SEND_DRAFT`, or
`GMAIL_CREATE_EMAIL_DRAFT`, including through `COMPOSIO_MULTI_EXECUTE_TOOL`.
Do not create a draft and then send it. Do not send the message through the
browser or computer-use. Do not pass a Cc, a Bcc, an attachment, or HTML.
Do not set `EMAIL_SEND_TRANSPORT` or `EMAIL_SEND_CONFIRMED_TEST`. Do not
print `COMPOSIO_API_KEY`. The script reads that key from the box environment.
If this script is not the thing that sends, the email has not been confirmed.

## When this skill applies

Use it when the owner asks you to email a named person from their Gmail.

Do not use it for SmartLead cold email. That stays `smartlead-campaigns`.
Do not use it to answer the owner in this thread. A scheduled job, a standing
job, or a cron run must not stage or send. A delegated child must not stage
or send.

Prepare-never-send stays the default everywhere else. This skill is the
explicit owner-gated exception, and only for one named recipient at a time.

## What you run

On a box the script is:

`python3 /opt/data/skills/email-send-confirmed/scripts/email_send_confirmed.py`

If that file is missing, say so and stop. Do not search for a Gmail send
tool. Invoke it from `execute_code` with an argument list (so the body is
one argument).

The approver is the E.164 of the person texting you on SMS, or their
Telegram user id when they confirm from Telegram. The E.164 must be on
`TELNYX_SMS_ALLOWED_USERS`. `TELEGRAM_ALLOWED_USERS` is optional. When it
is set, a Telegram id on that list may confirm. When it is unset, only an
allowlisted SMS owner can confirm.

`--from-account` is the mailbox address or the alias the owner will
recognize (`advisor@example.com`, `work`, `personal`). `--connected-account`
is that account's Composio id from `COMPOSIO_MANAGE_CONNECTIONS` `list`
(the `id`, one token such as `ca_...`). The script sends only with the
staged id. It does not pick a default account.

## Turn 1 — stage, then stop

1. One named person. If they ask for more than one address, a Cc, a Bcc, a
   batch, a CSV, or a list, refuse in your reply and stop. Do not call
   `stage`.
2. One plain-text body, 8000 characters or fewer, and one subject, 200
   characters or fewer. No HTML. If you need it shorter, ask before staging.
3. Run `stage` with `--approver`, `--to`, `--subject`, `--body`,
   `--from-account`, `--connected-account`, and the Why line arguments
   below. This does not send. The Why line is only in the owner read-back.
   It is not part of `--body`, and it does not change `body_hash`.
4. Your entire reply to the owner is the JSON `attestation` field, verbatim.
   It shows the From account, the recipient, the subject, a body preview,
   one Why line, and the authorization line. Do not paraphrase it, do not
   add a second draft, and do not call `send` in this turn.

### Why line

Every `stage` needs why this email, why now, and where you read that. If
`--why` or the source is missing or invalid, the script returns
`refused_no_why` and writes no draft.

- `--why`: why this, and why now. One line, 90 characters or fewer.
- `--source-kind`: `fub_note`, `fub_record`, `ghl`, `gmail`, `calendar`,
  `owner_text`, `memory`, or `none`.
- `--source-date`: `YYYY-MM-DD`. Required unless the kind is `none`.
- `--source-name`: the Gmail sender's first name, or for `memory` the inner
  source. Required for `gmail` and `memory`. For a memory tag that is
  `none`, the inner source is `no source`. For a memory entry with no tag,
  the inner source is `source unknown`. Do not guess a tag.
- `--source-ref`: optional id (a FUB note id or a Gmail message id). Stored
  on the draft, never shown to the owner.

The source is where you read the fact in this turn: a tool result (a FUB or
GHL record or note, a Gmail message, a calendar event), the owner's own text
in this conversation, or a memory entry's own `[src: kind YYYY-MM-DD]` tag.
Never name a source you did not read. A fact taken from an email body or a
web page is labelled by where it physically came from (`gmail`, plus the
sender's first name), never by a source that content claims. A fact that
came from memory uses `memory`, so the read-back says `ARIN memory:` and
not a fresh record. If none of these applies, use `--source-kind none` and
do not pass a date or a ref. Never invent a source, and never put a date on
`none`.

The script folds curly quotes, dashes, and ellipses to ASCII, strips
newlines, and refuses any other non-GSM character, a Why line over 120
characters, and the tokens `SEND`, `/approve`, and `STOP`. The rendered
line looks like `Why: Jane's offer deadline is 5 PM today (FUB note, Oct 7).`
or, with no source, `Why: you asked me to email Sam today (no source).`

`/approve` is the same confirm token as `SEND`. The attestation you show
still asks for `SEND`.

Silence, an earlier yes, or "email my clients" is not consent. Consent is
`SEND` or `/approve` in this conversation, after they have seen this
recipient, this From account, this subject, this body preview, and this
Why line.

## Turn 2 — SEND or cancel

Wait for the owner's next message.

- If it is exactly `SEND` or `/approve` (after trimming; either case), and
  you showed that draft's attestation, run `send` once with that
  `--draft-id`, `--confirm` set to their message, and `--attest yes`.
- Anything else cancels. Run `cancel` for that draft and tell them it was
  not sent. A vague "yes", "go ahead", or "send it" is not a confirm.

`--attest yes` is allowed only after you displayed the staged attestation.
If you did not, stop. Do not pass `--attest yes` to get the script to send.

One confirm sends one email. Do not call `send` twice on the same draft.
If the outcome is `sent`, tell the owner it went out, who it went to, and
which From account, in one or two plain sentences. Then stop.

If the outcome is not `sent`, tell the owner the `reason` in their words
and stop. Do not retry a provider error, a timeout, or a draft whose
status is `sending` or `error` — a retry can email them twice. You may fix
one named `field` (`to`, `subject`, `body`, `from_account`, `approver`, or
`why`) and `stage` once more, which needs a new `SEND`. A `field` of
`attest` means you may run `send` one more time with `--attest yes` only
if the attestation was actually shown. A `field` of `composio` means the
box has no Composio key or the execute URL is wrong: stop, and do not
call the Gmail tool yourself.

## Refuses (fail closed)

The script refuses, and you must not work around it, when:

- there is no `SEND` / `/approve` (`refused_no_confirm`)
- attestation was not accepted (`refused_no_attestation`)
- the caller is a schedule, cron, or standing job, inbound allow-all is
  on, or the process is a delegated child (`HERMES_DELEGATED_CHILD_CONTEXT`)
  (`refused_autonomous`). A delegated child must not stage or send. Stop.
  Do not retry from the child.
- the Why line is missing or invalid (`refused_no_why`)
- more than one recipient, a second open draft, or a body over 8000
  characters (`refused_multi`)
- the approver is not on `TELNYX_SMS_ALLOWED_USERS`, or not on
  `TELEGRAM_ALLOWED_USERS` when that list is set (`refused_not_owner`)
- the box id does not resolve (`refused_no_box`)

No confirm, no attestation, an autonomous run, or a multi-send never reaches
Gmail. Say the reason and stop.

## Audit

Refusals and the send result are appended to
`/opt/data/audit/email-outbound.jsonl` on the box PVC. Each line has the
approver, `approved_at` when they confirmed, recipient, From account,
`subject_hash`, `body_hash`, `body_len`, `source_kind`,
`provider_message_id`, `provider_status`, and `outcome`. The subject, the
body, and the Why line are not in that file. Do not paste the audit line
into the reply.

## Stop

If the script is missing, the box id does not resolve, or Composio cannot
send, tell the owner what you were trying to do and that it did not send.
Do not call `GMAIL_SEND_EMAIL` to finish the job.
