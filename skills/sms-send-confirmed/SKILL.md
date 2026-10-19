---
name: sms-send-confirmed
description: "Text one third party an SMS from this box's Telnyx number. Use when the user asks to text, SMS, or message someone else. Draft, show destination and From, and send only after they reply SEND. Never send without that confirm."
required_environment_variables:
  - TELNYX_SMS_FROM_NUMBER
  - TELNYX_SMS_ALLOWED_USERS
  - TELNYX_SMS_API_BASE
optional_environment_variables:
  - TELEGRAM_ALLOWED_USERS
  - ARIN_OWNER_IDENTITIES
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
Do not change Helm, the box's settings, or the Telnyx portal. A session file is
not an allowlist entry. Mode B (a list, a nurture sequence, a book of
business, or a MoO blast) stays refused.


## On a text (telnyx_sms) turn: use the sms_stage tool

`execute_code` and the terminal are blocked on texted turns. Do not try them,
and do not answer with a plain-text draft. Call the `sms_stage` tool instead.
It runs this skill's script with the same gates.

- Before every stage, run `learning_loop` op `next` with the draft `kind` (for
  example `sms-third-party` or the kind your box uses for these drafts).
- Stage: `sms_stage(action="stage", approver=<owner E.164>, dest=<E.164>,
  body=<text>, why=<one line>, source_kind=<kind>, source_date=<YYYY-MM-DD>,
  source_name=<only if required>, replaces=<draft_id only when re-staging after
  an edit>)`. Follow the Why line rules below. When the owner dictated the text,
  use `source_kind="owner_text"` and today's date.
- Show the tool's read-back verbatim and stop. Do not send in this turn.
- When the owner's next text is exactly `SEND` or `/approve`, call
  `sms_stage(action="send", draft_id=<id>)`. The destination and body come from the
  staged draft. The box plugin supplies the turn sender; do not pass `actor` in the
  tool call.
- If they cancel, call `sms_stage(action="cancel", draft_id=<id>)`.
- If the tool returns an error, say nothing was sent. Do not retry another way.

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

`ARIN_OWNER_IDENTITIES` (optional) links one owner's channels: comma-separated
groups of `|`-joined ids, for example `+17145550100|tg:424242`. Phones are
normalized to E.164. On `cancel`, `--actor` must match the draft approver or
share a group with them. **SEND and re-stage (RED-700):** only on the owner's
SMS text thread — the box sets `SMS_TURN_OWNER_E164` and the plugin passes that
identity; do not call `send` or `stage --replaces` from the app, Telegram, or
`execute_code` with a model-chosen `--actor`. Identity never comes from the
message body.

## Turn 1 — stage, then stop

1. One named person. If they ask for more than one number, a batch, a CSV,
   a book of business, a nurture sequence, or a MoO list, refuse in your
   reply and stop. Say that lists are not sent this way. Do not pick one
   row and stage that. Do not call `stage`.
2. One plain-text body, 640 characters or fewer (the box sends one segment
   at that cap; a longer body would become more than one Telnyx send).
   No Markdown. If you need it shorter, ask before staging.
3. Run `stage` with `--approver`, `--dest`, `--body`, and the Why line
   arguments in the next section. This does not send. The Why line is only
   in the owner read-back. It is not part of `--body`, and it does not
   change `body_hash`.
4. Your entire reply to the owner is the JSON `attestation` field, verbatim.
   It shows From (the box DID), the destination, the body, one Why line, and
   the authorization line. Do not paraphrase it, do not add a second draft,
   and do not call `send` in this turn.

### Why line

Every `stage` needs why this text, why now, and where you read that. If
`--why` or the source is missing or invalid, the script returns
`refused_no_why` and writes no draft.

