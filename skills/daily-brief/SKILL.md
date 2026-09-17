---
name: daily-brief
description: "Morning brief, daily update: a scheduled text + page. Use when the user asks for a morning brief, a daily or weekly update/summary/rundown, 'what's on today' every day, or to change what their brief contains. Scheduling itself (timezone, UTC conversion, delivery check, edits, pause/stop) is the schedule-text skill — this skill defines what a Brief Job's prompt says and, when the job fires, how the brief is gathered and delivered: a branded mobile HTML page via present-file plus a plain text under 550 characters ending with the link. Loaded by every Brief Job when it fires."
---

# Daily brief — a short text plus a page, built honestly from what is connected

A brief is a scheduled text. **Creating, changing, pausing or stopping the schedule is the
`schedule-text` skill's job** — open it and follow its sections A–D (timezone, UTC cron, create,
verify the Delivery Target). This skill tells you what the job's prompt must say (section 1) and
what to do when the job fires (section 2). The same division as `present-file`: the `video` and
`gbp-scorecard` skills make the file; `present-file` delivers it.

## 1. Creating a Brief Job (with `schedule-text`)

When `schedule-text` section C asks for the `prompt` and `skills`:

- `skills`: `["schedule-text", "daily-brief"]`
- `prompt`: the template below, filled in (`<…>` parts); keep everything else word for word:

```
User timezone: <IANA zone>. Local send time: <h:mm AM/PM> <every weekday|every day|every Monday…>.
You are sending <the user's first name, or "the user">'s <morning|daily|weekly> brief. Load and follow the daily-brief skill's section "2. When the job fires" exactly.
Include, in this order and only what is actually connected: today's calendar (conflicts first), replies owed, pipeline deadlines, one market line. If nothing is connected, say so plainly and how to connect (reply CONNECT). Never invent an item.
DELIVERY FORMAT (mandatory): write the full brief as a mobile-friendly HTML page named Morning-Brief-<YYYY-MM-DD>.html built from the daily-brief skill's references/brief-page.html and publish it with the present-file skill; then your FINAL RESPONSE is under 550 characters of plain text — the top 2–3 items with next actions, then the line "Full brief: <link>". Nothing else. No markdown, no bullets, no headings.
```

Then finish `schedule-text` section D (verify with `list`; confirm in local time: "Morning brief
set: weekdays at 7:30 AM Central. Reply 'send one now' to see it.").

"Send me one now" = `cronjob_manage` `action: run` on the existing Brief Job (list first). Do not
write a second brief by hand in the conversation.

## 2. When the job fires (a Brief Job loads this skill; this section is for that run)

You are in a fresh session with no chat context. The prompt tells you the timezone and what to
include. Do this, in order:

1. Gather only from what is connected on this box — calendar and email through the apps the
   user connected (`connect-app`), the Circle community through `circle-member-token`, memory
   if enabled — following `references/gathering.md` (priority order, per-source rules, honest
   failure wording). A source that is not connected gets one honest line ("Calendar: not
   connected"). Do not invent an appointment, a lead, a deadline, or a number.
2. Build the page: copy `references/brief-page.html`, replace the `{{…}}` fields, keep the
   inline CSS, add no `<script>`, no external fonts, no images. Name it
   `Morning-Brief-<YYYY-MM-DD>.html` (the local date from the prompt's timezone).
3. Publish it with the `present-file` skill (copy into `ARTIFACT_DIR`, link is
   `ARTIFACT_BASE_URL/<name>`).
4. Your FINAL RESPONSE — the text that is sent by SMS — is under 550 characters of plain text:
   the top 2–3 items each with a next action, then the last line `Full brief: <link>`. No markdown
   (`**`, `#`, `-` bullets), no greeting, no sign-off. Nothing connected? Then:
   `Morning brief: nothing is connected yet, so there is nothing to report. Reply CONNECT and I will link your calendar and email. Full brief: <link>`

## 3. Changing what the brief contains

"Add the weather", "drop the market line": `schedule-text` section F — `list`, then `update` the
job's `prompt` (keep the `User timezone:` first line and the DELIVERY FORMAT paragraph intact).
Time/day changes are `schedule-text` too.

## Hard rules

- Never text more than 550 characters from a Brief Job; the page carries the rest.
- Never invent brief content; unconnected sources are reported as unconnected.
- Never create or edit the schedule here — that is `schedule-text` (it verifies delivery is not `local`).
- The prompt's first line is always `User timezone: <IANA zone>.` and the DELIVERY FORMAT paragraph is never dropped.
