# RED-390 PR2 — Method A bake (spike only)

Box: `advisor-reach-internal` / pod `advisor-reach-internal-0` / namespace `advisor-reach-internal`.

No fleet. Do not advance `SKILLS_REF`. Do not roll Cos, Marc, or any customer box. Do not change Helm `allowedUsers`, customer YAML, Telnyx DIDs, or the portal. Do not set `TELNYX_SMS_ALLOW_ALL_USERS`.

## What this repo can do

On `outcome=sent`, `sms_send_confirmed.py` writes `/opt/data/sms-sessions/{E.164}.json` with `dest`, `sent_at`, `ttl_expires_at` (7 days), `telnyx_message_id`, `approver`, `draft_id`, `from`, and `body_hash`. It does not append that dest to `TELNYX_SMS_ALLOWED_USERS`.

`inbound` accepts a sender with a live session into `/opt/data/sms-events/{id}.json` (who, snippet, prior outbound, suggested next). It does not send. Expired and unknown senders are audited and rejected. `STOP` and the local opt-out file stay fail-closed.

`execute_code` strips `TELNYX_*`. The script refills `TELNYX_API_KEY`, `TELNYX_SMS_API_BASE` (telnyx-proxy), From, the static allowlist, and `TELEGRAM_ALLOWED_USERS` from `skills/sms-send-confirmed/runtime.env` when that file exists, else from `/proc/1/environ`. It does not override a key that is already set, and it does not print the values. Do not commit `runtime.env`.

Outbound delivery calls `discover_plugins()`, `platform_registry._resolve_all()`, then `telnyx_sms` `standalone_sender_fn`. It does not shell out to `hermes send --to telnyx_sms:…`.

Approvers may be an E.164 on `TELNYX_SMS_ALLOWED_USERS` or a numeric id on `TELEGRAM_ALLOWED_USERS`. The destination is never the approver.

## Why a skill cannot see the reply alone

The adapter webhook (`telnyx-sms-adapter.py` `_handle_webhook`) accepts `message.received`, then calls `handle_message`. Hermes `gateway/authz_mixin.py` `_principal_authorized` reads `TELNYX_SMS_ALLOWED_USERS` and drops everyone else. The webhook handler itself does not check that list. A dropped inbound never enters a skill.

## Spike hook (this pod only)

`/opt/hermes` is the image rootfs. This PR does not patch it and does not ship a fleet image.

On this pod only, after the own-number echo return in `_handle_webhook` and before media download / `handle_message`:

```python
from session_inbound_hook import capture, skip_agent_turn

payload = capture(from_number, text, message_id)
if skip_agent_turn(payload):
    return web.json_response({"ok": True})
```

`session_inbound_hook.py` lives next to this note. `skip_agent_turn` is true for `owner_event`, `unmatched`, `rejected_ttl`, and `refused_stop`. Those must not reach `handle_message`, or the agent will reply to the third party. A hook failure returns `None` and does not skip, so an owner text still reaches the static allowlist path.

If the rootfs is read-only, leave the image adapter in place. Copy the skill files onto the PVC under `/opt/data/skills/` and clear that skill's `__pycache__`. Sessions and the owner-event command still work. Live webhook accept waits on the one-pod hook above. Do not rebuild `box-fleet` to get there.

## Check

1. Owner on the static allowlist stages and replies `SEND` once. Audit `outcome=sent`. Session file exists. `TELNYX_SMS_ALLOWED_USERS` is unchanged.
2. Inbound from that dest inside 7 days writes one owner event and sends nothing back.
3. The same inbound after `ttl_expires_at`, or from any other number, does not write an owner event.
4. A reply to them is a new stage, and nothing goes out until a new `SEND`.
5. `STOP`, or a dest already in `/opt/data/audit/sms-opt-out.txt`, does not call Telnyx.
