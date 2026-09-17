# Gathering the brief — validated rules from real runs

Loaded at fire time (section E of SKILL.md). These rules came from an advisor's real morning-brief
runs; follow them for every source.

## Order of importance (never let a market statistic bury these)

1. A closing or deadline that is today or tomorrow, or a past next-deadline date that was never
   updated (decision needed today: stale sheet or lapsed deadline).
2. A calendar collision that involves a client-facing or revenue block (protect that block, name
   both events and the overlap; title-company pickups and closing logistics count as transactions).
3. A lead who replied and has had no answer (same priority as a deadline), then untouched recent
   leads, then aging ones.
4. Inbox items that explicitly need a reply or an action.
5. Market context, one line, dated.

## Per source

- **Calendar.** Establish the customer's current local time FIRST (the prompt's `User timezone:`
  line), then build the window [local midnight, next local midnight). Verify the returned event
  dates fall inside that window before summarizing; a query can silently reuse today's bounds when
  tomorrow was asked for. Parse bare dates as local calendar dates, never as UTC. Deduplicate mirrored
  events across calendars; a later invite saying someone cannot attend may REPLACE a meeting, not add one.
- **Email.** Metadata first (sender, subject, date); hydrate the body only for a shortlist. A broad
  "last 24h" query is mostly noise: filter by operational sender or topic (title/escrow, showing
  services, lenders, inspectors, co-op agents, genuine lead replies) before ranking. Exclude brokerage
  broadcasts, marketing, and social notifications.
- **Leads.** Lead-alert emails carry name, phone, email, source, inquiry and timestamp in the body;
  a partial alert (address + estimate only) is one retargeting note, not a call-list row. Search
  sent mail before claiming a lead was never contacted; if you did not, say "last touch unknown".
- **Pipeline (a spreadsheet or CRM).** "File visible" and "content parsed" are different claims. Do
  not say the pipeline was read unless the content parsed; keep "TBD" as "date not set"; never infer
  a deadline.
- **Market.** Show the data's date whenever it is not today; if the source is unavailable, say so and
  present no number. Basis points are points, not percent.

## Honest failure wording (use these shapes)

- "Pipeline file found, but its content could not be read. No closing dates or deadlines were inferred."
- "Market source unavailable; no current number is presented as fact."
- "Last-touch status unknown because sent mail was not checked."
- "Calendar: not connected." / "Email: not connected." (then: "Reply CONNECT to link it.")

## Tone

Businesslike and actionable. Enough lead context to make the call, never a dumped email body or
unrelated personal detail. Say "advisor", not "agent". No hype, no filler. The page is the
deliverable; the text is the lead-in.
