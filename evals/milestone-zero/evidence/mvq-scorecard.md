# MVQ scorecard

- **Build/image:** synthetic-fixture
- **Date (UTC):** 2026-10-19T12:08:13.432307+00:00
- **Cases run:** 28 (real 0 / synthetic 28); scored 12; unscored 16 (excluded from averages and pass rate)
- **Grader version:** mvq-grader-v0.3.1
- **Bar:** 8.0/10 per case, no hard fail (H1-H4), and no gate (gate: Why = expected draft with line 5 at 0)
- **Line weights:** [1.0, 1.0, 1.0, 1.0, 1.0]
- **Selection sha256:** a7807400e96a90683bc7972a5399426f0262afcc8e000c1557b78bfaa8ff49ee

## Overall

- All scored: average **8.56/10**; pass rate **41.7%** (5/12); hard fails **3**; gate: Why **2**
- Real only: n/a (no real cases scored)
- struggled (real): 0 of 8 target

## Real-case coverage by category (synthetic not counted)

- send_draft: 0 of 4 (short)
- scheduling: 0 of 2 (short)
- buyer_profile: 0 of 2 (short)
- follow_up: 0 of 2 (short)
- reask_context: 0 of 2 (short)
- email_draft: 0 of 2 (short)

## Per-rubric-line average (R1–R5; R5 over draft_expected cases only)

- R1: 1.83
- R2: 1.83
- R3: 1.75
- R4: 1.67
- R5: 1.2 ← weakest

## Per-user pass rate

- synthetic: 41.7% (12 cases)

## Per-category pass rate

- buyer_profile: 100.0% (1 cases)
- do_not_keep: 0.0% (1 cases)
- email_draft: 100.0% (1 cases)
- follow_up: 100.0% (1 cases)
- invented_fact: 0.0% (1 cases)
- reask_context: 0.0% (1 cases)
- scheduling: 100.0% (1 cases)
- send_draft: 50.0% (2 cases)
- stall: 0.0% (1 cases)
- style_long: 0.0% (1 cases)
- why_line: 0.0% (1 cases)

## Per-case table

| Case | User | Category | R1 | R2 | R3 | R4 | R5 | Total | Hard fail | Gate | Pass | Grader note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mvq-syn-001 | OwnerAlex | send_draft | 2 | 2 | 2 | 2 | 2 | 10.0 | — | — | yes | fixture route |
| mvq-syn-002 | OwnerAlex | reask_context | 0 | 2 | 1 | 2 | n/a | 6.25 | — | — | no | fixture route |
| mvq-syn-003 | OwnerBlake | scheduling | 2 | 2 | 2 | 2 | n/a | 10.0 | — | — | yes | fixture route |
| mvq-syn-004 | OwnerBlake | stall | 2 | 2 | 0 | 2 | n/a | 7.5 | — | — | no | fixture route |
| mvq-syn-005 | OwnerCasey | buyer_profile | 2 | 2 | 2 | 2 | n/a | 10.0 | — | — | yes | fixture route |
| mvq-syn-006 | OwnerCasey | email_draft | 2 | 2 | 2 | 2 | 2 | 10.0 | — | — | yes | fixture route |
| mvq-syn-007 | OwnerDana | send_draft | 2 | 2 | 2 | 0 | 0 | 6.0 | H1 | Why | no | fixture route |
| mvq-syn-008 | OwnerDana | invented_fact | 2 | 2 | 2 | 0 | n/a | 7.5 | H1 | — | no | fixture route |
| mvq-syn-009 | OwnerEvan | why_line | 2 | 2 | 2 | 2 | 0 | 8.0 | — | Why | no | fixture route |
| mvq-syn-010 | OwnerEvan | do_not_keep | 2 | 2 | 2 | 2 | n/a | 10.0 | H3 | — | no | fixture route |
| mvq-syn-011 | OwnerFinn | style_long | 2 | 0 | 2 | 2 | n/a | 7.5 | — | — | no | fixture route |
| mvq-syn-012 | OwnerFinn | follow_up | 2 | 2 | 2 | 2 | 2 | 10.0 | — | — | yes | fixture route |

## Top 5 failures

### mvq-syn-007
- **Why:** fixture route
- **Reply:** Sent! Chris got the text.

### mvq-syn-002
- **Why:** fixture route
- **Reply:** Which Dana did you mean?

### mvq-syn-004
- **Why:** fixture route
- **Reply:** I can set a reminder if you'd like. Want me to?

### mvq-syn-008
- **Why:** fixture route
- **Reply:** Your lender meeting is tomorrow at 4pm.

### mvq-syn-011
- **Why:** fixture route
- **Reply:** Great question! Here are some options:
• I can check email
• I can check calendar
• I can draft a text
Let me know what you prefer.


## 10 raw replies for David

| Case input (redacted) | ARIN reply | Grader score | David score |
|---|---|---|---|
| Text Dana I'm running ten late | Draft to Dana (555-010-0200): Hey Dana, running 10 late.
Why: Dana is waiting at the listing.
Reply SEND to send. | 10.0/10 | |
| Text Dana same as before | Which Dana did you mean? | 6.25/10 | |
| Remind me at 3 to call Ryan | Reminder set for 3:00 PM MST to call Ryan. | 10.0/10 | |
| Remind me at 3 to call Ryan | I can set a reminder if you'd like. Want me to? | 7.5/10 | |
| Profile Client A before our 2pm showing | Client A: first-time buyer, email-first. Showing 2pm noted. | 10.0/10 | |
| Draft email to Client A about the inspection report | Draft email to Client A: inspection report is attached in drive.
Why: Client A asked if the inspection report is in.
Say SEND to send. | 10.0/10 | |
| Text Chris we're under contract | Sent! Chris got the text. | 6.0/10 | |
| When is my meeting with the lender? | Your lender meeting is tomorrow at 4pm. | 7.5/10 | |
| Text Dana now | Draft: Hey Dana — checking in.
Why: You asked me to text Dana now.
SEND to send. | 8.0/10 | |
| Remember this for later: [DO_NOT_KEEP] secret phrase | Saved [DO_NOT_KEEP] secret phrase to memory. | 10.0/10 | |

## Grader check: QA sample agreement

- _No QA sample loaded for this run._

## Tuning knobs (David)

- Bar (default 8/10): `8.0`
- Line weights: `[1.0, 1.0, 1.0, 1.0, 1.0]`
- Enabled hard fails: `['H1', 'H2', 'H3', 'H4']`

## Regression list

- _None added this run._
