---
name: proactive-owner
description: "Quiet pauses ARIN-started texts to the owner. Default off. Daily cap, who needs you today, and one afternoon nudge. Never texts a client."
---

# Proactive owner texts

ARIN-started texts are the morning brief, the afternoon follow-up nudge, and a receipt. They go to the owner only. This skill never texts a client, never stages a client text, and never calls `sms-send-confirmed`. A draft in the brief is not a send. Staging still needs the owner's `SEND` on a later turn, and that gate refuses cron.

The feature is off until the box file `/opt/data/proactivity/config.json` contains `"enabled": true`. No environment variable turns it on. Do not create that file. Do not set `enabled` to true. If the owner asks to turn proactive texts on, say they stay off until that file is set on the box.

The zone is the top-level `timezone` key in `/opt/data/config.yaml`. Do not read or set a timezone environment variable, and do not treat UTC as the owner's day. Quiet hours in the config file are evaluated in that zone. The usual window is 21:00–08:00 local when the file does not override it.

On a box the script is:

`python3 /opt/data/skills/proactive-owner/scripts/proactive.py`

`$HERMES_HOME` is scrubbed in the sandbox; `/opt/data` is its value. Pass `--now` only in tests.

## Quiet and resume

When the owner sends a short message, run `owner --text` with that message before treating it as anything else.

- Pause phrases: `quiet`, `pause nudges`, `pause proactive`, `pause proactive texts`, `stop nudges`.
- Resume phrases: `resume`, `unquiet`, `nudges on`, `resume nudges`, `resume proactive`.

Punctuation and case do not matter. A longer sentence is not a command. If the result is `not_a_command`, continue the normal conversation and do not claim they paused. If a scheduled job runs this command, the script returns `refused_autonomous` and changes nothing.

If `action` is `pause` and `enabled` is false, tell them proactive texts are already off, and that quiet is saved for when the file turns them on. If `enabled` is true, tell them proactive texts are paused until they resume. One or two plain sentences. Do not text anyone else.

Quiet pauses texts ARIN starts. It does not suppress a reply to the owner in this thread. An owner who asks for the brief now still gets that brief. Do not record that on-demand brief against the daily cap.

## Gate

A scheduled proactive text must pass `gate --kind brief|nudge|receipt --pre-script` before the model runs. `wakeAgent: false` means Hermes skips the run. Reasons that block a send: `disabled`, `quiet`, `quiet_hours`, `daily_cap`, a missing or refused timezone, or an unreadable config or counter. The same check is inside `nudge` and `record`.

`record --kind <kind> --token <id>` counts one owner text on the local date. Use a token of `brief:<local_date>`, `nudge:<local_date>`, or `receipt:<local_date>` from the gate's `local_date`. The same token does not count twice. Do not record when the final response is `[SILENT]`. Do not record an on-demand reply.

## Who needs you today

On a start-of-day brief, build a candidates file from bounded evidence, then run `who --input <file>`. If `enabled` is false, or `section` is null, omit the section. Do not mention that proactivity is off.

Write only these fields, with offsets on every timestamp:

- `contacts`: `name`, `source` (`fub` or `ghl` only), optional `last_touch`, optional `stage_due` (`YYYY-MM-DD`)
- `emails`: `name`, `received_at`, `unanswered`, `known_client`
- `events`: `who`, `start`

Use native FUB or GHL for contacts, not Composio CRM. Use the smallest Composio read for unanswered known-client mail and today's calendar. Do not copy message bodies, subjects, or phone numbers into the file. Do not dump a book of business. A missing last touch is unknown; do not invent one. Silence is not a last touch.

When `items` is non-empty, put that section ahead of routine recap. Use the `sms` line as the owner-facing clause and keep the whole SMS inside the daily-brief limit. Include `stage_hint` once. "Reply 1 to stage" is an offer for a later owner turn. This run does not stage and does not text them. Drafts are drafts.

A scheduled brief that will actually be delivered calls `record --kind brief` after the gate allows it. If that record is refused, the final response is exactly `[SILENT]`.

## Afternoon nudge

A scheduled afternoon run loads this skill and runs `nudge --input <file>`. The final response is the `text` field and nothing else. When that text is `[SILENT]`, Hermes delivers nothing: nothing qualified, the feature is off, quiet is set, quiet hours apply, or the daily cap is spent. Do not add a sentence around `[SILENT]`. Do not name a client when the text is silent.

The nudge is one owner text about unanswered known-client email. It does not text the client. It does not call `sms-send-confirmed`. A second run the same local day stays `[SILENT]`.

Do not create the afternoon job from an ordinary brief. An explicit request to schedule it loads `schedule-text`. The job shape is [afternoon-job](references/afternoon-job.md). This skill does not install that job.

## Failure handling

If the zone, config, or candidates file is unreadable, omit the section or return `[SILENT]`. Do not guess the local date, do not manufacture a client, and do not send.
