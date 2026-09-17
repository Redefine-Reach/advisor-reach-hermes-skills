---
name: schedule-text
description: "Reminders and scheduled texts: later, daily, weekly. Use whenever the user wants something texted to them at a later time or on a schedule — 'remind me in 20 minutes', 'remind me at 4', 'text me tomorrow morning', 'every Monday send me…', 'every weekday at 7:30…' — and whenever they want to change, pause, or stop one ('make it 8 instead', 'stop the reminders'). Read this BEFORE calling the cron tool: this box's clock is UTC and a job created without these steps fires at the wrong hour or texts nobody. A morning brief or daily update is a scheduled text whose CONTENT is defined by the daily-brief skill — use both."
---

# Schedule a text — reminders and recurring texts that actually arrive, at the right hour

You schedule with the `cronjob_manage` tool. Two facts about this box decide everything below:

1. **The box's clock is UTC.** `date +%Z` here prints `UTC`, and the scheduler interprets every
   schedule — "weekdays at 9am", cron syntax — in UTC. A user in Chicago who asks for 7:30 and gets a
   job at `30 7 * * 1-5` will be texted at 2:30 in the morning. You convert to UTC yourself.
2. **A job only reaches the user if its Delivery Target is this conversation.** When you create a
   job from a text conversation and leave `deliver` out, the tool records this conversation as the
   job's origin and the job texts the user. A job whose `deliver` is `local` runs on schedule and
   texts nobody — it just writes a file. That is the failure this skill exists to stop.

## A. Before you create anything: know the user's timezone (clock times only)

- One-shots phrased as a delay ("in 20 minutes", "in 2 hours") need NO timezone and NO conversion:
  pass the tool's own form (`in 20m`, `in 2h`). Never hand-compute an absolute timestamp.
- For a clock time ("at 4", "every weekday at 7:30", "tomorrow at 9"): if you already know the
  user's timezone (they told you, a previous job's prompt has `User timezone:`, or memory has it),
  use it. Otherwise ask ONE short question and wait: "Happy to — which time zone are you in?" A
  city, state or zone word is enough ("Chicago", "Minnesota", "Central", "Eastern", "Arizona"). Map
  it to an IANA zone with `references/timezones.md`. Do not guess from nothing; do not ask twice.

## B. Write the schedule as a UTC cron expression

Use the conversion rule and table in `references/timezones.md`:

`UTC hour = local hour + (the zone's current offset, as a positive number)`; if that is 24 or
more, subtract 24 and move the day list one day later (`1-5` → `2-6`, `1` → `2`, `0` → `1`).

Worked example — "every weekday at 7:30", Chicago, on a date inside daylight time (CDT, +5):
`30 12 * * 1-5`. The same request in standard time (CST, +6) is `30 13 * * 1-5`.
Use a cron expression (`m h * * dow`) for anything recurring at a clock time. Use the tool's
natural forms only for intervals ("every 2h") and delays (`in 20m`). A single clock time today or
tomorrow ("at 4 today") is a one-shot: work out the minutes from now (in the user's zone) and use
`in Nm` — the tool's ISO one-shot form carries no timezone and would be read as UTC.

DST: the offset changes on the second Sunday of March and the first Sunday of November. A job
written in one period drifts by an hour in the other. If the user says a text is arriving an hour
early or late, re-convert with today's offset and `update` the job's `schedule`.

## C. Create the job

Call `cronjob_manage` with:

- `action`: `create`
- `name`: a plain name, e.g. `Reminder: call the title company` or `Morning brief (weekdays 7:30 AM Central)`
- `schedule`: the UTC cron expression from B, or `in 20m` for a delay one-shot
- `failure_deliver`: `local` — a config error must never text the user a raw stack trace
- `skills`: the skill(s) the fire-time run must load — `["schedule-text"]` for a plain reminder,
  `["schedule-text", "daily-brief"]` for a brief (the daily-brief skill says what the prompt must
  contain; read it before creating a brief)
- `prompt`: self-contained — the run has NO chat context. For a reminder:
  `User timezone: <IANA zone>. Text the user exactly: "Reminder: call the title company about 8115 Arrowwood."`
  For a brief: the template in the daily-brief skill.
- Do NOT include `deliver` in a text conversation.

## D. Verify, then confirm in the user's words

1. Call `cronjob_manage` with `action: list`. Find the job you just created. Its `deliver` must be
   `origin` or start with `telnyx_sms:`. If it says `local`, the job cannot text anyone: tell the
   user "I need the number to text this to — is it this one?" and, with their number, call
   `update` with `deliver: telnyx_sms:+1XXXXXXXXXX`. Never leave a job at `local`.
2. Confirm in local time, never in UTC and never quoting the cron expression or a job id:
   "Reminder set for 4:00 PM Central." / "Morning brief set: weekdays at 7:30 AM Central. Reply
   'send one now' to see it."

## E. When a scheduled text fires (this skill is loaded by the job)

You are in a fresh session with no chat context; the prompt is the whole instruction. Your FINAL
RESPONSE is what gets texted. Keep it short and plain — under 300 characters for a reminder, no
markdown (`**`, `#`, `-` bullets), no greeting, no sign-off. A brief follows the daily-brief skill
instead (its page + link format).

## F. Changing, pausing, stopping, "send it now"

Always `list` first, match by name, then `update` (new `schedule` — re-converted to UTC — or new
`prompt`), `pause`, `resume`, or `remove`. "Send me one now" = `action: run` on the existing job.
Confirm in local time. "Stop the reminders" = `remove` those jobs, nothing else.

## Hard rules

- Never create a job that is left with `deliver: local` (verify with `list`, section D).
- Never write a clock-time schedule without converting from the user's timezone to UTC.
- Never hand-compute an absolute timestamp for "in N minutes" — use `in Nm`.
- Never quote UTC, a cron expression, or a job id to the user.
- A brief is a scheduled text whose content the `daily-brief` skill defines — load both.