- `--why`: why this, and why now. One line, 90 characters or fewer.
  Give a cause (what is due or happened, and why now), never the trigger.
  "You asked me to text Dana", "as requested", or any wording that only
  cites the owner's text and date is refused (`refused_why_trigger`). For
  `owner_text` the read-back names the source plainly:
  `Why: Dana asked if the inspection report is in, from your own text.`
  If the model already wrote that phrase, including a leading `From your own text,`
  or `(from your own text)` anywhere in the line, the script removes the copy
  so the owner sees it once. When the label led the line, the remaining sentence
  starts with a capital (`From your own text, it's Sam's birthday today` renders
  `Why: It's Sam's birthday today, from your own text.`).
  `source_date` and `source_ref` on the draft are JSON null, not a date.
  Other kinds keep `(<source>, <Mon D>)` and require `--source-date`.
- `--source-kind`: `fub_note`, `fub_record`, `ghl`, `gmail`, `calendar`,
  `owner_text`, `memory`, or `none`.
- Why quality (script-enforced before any draft is written): give a client-specific
  reason from the owner's message or known context (a deadline, the last contact, what
  the client asked, or the event itself: "Pat is closing today"). Never invent one.
  `refused_why_generic`: the reason is too thin ("Pat") or only restates the request.
  `refused_why_circular`: the reason is the action or the draft ("Congratulate Pat");
  an action tail ("so congratulate Pat", "and deserves congratulations", "so a reminder
  is timely") is trimmed off, so do not write one. A real cause that uses "so" or
  "meaning" in the middle stays whole ("so the wire must go out this morning",
  "meaning Dana needs a counter before 5"). A Why that only says the thing is
  "available now" is a status, not a cause (`refused_why_circular`): name what the client
  asked or what happened ("Dana asked if the inspection report is in"). A cause plus a
  status still stages. A source or date the model appends
  itself, such as "(owner text, 2026-10-15)", is stripped and never shown.
- Wording: keep the owner's own words and facts. Only the recipient becomes "you"
  or "your" (the owner's "tell Dana to bring her signature" becomes "please bring
  your signature" in a text TO Dana); keep every other person's pronouns and names
  exactly as the owner gave them ("her" for a third person stays "her"). Do not add,
  drop, or reword facts, dates, amounts, or names. The script never edits the body.
- Body quality: the draft is the text itself, to the recipient, in second person
  (greet them by name: "Hi Dana, yes, the report is in." or "Hi, Dana, ..."; never a bare
  "Hi,", "Hello,", "Hey!", "Hi there,", or "Good morning,"; use "you"
  and "your"; answer the client's question, do not repeat "you asked ..." back to them).
  **Who first.** When the owner asks to text, follow up, or check in and you do not
  have one identifiable recipient, ask exactly one recipient question and do not call
  `stage`. Generic: `Who should I text?` When a role is clear (buyer, seller, client):
  `Which buyer should I text?` Do not ask about price or other content in that turn.
  If conversation or memory already names exactly one matching person (for example
  one buyer in context), use that real name and stage normally. If it is unknown or
  ambiguous, ask only about the recipient.
  `refused_no_recipient`: the draft has no named recipient — a bare greeting ("Hi,",
  "Hello,", "Hey!", "Hi there,", "Good morning,"), or a bracketed name or role in the
  greeting (`[NAME]`, `[BUYER NAME]`, `[BUYER]`, and similar). Do not stage; ask who
  (or which buyer) as above.
  When the owner names a recipient and gives anything to say, stage. Any missing
  **content** detail (price, date, time, address, amount — not the recipient's name)
  is NEVER a reason to ask instead of staging: put a bracketed UPPERCASE placeholder in the body
  ("Hi Dana, the new price for 12 Oak St is [PRICE]."; also [DATE], [TIME], [ADDRESS]).
  Never add facts the owner did not give. The read-back order is: body, Why line,
  `Missing: ...` (when placeholders remain), then the usual authorization lines and
  `The recipient can still opt out with their carrier.` last. The Missing line says
  `Reply with it to restage, or DROP to discard.` (use `both` / `them` when several
  details are missing). It never invites SEND while placeholders remain. Ask for missing content
  in the same reply as the read-back. When the owner supplies a value, stage the message AGAIN with the value filled in and show the new read-back; never edit around the old draft.   NEVER send a bracketed placeholder: `refused_unfilled_placeholder` at
  `send` writes one `refused` outcome (`unfilled_placeholder`); re-stage with
  `--replaces` after the owner supplies the value.
  `refused_why_action_tail`: the Why line has a trailing consequence or states what
  the recipient needs, should do, or should know (joined by `, so`, `, and`, `so`,
  `and`, or `which means`, then a person such as she/he/they/the buyer/Dana and
  needs/should/must/has to/wants to/know). Examples: `so the buyer should know`,
  `so she needs the new date`, `and she needs the good news`. Rewrite to state the
  reason or fact only (for example `Dana's closing date moved to Nov 3.`).
  `refused_why_reused`: the Why line is identical to the owner's previous draft but
  the recipient or the message body changed. Write a fresh why for each new text and
  person; never copy the last draft's Why into a different action.
  `refused_body_meta`: instructions like "Tell them ..." in the text.
  `refused_body_not_to_recipient`: not addressed to the recipient.
  `refused_unfilled_placeholder` (at send): the body still has a bracketed placeholder; restage with the value.
  `refused_body_missing_placeholder`: price mentioned with no figure. A street number is not a figure; use [PRICE] or the amount.
  `refused_body_no_content`: filler ("just sending a note"); ask ONE short question
  (what should the note say?).
- `--source-date`: `YYYY-MM-DD`. Required unless the kind is `none` or
  `owner_text` (do not pass a date for `owner_text`).
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
or, with no source, `Why: Sam's offer is due today (no source).`

`/approve` is the same confirm token as `SEND`. The attestation you show
still asks for `SEND`.

Silence, an earlier yes, or "text my clients" is not consent. Consent is
`SEND` or `/approve` in this conversation, after they have seen this
destination, this From number, this body, and this Why line. That is the same rule as
email outreach: the irreversible step needs its own go-ahead.

## Turn 2 — SEND, edit, or DROP

Wait for the owner's next message. The attestation already tells them:
Reply SEND to send, DROP to discard.

Before you act, call `learning_loop` op `next` with this draft's `kind` so
style notes apply. Do not announce that you recorded anything.

- If it is exactly `SEND` or `/approve` (after trimming; either case) **on an
  SMS text turn**, and you showed that draft's attestation, call
  `sms_stage(action="send", draft_id=<id>)` once. The box supplies the SMS
  owner identity; do not pass `--actor` in the tool call and do not invoke
  `send` from the app or `execute_code` until RED-700. When the outcome is
  `sent`, call `learning_loop` op `record` with `action="send"` and the same
  `kind`. Do not pass a note or the body.
- If the owner replies with an **edit** (a shorter wording, tone change, or
  other revision — not DROP/NO/skip and not SEND), do **not** cancel. Call
  `learning_loop` op `record` with `action="edit"` and a `note` that states
  the change in plain words ("shorter, no exclamation"), never the draft body.
  Then re-stage on the **same SMS text thread** with `replaces` set to that
  `draft_id`, the updated body, and a **new** Why line (the guard refuses a
  reused Why whenever the body changes). Use `sms_stage` on texts; do not
  re-stage from the app or `execute_code` until RED-700. Show the new
  attestation and wait again for SEND or DROP.
- After a fixable script refusal (`unfilled_placeholder`, `opted_out`, or
  `over_length`), re-stage with `--replaces` on the SMS text thread only. A
  refused draft can be the source of only one re-stage.
- If it is `DROP`, `NO`, or `skip` (after trimming; either case), run
  `cancel` with `--draft-id` and `--actor`, then `learning_loop` op
  `record` with `action="skip"` and the same `kind` (no note). Tell them it
  was not sent with **Not sent.** first. `NO` remains an alias for owners who
  already use it.
- Any other reply that is not SEND and not an edit does not send. Run
  `cancel` for that draft, then `record` with `action="skip"` when the owner
  clearly dropped the approach, and tell them it was not sent. A vague "yes",
  "go ahead", or "send it" is not a confirm.

Do not ask the owner to answer with a carrier opt-out keyword. `DROP`, `NO`,
and `skip` drop a staged draft.

The read-back footer is unchanged: Why line, then SEND/DROP, then the carrier
opt-out line last. Never remove the SEND demand because of a learned note.

`--attest yes` is allowed only after you displayed the staged attestation.
If you did not, stop. Do not pass `--attest yes` to get the script to send.

One confirm sends one message. Do not call `send` twice on the same draft.
If the outcome is `sent`, tell the owner it went out, who it went to, and
which From number, in one or two plain sentences. Then stop. Do not send
a follow-up text to that person.

If the outcome is not `sent`, tell the owner the `reason` in their words
and stop. Do not retry a provider error, a timeout, or a draft whose
status is `sending` or `refused` with `refuse_reason` `provider_error` or
`provider_no_id` — a retry can text them twice. Staging the same body to the
same recipient again within 24 hours after an ambiguous provider failure
returns `refused_recent_provider_failure` with: "Your last text to this person may still go through, so I didn't queue a duplicate" (no outcome line). Definitive provider `rejected` or local `not_sent` failures do not arm the guard. You may fix
one named `field` (`dest`, `body`, `approver`, or `why`) and `stage` once more,
which needs a new `SEND`. A `field` of `from` means the box number is
missing: stop, and do not invent one. A `field` of `attest` means you may
run `send` one more time with `--attest yes` only if the attestation was
actually shown.

### Script examples (cancel only off the SMS text thread)

Until RED-700, do **not** run `send` or `stage --replaces` from `execute_code`,
the app, or Telegram. SEND and re-stage happen only on the owner's SMS text
turn via `sms_stage`, with `SMS_TURN_OWNER_E164` set by the box.

App or Telegram may still **cancel** when `ARIN_OWNER_IDENTITIES` links the
channel to the approver:

```bash
python3 /opt/data/skills/sms-send-confirmed/scripts/sms_send_confirmed.py cancel --draft-id DRAFT_ID --actor +17145550100
```

## Refuses (fail closed)

The script refuses, and you must not work around it, when:

- there is no `SEND` / `/approve` (`refused_no_confirm`)
- attestation was not accepted (`refused_no_attestation`)
- the destination is on the local opt-out list (`refused_stop`)
- the caller is a schedule, cron, or standing job, inbound allow-all is
  on, or the process is a delegated child (`HERMES_DELEGATED_CHILD_CONTEXT`)
  (`refused_autonomous`). A delegated child must not stage or send. Stop.
  Do not retry from the child.
- the Why line is missing or invalid (`refused_no_why`)
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

An inbound from that destination whose whole body is a single carrier
opt-out keyword is recorded on the same list. Do not send. Telnyx's
default opt-out keywords are STOP, STOPALL, STOP ALL, UNSUBSCRIBE,
CANCEL, END, and QUIT. REVOKE and OPTOUT are extra guards and are
treated the same way. Never ask the owner to send one of those words.
START and UNSTOP opt back in.
HELP is the help word. Never ask the owner to send HELP either.
`/stop` is the Hermes pause, and it is not how a third party is opted out
here. The recipient can still opt out with their carrier. Telnyx enforces
that later; this file is the check you run first.

## If the owner opts out

If the owner texts a plain-words opt-out, any reasonable request to stop
the texts, including "please stop texting me", do not argue.
Send exactly one confirmation text, and send nothing after that.
START and UNSTOP opt back in.

Unsubscribing the owner number, blocking later texts, and honoring START
and UNSTOP are carrier and Hermes gateway behavior. HELP is also answered
by Telnyx, not by asking the owner to send it. This repository cannot do
that part. If the text still reaches you, send that one confirmation
text and then stop.

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
