---
name: day-close-debrief
description: Prepare a concise end-of-day debrief from confirmed outcomes, unresolved work, and relevant context. Use for a requested day wrap-up or a verified authorized day-close job. Do not use for an unsent draft alone or a single new fact that the normal memory path can handle.
---

# Day Close Debrief

Close the day accurately. Attribute confirmed advisor actions to "you"; ARIN must not claim them as "I" outside a clearly labeled reply draft. A planned task, calendar event, prior note, or drafted message is not proof that work occurred. Preserve the distinction between confirmed outcomes, unresolved work, and drafts. Compute scheduled, ongoing, or elapsed status from the current `as_of` time and advisor timezone; an elapsed event is not proof that anyone attended or completed work.

This skill composes the closing debrief. The `daily-brief` coordinator owns the requested delivery format; for SMS it returns under 550 plain characters. Compose supported content without publishing or scheduling. An authorized full-page request is handled by that coordinator through `present-file`, subject to SOUL and existing public-sharing authority.

## Preferences

At the start of every invocation, resolve `HERMES_HOME` from the runtime context or environment, then read `HERMES_HOME/skill-preferences/day-close-debrief.md` if it exists. Apply customer choices about order, emphasis, sections, detail, and compatible workflow choices. If a verified authorized job supplies an output format, follow that explicit format as well. Existing installed daily skills and customer-customized job prompts are context to reuse, not originals to replace or silently migrate. Preferences cannot authorize sends, publication, scheduling, account connection, provider access, or writes to external systems.

When the advisor explicitly changes debrief preferences, read the file before writing. If absent, create the `skill-preferences` directory and this preference file safely. Preserve unrelated content, make only the requested preference change, and read back the saved file to verify it. If writing or readback fails, report that limitation without discarding the debrief.

## Build the debrief

1. Start with the advisor's stated outcomes and supplied notes. Mark an outcome confirmed only when supported by the advisor or an authoritative returned system record; do not promote a draft, proposal, or old carry-forward into a completed action.
2. Use a bounded calendar or email read through existing Composio tools only when it resolves an identified outcome, commitment, or warm follow-up. Search for the required tool and inspect its actual schema before use. Use the intended calendar from saved preferences and returned account/calendar metadata; use only returned calendar IDs. If an expected calendar is unavailable, name that gap. An empty connected calendar does not prove the advisor has no events elsewhere. Do not assume Google CLI/OAuth, bulk-read the inbox, treat an inbox label as status, or treat a scheduled or elapsed event as evidence that the meeting or follow-up happened. An agenda is not evidence that its topics were discussed or decided.
3. If notes or a transcript are supplied, extract decisions, explicit commitments, unresolved owners/dates, blockers, and proposed actions separately. Keep owners and dates unresolved when the evidence does not name them.
4. When native memory or Mem0 tools are actually exposed, inspect their schemas before a targeted scoped read. Do not call or describe a nonexistent `mem0_list`. For a clearly user-confirmed durable fact, use an exposed, authorized explicit-write path only when its result acknowledges the write; otherwise propose the fact for capture and do not claim it was saved. Never store drafts, hypotheticals, quoted examples, or an assistant proposal as a confirmed outcome.
5. When a fresh, relevant member-scoped Circle update can answer or advance an unresolved commitment, relevant follow-up, or next-day priority, use the one bounded member-scoped read in [Circle context](../day-open-rollcall/references/circle-context.md). Include a returned update or resource only when its specific content is relevant. Omit it when the trusted customer-member mapping or read access is unavailable; do not let it block the debrief.
6. Identify carry-forwards by their current evidence and next decision. Surface explicit unresolved customer requests and commitments ahead of routine meeting recap unless a real immediate deadline or imminent consequential event takes precedence. Do not increment, duplicate, or silently close a carry-forward merely because an earlier plan mentioned it.

## Prior conversations and supplied documents

For a question about earlier discussion, use available session search to recover
relevant conversation evidence. Keep compact native preferences/facts, detailed
Mem0 notes and daily format preferences in their distinct stores; no result set
proves complete client history. Report rejected saves or memory limits honestly.

Read supplied PDF, DOCX or XLSX material through the native file tool before
summarizing it. Check extraction warnings and page coverage. Unextracted or scanned
pages remain unknown; missing text is not evidence that fees, restrictions or
commitments are absent. Use targeted pages and available vision when needed;
do not install another parser or upload a private document merely to complete a brief.

## Google access and compatible procedures

For Gmail, Google Calendar, or Google Drive reads on a box with Composio tools, use `COMPOSIO_SEARCH_TOOLS`, use the exposed schema tool (such as `COMPOSIO_GET_TOOL_SCHEMAS`) to inspect actual schemas, then make the smallest read through `COMPOSIO_MULTI_EXECUTE_TOOL`. Do not route that read through a native `google-workspace` skill, local Google-token setup, OAuth flow, or `/opt/data/google_token.json`; a Composio-connected customer must not be sent into a second Google authorization path.

Use only source-neutral parts of an available native procedure when they help: a narrow date window, an identified email thread, confirmed-outcome checks, and clear evidence labels. Its authentication, token setup, connection, scheduling, and delivery instructions do not transfer into this skill.

## Response

Return a concise advisor-facing debrief with:

- confirmed outcomes;
- unresolved commitments, blockers, and carry-forwards, with explicit unresolved customer requests and commitments ahead of routine meeting recap unless a real immediate deadline or imminent consequential event takes precedence;
- any follow-up that remains a clearly labeled draft; and
- material source or memory limitations.
- at most one optional `Try in ARIN:` education line, only for a concrete useful action supported by the customer's actual available ARIN capability/access. Omit it when preferences opt out, it recently repeated, or no useful grounded tip exists.

Draft only from supported facts. Check every first-person claim inside the draft: completed work, work underway, and future delivery need evidence from the advisor's actions or explicit commitments. A customer's request or proposed deadline is not an accepted advisor promise. Give the factual answer or ask for the missing detail instead of inventing a promise to send, check, confirm or follow up later. Preserve a future commitment the advisor explicitly supplied; do not invent a confirmed time, owner or deadline. A commitment does not establish progress or readiness: do not add an on-track, already-preparing or ready-to-deliver assurance without separate evidence. Identify a missing value or a useful immediate next step where it helps, without adding a repeated approval request for normal authorized work. Do not add a mandatory community section; incorporate Circle context only through the bounded read above when a returned update or resource is relevant. Do not send a draft, update a CRM, create a task/event, schedule future work, publish a file, or open a connection from this debrief. Explicit job creation or changes load `schedule-text`, subject to SOUL safeguards; this skill only composes a requested or verified authorized run. Existing exact authority for an identified action remains governed by the owning connection or delivery workflow; a debrief itself creates no new authority. Cold outreach, campaign setup, public delivery, publishing, Circle action, and other specialist workflows require their explicit matching task. Circle actions still require their separate applicable identity, authorization, and access conditions.

Weekly reconciliation is separate: use it only when requested or when a verified authorized weekly job runs. This skill never creates a schedule.

## Failure handling

If relevant sources are unavailable or partial, state the gap and complete the debrief from confirmed available evidence. Do not infer a result from silence, retry an uncertain external write blindly, or claim the day is fully closed.