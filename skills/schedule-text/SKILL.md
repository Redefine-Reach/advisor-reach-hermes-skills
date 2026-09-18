---
name: schedule-text
description: "Schedule texts: create, update, run, pause, or remove an explicit reminder or Brief Job. Use when the user asks to manage a scheduled text; ordinary brief composition and delivery belongs to daily-brief."
---

# Schedule Text

Use `cronjob_manage` only for an explicit create, update, run, pause, or remove request. An ordinary brief, draft, or current update does not create a job. Existing customized workflows and authorized output preferences remain authoritative.

## Schedule safely

1. List before create, update, run, pause, resume, or remove. Match an existing requested job by its persisted details and update it instead of creating a duplicate. For a delay, preserve the scheduler form (`in 20m`, `in 2h`) without timezone conversion.
2. For a local clock time, use a timezone from trusted preferences or known context; otherwise ask once. Inspect the actual configured scheduler timezone and the tool's exposed schema/status. Use a verified IANA local walltime only when that configuration supports it. Do not assume UTC, calculate a fixed offset, or claim recurring DST safety from an unverified configuration.
3. If the configured scheduler timezone differs from the requested IANA zone, do not change it globally. Assess affected jobs and obtain coherent migration authority before changing schedules or configuration.
4. On create or update, set `failure_deliver: local`. In a verified gateway context, omit `deliver` only when the persisted result confirms the intended origin recipient; otherwise use an explicit verified authorized SMS target. Never leave a user SMS job with `deliver: local`. Keep the run prompt self-contained and short. A plain reminder loads `schedule-text`; a Brief Job loads `daily-brief` plus `day-open-rollcall` or `day-close-debrief`, never `schedule-text`.
5. Verify the persisted job with `list`: platform and recipient must be a real authorized delivery target, and the next run and selected days must match the requested local schedule. A generic flag or `deliver: origin` alone is not proof of delivery, and a CLI session without an origin cannot claim SMS success.

## Brief jobs and direct requests

`daily-brief` coordinates brief content and authorized delivery. For `send one now`, run an existing matching authorized Brief Job after listing it. If none exists, compose the current requested brief; do not create or assume a job. A fire-time Brief Job returns only its final response and makes no extra send or scheduler-tool request.

## Reminder fire-time response

A reminder run returns only the requested reminder as plain text under 300 characters. Do not make an extra send or job-management request while firing.

## Changes and removal

Use `update`, `pause`, resume, or remove only for the identified existing job after listing it. Preserve other jobs and report the verified local next run and days. Never expose a raw failure by SMS; `failure_deliver: local` is intentional.