---
name: mab-design-iteration
description: Run and iterate a MAB "Email Campaigns" Design pipeline in a customer Omega workspace — read the package docs first, iterate bounded at limit 1 Critic-first, never rapid-fire, drive the Copywriter↔Critic loop to all-accept, full drain only to farm bugs.
---

# MAB Design Iteration

The MAB package docs are the source of record; this skill points you to them and adds the operational specifics that are easy to get wrong. BEFORE firing anything, read: `read Docs/MAB/workflows/iterating-the-design-pipeline`, `read Docs/MAB/workflows/iterating-agent-instructions`, `read Docs/MAB/workflows/install-runbook`, `read Docs/MAB/agent-steps/critic-failure-modes`.

## Non-negotiable run discipline
- Iterate with BOUNDED single-STEP fires. Fire the install's `Workflows/Design/Coordinator/Critic` step with `-p "Event Handler" -m "on-event" -a '[{"limit":"1"}]'`; preview the `Copywriter` with `-a '[{"dry-run":"true","return-llm":"true","limit":"1"}]'`. Start small; widen only once it looks right.
- Keep `limit` SMALL (≤5). A large batch (e.g. `limit:40`) fails with `omega/query/no-return` in `Qo.Api.AgentService/send-message` — the oversized synchronous batch overwhelms the send phase. That is a PLATFORM error, not an instruction error; don't retry it bigger.
- ONE fire per drive, then let the coordinator go-loop self-drain ASYNCHRONOUSLY over the bus (poll `list-uncritiqued-copies` — the count drops on its own). The self-continue is FINITE: it drains a batch then stalls. A single deliberate fire after a CONFIRMED stall resumes it — that is NOT rapid-firing. NEVER rapid-fire `on-event`, and never fire an empty-map `[{}]` to iterate (it resets dispatch to Manager).
- The FULL coordinator self-drain (`Coordinator` `on-event -a '[{}]'`) is the LAST check only — run once, after the bounded runs already reach all-accept, to farm cross-step bugs. NEVER to iterate.
- OPERATOR GATE: Design iteration only — do NOT fire the `Execute` or `Allocation` steps.

## Verify the Brief BEFORE blaming the Copywriter (the #1 hidden deadlock)
The Critic's fact-grounding enumeration gate REJECTS any number/percentage/ratio/count/ranking that has no VERBATIM matching statement in the Brief. So if the Brief has no approved-facts list, EVERY proof-point draft is doomed no matter how the Copywriter is worded — the two agents lack a shared source of truth.
- When the Critic rejects a numeric/proof claim, first `read` the Brief and confirm it literally contains that exact approved string. A Brief that only says "approved proof points unchanged from vX" but never lists them is a BROKEN source of truth — a dangling reference, not an approved-facts list.
- Fix it at the Brief, not by guessing facts. Either add the exact truthful approved strings to the Brief (verbatim, operator-supplied — never invent a client's numbers), OR make the campaign number-free: state in the Brief "Approved proof points: NONE; no numeric statistic/count/percentage/ratio/ranking/award/dollar figure in any email or subject; lead with qualitative credibility and client-protection," and add the same hard rule to the Copywriter instruction.

## Editing instructions — Critic-first, via revisioned content
- CRITIC-FIRST: encode a defect as a Critic auto-reject hard-check first, confirm it rejects, THEN push the rule upstream into the Brief/Copywriter. Extend the Critic's existing gate; don't invent parallel checks.
- Edit an agent's instruction with `Get Revisioned Content` / `Append Revisioned Content` (args `table-name:"Instructions"`, `agent:"copywriter"|"critic"|…`, `new-html:"<FULL edited HTML>"`). It APPENDS a new revision (does not patch); send the whole instruction; the agent reads the latest revision on its NEXT run. Keep instructions LEAN — a bloated instruction is applied inconsistently.

## Isolating ONE treatment (there is no per-treatment filter)
The Copywriter/Critic steps expose only `{self, event}`; `limit` is a batch size, not a treatment selector, and batch order is not controllable. To reason about ONE treatment:
- Preview with a Copywriter DRY-RUN (`dry-run:true, return-llm:true`) — it writes nothing — and inspect one returned draft.
- A NUMBER-FREE Copy row is definitionally a draft written under the current no-numbers instruction; a still-number-bearing row is stale. Use that to tell fresh from stale without timestamps.

## The heal → re-critique loop (how convergence actually works)
- The Critic judges ONLY `list-uncritiqued-copies` and SKIPS rows that already have a Critique. So a rewritten draft is re-judged only once its old Critique is gone.
- The Copywriter heal SELF-DELETES the Critique rows of the copies it rewrites (`rewrite-count` == `delete-count`), leaving them uncritiqued for the next Critic drain. So normal convergence is simply: repeat (Copywriter heal `limit≤5` → Critic drain to `uncritiqued:0`). No manual deletes needed.
- Manual delete is ONLY for the stuck/​block-less-Notes healing case (`CRITIQUE_NOTES_MISSING`): delete the block-less Critique row with MCP `delete_page` on its EXACT `ls verbose` composite name (one call per row) — NEVER a `qo` composite-path delete (brackets/commas break shell escaping) and NEVER a table drop; then re-critique. Re-critique assigns a NEW page-id — match rows by `treatment_id` + `draft`, never page-id.

## Measuring convergence (use the reliable signal)
- The full Critiques-table verdict readback is UNRELIABLE on the composite-key table (large raw result; verdict column not always parsed). Do NOT gate on it.
- Use the Copywriter heal's own machine-readable `batched-reject-count` as the metric. CONVERGED when a heal returns `batched-reject-count: 0` + `skipped: no-work` and the Critic drain shows `uncritiqued: 0` — no rejects remain, every copy critiqued = all accept.
- Real STALL = the same nonzero `batched-reject-count` across 3 consecutive rounds (a draft the rewrite can't fix) → read those specific rejects' Notes and address the defect class, don't keep looping.

## Reading critique Notes (composite-key rows)
MCP `read`/`get` on a Critique row throws `AppNotFoundException` (composite `treatment_id::draft` name breaks slash-path resolution). Read Notes with `qo get-html '<install>/Data/Critiques/<exact ls-verbose name>' Notes` per row, or a `prop-vals-by-folder <Critiques-db-page-id>` scan. OBSERVE, don't assume: a clearing Copywriter dry-run is necessary but NOT sufficient — read each reject row's Notes and confirm it is real prose critique.

## Classify every failure
Separate PLATFORM failures (send-message no-return, gateway restart, go-loop stall — recover per install-runbook: Service start + one fire) from INSTRUCTION/Brief failures (fact-grounding, CTA, voice, disclosure — fix Critic-first in the Brief/Copywriter). Never treat a platform error as an instruction defect or vice versa.
