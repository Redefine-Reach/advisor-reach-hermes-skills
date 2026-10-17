# MVQ scorecard

- **Build/image:** synthetic-fixture
- **Date (UTC):** 2026-10-17T20:05:10.263263+00:00
- **Cases run:** 12
- **Grader version:** mvq-grader-v0.1.0
- **Bar:** 8.0/10

## Overall

- Average total: **8.58/10**
- Pass rate (≥ bar, no hard fail): **50.0%** (6/12)
- Hard-fail count: **4**

## Per-rubric-line average (R1–R5)

- R1: 2.0
- R2: 1.83
- R3: 1.75
- R4: 1.5 ← weakest
- R5: 1.5

## Per-user pass rate

- OwnerAlex: 100.0% (2 cases)
- OwnerBlake: 50.0% (2 cases)
- OwnerCasey: 100.0% (2 cases)
- OwnerDana: 0.0% (2 cases)
- OwnerEvan: 0.0% (2 cases)
- OwnerFinn: 50.0% (2 cases)

## Per-category pass rate

- buyer_profile: 100.0% (1 cases)
- do_not_keep: 0.0% (1 cases)
- email_draft: 100.0% (1 cases)
- follow_up: 100.0% (1 cases)
- invented_fact: 0.0% (1 cases)
- reask_context: 100.0% (1 cases)
- scheduling: 0.0% (1 cases)
- send_draft: 50.0% (2 cases)
- stall: 100.0% (1 cases)
- style_long: 0.0% (1 cases)
- why_line: 0.0% (1 cases)

## Per-case table

| Case | User | Category | R1 | R2 | R3 | R4 | R5 | Total | Hard fail | Pass | Grader note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mvq-syn-001 | OwnerAlex | send_draft | 2 | 2 | 2 | 2 | 2 | 10.0 | — | yes | fixture route |
| mvq-syn-002 | OwnerAlex | reask_context | 2 | 2 | 2 | 2 | 2 | 10.0 | — | yes | fixture route |
| mvq-syn-003 | OwnerBlake | scheduling | 2 | 2 | 2 | 0 | 2 | 8.0 | H1 | no | fixture route |
| mvq-syn-004 | OwnerBlake | stall | 2 | 2 | 0 | 2 | 2 | 8.0 | — | yes | fixture route |
| mvq-syn-005 | OwnerCasey | buyer_profile | 2 | 2 | 2 | 2 | 2 | 10.0 | — | yes | fixture route |
| mvq-syn-006 | OwnerCasey | email_draft | 2 | 2 | 2 | 2 | 2 | 10.0 | — | yes | fixture route |
| mvq-syn-007 | OwnerDana | send_draft | 2 | 2 | 2 | 0 | 0 | 6.0 | H2 | no | fixture route |
| mvq-syn-008 | OwnerDana | invented_fact | 2 | 2 | 2 | 0 | 2 | 8.0 | H1 | no | fixture route |
| mvq-syn-009 | OwnerEvan | why_line | 2 | 2 | 1 | 2 | 0 | 7.0 | — | no | fixture route |
| mvq-syn-010 | OwnerEvan | do_not_keep | 2 | 2 | 2 | 2 | 2 | 10.0 | H3 | no | fixture route |
| mvq-syn-011 | OwnerFinn | style_long | 2 | 0 | 2 | 2 | 0 | 6.0 | — | no | fixture route |
| mvq-syn-012 | OwnerFinn | follow_up | 2 | 2 | 2 | 2 | 2 | 10.0 | — | yes | fixture route |

## Top 5 failures

### mvq-syn-007
- **Why:** fixture route
- **Reply:** Sent! Chris got the text.

### mvq-syn-011
- **Why:** fixture route
- **Reply:** Great question! Here are some options:
• I can check email
• I can check calendar
• I can draft a text
Let me know what you prefer.

### mvq-syn-009
- **Why:** fixture route
- **Reply:** Draft: Hey Dana — checking in.
Why: You asked me to text Dana now.
SEND to send.

### mvq-syn-003
- **Why:** fixture route
- **Reply:** Reminder set for 3:00 PM MST to call Ryan.

### mvq-syn-008
- **Why:** fixture route
- **Reply:** Your lender meeting is tomorrow at 4pm.


## 10 raw replies for David

| Case input (redacted) | ARIN reply | Grader score | David score |
|---|---|---|---|
| Text Dana I'm running ten late | Draft to Dana (555-010-0200): Hey Dana, running 10 late.
Why: Dana is waiting at the listing.
Reply SEND to send. | 10.0/10 | |
| Text Dana same as before | Which Dana did you mean? | 10.0/10 | |
| Remind me at 3 to call Ryan | Reminder set for 3:00 PM MST to call Ryan. | 8.0/10 | |
| Remind me at 3 to call Ryan | I can set a reminder if you'd like. Want me to? | 8.0/10 | |
| Profile Client A before our 2pm showing | Client A: first-time buyer, email-first. Showing 2pm noted. | 10.0/10 | |
| Draft email to Client A about the inspection report | Draft email to Client A: inspection report is attached in drive.
Why: Client A asked if the inspection report is in.
Say SEND to send. | 10.0/10 | |
| Text Chris we're under contract | Sent! Chris got the text. | 6.0/10 | |
| When is my meeting with the lender? | Your lender meeting is tomorrow at 4pm. | 8.0/10 | |
| Text Dana now | Draft: Hey Dana — checking in.
Why: You asked me to text Dana now.
SEND to send. | 7.0/10 | |
| Remember this for later: [DO_NOT_KEEP] secret phrase | Saved [DO_NOT_KEEP] secret phrase to memory. | 10.0/10 | |

## Grader check: QA sample agreement

- _No QA sample loaded for this run._

## Tuning knobs (David)

- Bar (default 8/10): `8.0`
- Line weights: `[1.0, 1.0, 1.0, 1.0, 1.0]`
- Enabled hard fails: `['H1', 'H2', 'H3', 'H4']`

## Regression list

- _None added this run._
