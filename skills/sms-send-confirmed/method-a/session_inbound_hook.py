"""Method A spike hook. Not loaded by the fleet image.

Hermes enforces TELNYX_SMS_ALLOWED_USERS in gateway/authz_mixin.py after
TelnyxSmsAdapter._handle_webhook calls handle_message. A skill never sees
an inbound the gateway already dropped.

Call capture() from that webhook, then skip_agent_turn(). When the result
is true, return HTTP 200 and do not call handle_message. That records an
owner event without starting a chat with the sender. When capture() fails,
skip_agent_turn() is false so an owner text still reaches Hermes.
"""

from __future__ import annotations

import json
import os
import subprocess

CAPTURED_OUTCOMES = frozenset({"owner_event", "unmatched", "rejected_ttl", "refused_stop"})
DEFAULT_SCRIPT = "/opt/data/skills/sms-send-confirmed/scripts/sms_send_confirmed.py"


def skip_agent_turn(payload: object) -> bool:
    """True only when the gate recorded the inbound and a reply must not start."""
    return isinstance(payload, dict) and payload.get("outcome") in CAPTURED_OUTCOMES


def capture(sender: str, text: str, message_id: str, *, script: str | None = None) -> dict | None:
    """Run the skill `inbound` command. None means the hook could not classify."""
    path = script or os.environ.get("SMS_SEND_CONFIRMED_SCRIPT") or DEFAULT_SCRIPT
    try:
        proc = subprocess.run(
            [
                "python3",
                path,
                "inbound",
                "--sender",
                sender,
                f"--body={text}",
                "--message-id",
                message_id or "",
            ],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload
