---
name: daily-brief
description: "Morning brief or daily update: coordinate the requested content and authorized delivery. Use for a current, on-demand, or scheduled brief; use schedule-text only when the user explicitly asks to create, change, run, pause, or remove a job."
---

# Daily Brief

Coordinate one useful current or scheduled brief. The customer's existing customized workflow and authorized output preference remain authoritative. Load the matching day skill for composition: `day-open-rollcall` for a start-of-day brief and `day-close-debrief` for a wrap-up. Reuse its source rules, preference handling, source limits, and evidence labels; this skill does not duplicate gathering or invent a market or community section.

## Compose and deliver

1. Determine whether the request is on-demand, an existing authorized scheduled brief, or an explicit job-management request. Only the last routes to `schedule-text`.
2. For `send one now`, list existing jobs and run the matching authorized Brief Job. Do not create or assume a job. If none exists, compose the currently requested brief without scheduling it.
3. Use the selected day skill's concise advisor-facing content. Its bounded Composio, exact calendar window, one member-scoped Circle read, native history/Mem0 separation, and document-coverage rules govern evidence. Keep the useful source-neutral checks in [gathering](references/gathering.md): priority, current local dates, pipeline parsing, and last-touch honesty.
4. Deliver the requested, authorized format. Default SMS is plain text below 550 characters with the priority and a useful next step. For an unresolved customer request, retain the concrete answer, relevant returned resource, or a short grounded reply draft that advances it. Drop lower-priority recaps before dropping that action; a list of unresolved statuses alone is not a useful brief. Preserve at most one optional `Try in ARIN:` line when the day skill allows it.
5. Make a page only when the requested format and valid public-sharing authority both permit it. Use the branded [page template](references/brief-page.html), HTML-escape every inserted source value, add no scripts or external assets, and publish through `present-file` under an opaque unique `.html` filename. Do not publish, force a connection, use a predictable filename, or overwrite an existing page when that authority is absent.

A scheduled agent produces only its final response. It does not request scheduler or send tools while firing. A draft or composed brief is not an external send, page, record, or schedule.

## Explicit Brief Job requests

When the user explicitly asks to create, update, pause, remove, or run a Brief Job, load `schedule-text`. Its job must load `daily-brief` plus the appropriate day skill (`day-open-rollcall` or `day-close-debrief`), never `schedule-text`; that is workflow routing, while runtime cron policy controls tool permissions. The self-contained job prompt names the IANA timezone, intended local time/days, chosen day skill, existing authorized output preference, and this rule: compose from the day skill and return only the final response.

Do not create, edit, pause, or remove a job from an ordinary brief request. Do not claim a scheduled delivery succeeded without the persisted platform, recipient, next local run, and days verified by `schedule-text`.

## Failure handling

Finish from available evidence when a source is absent or partial. State the specific gap; do not manufacture urgency, completion, owners, deadlines, delivery, or public authority. `failure_deliver: local` keeps raw failures out of SMS.