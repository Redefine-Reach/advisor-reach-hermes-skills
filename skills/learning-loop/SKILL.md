---
name: learning-loop
description: "Save owner or client preferences and learned draft style. Use for an explicit preference, the same correction twice, what you remember, forget that, show, or the next draft of a kind."
---

# Learning loop

This is how ARIN keeps an explicit preference, a correction the owner repeats, and what the owner does with a draft. Texts use the `learning_loop` tool. A non-text session uses one script. It does not ask for approval. It does not turn silent background review on. It does not write memory, a cron job, or a skill with the file tool.

On a text turn, the terminal and `execute_code` are refused. Call the box plugin tool `learning_loop`. That is the path on texts. Do not try the script, the terminal, or `execute_code` there, and do not stop because those are blocked.

- `save` stores one preference, a repeated correction, a client procedure, or a draft style note.
- `show` lists what is remembered for the owner or one named client, including what to apply before a draft.
- `forget` removes the one item the owner named.

Pass the same scope, client, kind, and text the commands below use. If `learning_loop` returns an error, say that and stop.

In a non-text session, run the script from `execute_code` with an argument list:

`python3 /opt/data/skills/learning-loop/scripts/learning_loop.py`

Do not use `execute_code` on a text turn. Do not set `LEARNING_LOOP_TEST` or `LEARNING_LOOP_JUDGE`. Do not set `ARIN_DONOTKEEP_PY`.

On a text turn, a line below that says to run a command means call `learning_loop` with `save`, `show`, or `forget` and those fields. `save-explicit`, `note-correction`, `record`, and `write-client-skill` are `save`. `apply`, `list`, `next`, `show`, and `status` are `show`. `forget` is `forget`. It does not mean `execute_code`.

Every command prints one JSON object. `confirm` is either null or one line. Send that line to the owner only when `saved` is true and `confirm` is that line, and only after this command returns. If `confirm` is null, do not say it was saved. If `say` is set, say that sentence and stop. Do not add an approval question, a second sentence about the save, or a memory-tool call.

A preference is tagged to the owner (`--scope owner`) or to one named client (`--scope client --client "<name>"`). One save is one of those. It is not both, and it is not two clients.

## Explicit preference

When the owner states a preference, run `save-explicit` in this turn. Example: "For my Daily Brief, put new leads first and keep it to 5 bullets" is `--scope owner --kind daily-brief --text` that sentence. A preference about one client uses `--scope client` and that client's name.

Do not wait for a second statement. Do not ask whether to remember it.

## The same correction twice

When the owner corrects a draft or a brief, and they are not stating a new preference in the form above, run `note-correction` with the correction text, the same scope, client, and kind. The first time, `saved` is false and `confirm` is null. Say nothing about saving. The second time the same correction is given, the script saves it and returns `confirm`. A different wording, a different client, or a different kind does not count as the second time.

## After /new

`/new` drops the chat. It does not drop the file. On the first turn of a session, including the turn right after `/new`, run `apply` before a Daily Brief or a draft:

`apply --kind daily-brief`

Add `--client "<name>"` only when the work is about that one client. Follow every returned item for order, length, and emphasis. Owner items apply to the owner's work. A client's items apply only when that client was named. A preference does not authorize a send, a page, a job, or a CRM write.

## What you remember

"What do you remember about client A?" is:

`list --scope client --client "Client A"`

Reply with those preferences and client procedures. Do not include the owner and do not include any other client. "What do you remember about me?" is `list --scope owner`.

## Forget that

`forget` removes one preference. Pass `--id` from the list you just showed. `--text` is allowed only when it matches one preference. If `say` is `Which one should I forget? Ask me to list them.`, list them and stop. Do not delete a second item. `confirm` (`Forgot that.`) is sent only when `saved` is true.

## Do-not-keep

The script calls the box gate at `/opt/box/arin_donotkeep.py` (`on_pre_tool_call` for a memory add) before every save. Health details, Social Security numbers, and financial account numbers are never learned. Do not rephrase a blocked save to get it through. Do not copy the blocked text into a preference, a pending correction, a style note, a client skill, or memory.

## Client procedures

A per-client procedure is a small skill the script writes. You do not write it. Do not use `write_file`, `patch`, or a shell redirect on any `SKILL.md`. Run `write-client-skill` with `--client`, `--name`, `--when`, and one `--step` per step (at most six). The file lands under `$HERMES_HOME/skills/c-<client>--<procedure>/SKILL.md`. It applies only to that client. `forget --client "<name>" --procedure <name>` removes that one skill and no other.

## Style from drafts

When the owner edits, sends, or skips a draft, record that action before the next draft of the same kind. This is the mechanism, not a count over days. One action is enough.

- An edit is `record --kind <kind> --action edit --note "<the style change>"`. The note is the change ("shorter, no exclamation"), not the draft body. That is a style signal.
- A send is `record --kind <kind> --action send`. That is an acted-on signal. Do not pass `--note` or the body.
- A skip is `record --kind <kind> --action skip`. That is an acted-on signal. Do not pass `--note` or the body.

Do not announce the record. Before the next draft of that kind, run `next --kind <kind>` and follow each style note. Do not repeat an approach the owner skipped. `show` lists the learned signals. `show --kind <kind>` lists one kind. Neither command stores a message body or a phone number.

## Background review

Silent background review stays off. Do not run a review, do not create a review job, and do not change Hermes config. `status` reports `background_review` as `off`, `on`, or `unset`. `unset` and `off` stay as they are. If it is `on`, say so and do not start a review. This script has no command that turns it on.

## What you never do

- Do not call `memory`, Mem0, or `cronjob` to store a preference or a style signal.
- Do not say "saved" unless `confirm` is set.
- Do not send `confirm` before the command returns.
- Do not learn health, a Social Security number, or a financial account number.
- Do not write a client skill yourself.
- Do not turn background review on.
