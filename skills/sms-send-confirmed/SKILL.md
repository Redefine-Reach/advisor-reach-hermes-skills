---
name: sms-send-confirmed
description: "Text one third party an SMS from this box's Telnyx number. Use when the user asks to text, SMS, or message someone else. Draft, show destination and From, and send only after they reply SEND. Never send without that confirm."
required_environment_variables:
  - TELNYX_SMS_FROM_NUMBER
  - TELNYX_SMS_ALLOWED_USERS
  - TELNYX_SMS_API_BASE
optional_environment_variables:
  - TELEGRAM_ALLOWED_USERS
---

# SMS send confirmed

This is the only path that may text a third party. It is one message, from
this box's Telnyx number, after the owner confirms. It reuses the box's
existing Telnyx adapter (`team-telnyx/telnyx-hermes-sms` @ `a7d209f`).
The script hydrates `TELNYX_*` (including `TELNYX_SMS_API_BASE` for the
telnyx-proxy), resolves the `telnyx_sms` plugin, and calls that plugin's
`standalone_sender_fn`. From is `TELNYX_SMS_FROM_NUMBER`.

`execute_code` strips `TELNYX_*` before the script starts. The script
refills the keys it needs from this skill's `runtime.env` (optional) and
from `/proc/1/environ`. It does not print those values.

You do not send any other way. Do not call `hermes send` yourself, do not
curl Telnyx, do not import the adapter, and do not pass a From number.
NEVER use Composio, `connect-app`, or a Telnyx toolkit to send or receive
a third-party SMS. Do not add the destination to `TELNYX_SMS_ALLOWED_USERS`.
Do not change Helm, customer YAML, or the Telnyx portal. A session file is
not an allowlist entry. Mode B (a list, a nurture sequence, a book of
business, or a MoO blast) stays refused.

## When this skill applies

Use it when the owner asks you to text, SMS, or message a named person who
is not this conversation.

Do not use it to answer the owner. A reply in this thread is the normal
owner↔ARIN SMS path and stays as it is. Do not use `schedule-text` as the
third-party path. That skill is owner-thread only, and so is `daily-brief`.
A scheduled job, a standing job, or a cron run must not stage or send a
third-party text.

Prepare-never-send stays the default everywhere else. This skill is the
explicit owner-gated exception, and only for one named recipient at a time.
No SOUL change is required: if this script is not the thing that sends,
the message has not been confirmed.

## Path A

Third-party send is Path A on every box whose id resolves and whose native
Telnyx From (`TELNYX_SMS_FROM_NUMBER`) is set. The script reads the pod
name, then `BOX_PUBLIC_BASE_URL`, then `SMS_BOX_ID`. Customer boxes are
included. The earlier spike that allowed only `advisor-reach-internal` is
retired; that lock was intentional and is not the fleet rule anymore.

If the script returns `refused_no_box`, or `error` with `field` `from`,
tell the owner this box cannot send and stop. Do not look for another
sender. Do not connect Telnyx through Composio.

## What you run

On a box the script is:

`python3 /opt/data/skills/sms-send-confirmed/scripts/sms_send_confirmed.py`

If that file is missing, say so and stop. Do not search for another SMS
tool. Invoke it from `execute_code` with an argument list (so the body is
one argument). Do not set `SMS_SEND_TRANSPORT` or `SMS_SEND_CONFIRMED_TEST`.

The approver is the E.164 of the person texting you on SMS, or their
Telegram user id when they confirm from Telegram. The E.164 must be on
`TELNYX_SMS_ALLOWED_USERS`. `TELEGRAM_ALLOWED_USERS` is optional. When it
is set, a Telegram id on that list may confirm. When it is unset, this
skill still runs and only an allowlisted SMS owner can confirm. Never
pass the destination as the approver.

## Turn 1 — stage, then stop

1. One named person. If they ask for more than one number, a batch, a CSV,
   a book of business, a nurture sequence, or a MoO list, refuse in your
   reply and stop. Say that lists are not sent this way. Do not pick one
   row and stage that. Do not call `stage`.
2. One plain-text body, 640 characters or fewer (the box sends one segment
   at that cap; a longer body would become more than one Telnyx send).
   No Markdown. If you need it shorter, ask before staging.
3. Run `stage` with `--approver`, `--dest`, and `--body`. This does not send.
4. Your entire reply to the owner is the JSON `attestation` field, verbatim.
   It shows From (the box DID), the destination, the body, and the
   authorization line. Do not paraphrase it, do not add a second draft, and
   do not call `send` in this turn.

`/approve` is the same confirm token as `SEND`. The attestation you show
still asks for `SEND`.

Silence, an earlier yes, or "text my clients" is not consent. Consent is
`SEND` or `/approve` in this conversation, after they have seen this
destination, this From number, and this body. That is the same rule as
email outreach: the irreversible step needs its own go-ahead.

