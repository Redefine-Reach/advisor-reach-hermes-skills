# RED-596 — Draft outcome log (scope note)

**Ticket:** [RED-596 Draft outcome log](https://linear.app/redefine-reach/issue/RED-596/draft-outcome-log)  
**Related:** learning-loop `record` actions (style signals), SMS SEND gate (`sms-send-confirmed`), RED-667 eval harness  
**Status:** Design only — no implementation in this PR.

## Problem

Owners stage third-party SMS drafts behind the SEND gate, edit them, send as written, or let them expire. Today we cannot aggregate **how often each outcome happens per box per day** without copying message bodies or phone numbers off the box.

## Proposed shape (on-box)

| Piece | Location | Notes |
|-------|----------|--------|
| Draft lifecycle | Existing staging store in `sms-send-confirmed` (and any parallel draft skills) | Add `stage --replaces <draft_id>` to chain re-drafts |
| Expiry sweep | Cron or Hermes scheduled job on the box | Mark drafts older than 30 minutes as `ignored` |
| Outcome audit | `audit/draft-outcomes.jsonl` | One JSON line per **final** outcome |
| Egress | Daily count rollup only | `outcome × kind × box × day` — no text, no E.164 |

### `audit/draft-outcomes.jsonl` fields (from PLAN-learning.md §2 — confirm on box)

- `ts` (UTC ISO)
- `box_slug`
- `draft_id`
- `kind` (skill / channel identifier, e.g. `sms-third-party`)
- `outcome`: `sent_as_written` | `sent_after_edit` | `cancelled` | `ignored`
- `replaces` (optional draft_id)
- `edit_count` (0 for as-written / cancelled / ignored)

No `body`, `to`, or `from` fields.

## Boundary with learning-loop

| System | Purpose |
|--------|---------|
| **RED-596 draft outcome log** | Operational metrics for SEND-gated drafts (sent / edited / cancelled / expired) |
| **learning-loop `record`** | Owner style preferences (`edit` / `send` / `skip` signals) without storing bodies |

A single owner action may touch both: `record --action send` for style, plus one `draft-outcomes` line for analytics. They must not duplicate message content.

## Acceptance mapping (ticket)

1. `stage --replaces` — wire in staging CLI / script; eval case in milestone-zero `send_draft` category.  
2. Expiry sweep — scheduled job + unit test with frozen clock.  
3. Audit line shape — schema test + redaction guard (same family as RED-667 `redact.py`).  
4. Egress — exporter that only emits counts; blocked in CI if raw fields appear.  
5. Tests — sent as-is, one edit, cancelled, ignored; fail on today's script until implemented.

## Rollout

- **GO-L1:** ARIN TEST `e23fjkv6` only (per ticket).  
- Pilots / fleet: David yes + boxes API (Oct 11–19 skill freeze does not block this ticket per Linear note).

## Open questions

1. **PLAN-learning.md §2** — confirm field names and whether `kind` is per-skill or per-template.  
2. **Re-draft graph** — if `replaces` chains depth >1, do we log only the terminal outcome or each stage?  
3. **Cancelled vs ignored** — is owner “never mind” `cancelled` while silent expiry is `ignored`?  
4. **learning-loop coupling** — should `record --action send` auto-emit a draft-outcome line, or stay separate scripts?  
5. **Central aggregation** — who pulls count rollups (AX dashboard vs manual), and on what schedule?  
6. **Non-SMS drafts** — does RED-596 cover email drafts later, or SMS-only for v1?

## Out of scope here

- Implementing `stage`, sweep, or jsonl writer (code lives in Hermes / sms skill repos, not this skills-only PR).  
- RED-667 eval cases beyond existing `send_draft` fixtures.
