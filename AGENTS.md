# Agent instructions

## Codex trial rules (RED tickets, Oct 2026)

These rules apply to any Codex task (cloud or local) on a Linear RED ticket. They win over anything broader in this file.

- Draft PRs only. Never merge, never mark a PR ready, never push to `main` or `production`, never force-push.
- Branch `codex/red-<id>` (e.g. `codex/red-698`). The PR title starts with the RED id (`RED-698: ...`).
- Base: `advisorreach-operations` and `advisorreach-boxes-api` work starts from `production`, not `main`, unless the ticket names another base (e.g. RED-698 in `advisor-reach-hermes-skills` uses `cursor/redaction-followups-df95`). Otherwise use the base the ticket names.
- No secrets: never read, print or commit keys, tokens, `.env` values or auth files.
- No fleet, box, Telnyx, live Stripe or GoHighLevel (GHL) work, and no deploys or infra changes. Use fakes and stubs.
- `advisor-reach-hermes-skills` is PUBLIC: synthetic test data only. No customer names, phone numbers, messages or box ids.
- CI: `gh run rerun --failed` at most twice. No empty retrigger commits.
- Stay inside the ticket. If it needs more scope, access or a forbidden action, stop and report on the ticket rather than widen scope.
- Maintainers review. Only the repository owner merges or deploys.