## Turn 2 — SEND or cancel

Wait for the owner's next message.

- If it is exactly `SEND` or `/approve` (after trimming; either case), and
  you showed that draft's attestation, run `send` once with that
  `--draft-id`, `--confirm` set to their message, and `--attest yes`.
- Anything else cancels. Run `cancel` for that draft and tell them it was
  not sent. A vague "yes", "go ahead", or "send it" is not a confirm.

`--attest yes` is allowed only after you displayed the staged attestation.
If you did not, stop. Do not pass `--attest yes` to get the script to send.

One confirm sends one message. Do not call `send` twice on the same draft.
If the outcome is `sent`, tell the owner it went out, who it went to, and
which From number, in one or two plain sentences. Then stop. Do not send
a follow-up text to that person.

If the outcome is not `sent`, tell the owner the `reason` in their words
and stop. Do not retry a provider error, a timeout, or a draft whose
status is `sending` or `error` — a retry can text them twice. You may fix
one named `field` (`dest`, `body`, or `approver`) and `stage` once more,
which needs a new `SEND`. A `field` of `from` means the box number is
missing: stop, and do not invent one. A `field` of `attest` means you may
run `send` one more time with `--attest yes` only if the attestation was
actually shown.

## Refuses (fail closed)

The script refuses, and you must not work around it, when:

- there is no `SEND` / `/approve` (`refused_no_confirm`)
- attestation was not accepted (`refused_no_attestation`)
- the destination is on the local opt-out list (`refused_stop`)
- the caller is a schedule, cron, or standing job, or inbound allow-all is
  on (`refused_autonomous`)
- more than one destination, a second open draft, or a body over 640
  characters (`refused_multi`)
- the approver is not on `TELNYX_SMS_ALLOWED_USERS`, or not on `TELEGRAM_ALLOWED_USERS` when that list is set (`refused_not_owner`)
- the destination is the owner or the box number (`refused_not_third_party`)
- the box id does not resolve (`refused_no_box`) or `TELNYX_SMS_FROM_NUMBER` is unset (`field` `from`)

No confirm, no attestation, an autonomous run, or a multi-send never reaches
Telnyx. Say the reason and stop.

## Opt-out

Before every send the script reads `/opt/data/audit/sms-opt-out.txt`
(one E.164 per line). If the destination is listed, it does not call
Telnyx. Tell the owner that number is on the do-not-text list.

When the owner says not to text someone again, run `deny` with their
approver and that destination. That only updates the local file. It does
not send.

Never tell the owner to reply `Stop` or `STOP`. That is the carrier
keyword. `/stop` is the Hermes pause, and it is not how a third party is
opted out here. Carrier STOP is still enforced by Telnyx later; this file
is the check you run first.

## Audit

Refusals and the send result are appended to
`/opt/data/audit/sms-outbound.jsonl` on the box PVC. Each line has the
approver, `approved_at` when they confirmed, destination, From, `body_hash`,
`body_len`, `telnyx_message_id`, `provider_status`, and `outcome`. The body
itself is not in that file. Do not paste the audit line into the reply.
Do not read the file back unless the owner asks whether a specific send
was recorded — then summarize the outcome, the destination, and whether a
provider id was stored, not the raw JSON.

## Replies from the person you texted

A successful send writes `/opt/data/sms-sessions/{E.164}.json`. The window
is 7 days (`ttl_expires_at`). That file means an inbound SMS from that
number may be shown to the owner. It does not let them drive this box, and
it does not let you text them again.

When a reply is captured, load `sms-inbound-owner-event`. Tell the owner
who sent it (E.164), the snippet, and the prior outbound (`draft_id`,
`telnyx_message_id`, sent time). Offer call, a draft reply, or dismiss.
Do not answer the recipient. Do not say you will handle the thread. Do not
keep talking to them after that one inbound.

A draft reply is another pass through this skill: `stage`, show the
attestation, and send only after a new `SEND` or `/approve`. One confirm,
one message. `STOP` / the local opt-out file still refuses before Telnyx.

Hermes drops inbound SMS that are not on `TELNYX_SMS_ALLOWED_USERS` inside
the gateway, before any skill runs. This script cannot see those webhooks
on its own. The Method A hook in `method-a/BAKE.md` calls `inbound` and
then skips the agent turn. Do not call `inbound` yourself. Do not bake
that hook from this conversation, and do not set
`TELNYX_SMS_ALLOW_ALL_USERS` to fake it. A missing hook is not a reason
to use Composio.

## Stop

If the script is missing, the box id does not resolve, or the From number
is unset, tell the owner what you were trying to do and that it did not
send. Do not probe Telnyx, do not vary the destination to see what works,
and do not switch to another provider or to Composio.
