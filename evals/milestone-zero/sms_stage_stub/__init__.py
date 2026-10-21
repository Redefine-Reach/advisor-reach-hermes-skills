"""EVAL STUB of the production arin-sms-stage plugin (ARIN TEST evals only).

Same tool name, toolset and JSON schema as /opt/box/plugins/arin-sms-stage (skills 6014efa era).
- stage: runs the skill script's own pure gate/render functions in-process
  (strip_why_provenance, build_why_line, gate_why_and_body, content_placeholders,
  format_missing_line, attestation_text) and returns the production-shaped payload
  with the read-back ("attestation"). It writes no draft file and starts no process.
- send: ALWAYS refused (outcome eval_stub_no_send). cancel: acknowledged, no-op.
- No Telnyx, no network, no subprocess: while the stub runs, socket connect/create_connection
  and subprocess.Popen are replaced with functions that raise. The script's own send code is
  never called.
- Every call is appended (counts and flags only) to $ARIN_EVAL_SMS_STAGE_STUB_LOG if set.

Installed into each throwaway eval HERMES_HOME by live_session.install_sms_stage_stub when
ARIN_EVAL_SMS_STAGE_STUB=1. Never install it on a real box.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

SCRIPT_REL = Path("skills/sms-send-confirmed/scripts/sms_send_confirmed.py")
FROM_NUMBER = "+15550100000"  # fixture box DID
E164 = re.compile(r"^\+[1-9]\d{7,14}$")
DEFAULT_LOG = ""
UNAVAILABLE = "I couldn't stage that draft right now. Nothing was sent."
# The installed sms-send-confirmed script must expose these (6014efa-era API). Older scripts
# without the Why gates make the stub fail closed, like production when its script is missing.
REQUIRED_SCRIPT_API = ("GateFailure", "one_line", "build_why_line", "attestation_text")

# --- production schema, copied verbatim from arin-sms-stage (6014efa era) ---
SCHEMA = {
    "name": "sms_stage",
    "description": (
        "Stage, cancel, or send one draft text to a third party. "
        "Use this instead of the terminal for the sms-send-confirmed skill. "
        "stage takes approver, dest, and body, plus why, source_kind, source_date, and source_name. "
        "Pass why and source_kind on every stage; the script refuses to stage without them. "
        "Omit source_date and source_name when you do not have them. "
        "Show the owner the returned staged text exactly. "
        "When the owner's next text is exactly SEND, call action send with that draft_id only. "
        "Do not pass dest or body on send; both are taken from the staged draft, and the tool "
        "sends only when this turn's inbound text is SEND from the box owner's allowlisted number. "
        "The discard word is DROP: say \"Reply SEND to send, DROP to discard.\" Never tell the owner to reply "
        "CANCEL, STOP, END, QUIT, UNSUBSCRIBE, START or HELP; those are carrier keywords and CANCEL unsubscribes them. "
        "Use action cancel when the owner replies DROP or anything else that is not SEND."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["stage", "cancel", "send"]},
            "approver": {"type": "string", "description": "E.164 of the owner texting you. stage only."},
            "dest": {"type": "string", "description": "E.164 destination. stage only. Ignored on send."},
            "body": {"type": "string", "description": "Message text. stage only. Ignored on send."},
            "why": {
                "type": "string",
                "description": "Why this text is being staged. stage only. The script refuses to stage without it.",
            },
            "source_kind": {
                "type": "string",
                "description": (
                    "Where the request came from (owner_text, fub_note, gmail, etc.). stage only. "
                    "The tool refuses to stage without it. owner_text is stored for audit but the "
                    "owner read-back is one plain Why sentence with no source parenthetical."
                ),
            },
            "source_date": {
                "type": "string",
                "description": (
                    "Date of the source, YYYY-MM-DD. stage only. Omit for owner_text (stored as "
                    "null audit). Required for every other source-kind except none."
                ),
            },
            "source_name": {
                "type": "string",
                "description": "Name of the source. stage only. Omit when unknown.",
            },
            "draft_id": {"type": "string", "description": "Required for cancel and send."},
        },
        "required": ["action"],
    },
}


def _no_net(*_a, **_k):
    raise RuntimeError("eval stub: network and subprocess are disabled")


@contextlib.contextmanager
def _sealed():
    saved = (socket.socket.connect, socket.create_connection, subprocess.Popen)
    socket.socket.connect = _no_net
    socket.create_connection = _no_net
    subprocess.Popen = _no_net
    try:
        yield
    finally:
        socket.socket.connect, socket.create_connection, subprocess.Popen = saved


def _log(rec: dict) -> None:
    path = os.environ.get("ARIN_EVAL_SMS_STAGE_STUB_LOG") or DEFAULT_LOG
    if not path:
        return
    rec = {"t": round(time.time(), 1), "home": Path(os.environ.get("HERMES_HOME", "")).name, **rec}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(rec) + "\n").encode())
    finally:
        os.close(fd)


def _script():
    path = Path(os.environ.get("HERMES_HOME") or "/nonexistent") / SCRIPT_REL
    spec = importlib.util.spec_from_file_location("ssc_evalstub", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _refuse(outcome: str, say: str) -> str:
    return json.dumps({"ok": False, "outcome": outcome, "say": say})


def _stage(args: dict) -> tuple[str, dict]:
    why_raw = str(args.get("why") or "").strip()
    kind = str(args.get("source_kind") or "").strip().lower()
    date = str(args.get("source_date") or "").strip()
    name = str(args.get("source_name") or "").strip()
    body = str(args.get("body") or "").strip()
    dest = str(args.get("dest") or "").strip()
    meta = {"why_given": bool(why_raw), "kind": kind}
    if not why_raw or not kind:
        return _refuse("refused_no_why", "I need why and source_kind before I can stage that draft."), meta
    if kind not in ("none", "owner_text") and not date:
        return _refuse("refused_no_source_date", "I need source_date for that source before I can stage that draft."), meta
    if not E164.match(dest):
        return _refuse("error", "dest must be E.164"), meta
    if not body:
        return _refuse("error", "body is empty"), meta
    m = _script()
    missing_api = [f for f in REQUIRED_SCRIPT_API if not hasattr(m, f)]
    if missing_api:
        return json.dumps({"ok": False, "say": UNAVAILABLE}), {**meta, "outcome": "stub_script_incompatible"}
    strip = getattr(m, "strip_why_provenance", lambda s: s)
    gate = getattr(m, "gate_why_and_body", lambda why, _body: why)
    try:
        why_clean = strip(m.one_line(why_raw))
        m.build_why_line(why_clean, kind, date, name, "")
        why_shown = gate(why_clean, body)
        why_line, *_ = m.build_why_line(why_shown, kind, date, name, "")
    except m.GateFailure as failure:
        outcome = getattr(failure, "outcome", "refused")
        reason = getattr(failure, "reason", str(failure))
        return json.dumps({"ok": False, "exit": 2, "result": json.dumps({"ok": False, "outcome": outcome, "reason": reason})}), {**meta, "outcome": outcome}
    placeholders = getattr(m, "content_placeholders", lambda _b: [])(body)
    missing = getattr(m, "format_missing_line", lambda _p: "")(placeholders)
    shown = m.attestation_text(FROM_NUMBER, dest, body, why_line, missing)
    draft_id = os.urandom(8).hex()
    payload = {"ok": True, "outcome": "staged", "draft_id": draft_id, "dest": dest, "from": FROM_NUMBER,
               "why_line": why_line, "attestation": shown, "provider_called": False, "eval_stub": True}
    if missing:
        payload["missing_line"] = missing
    return json.dumps({"ok": True, "exit": 0, "result": json.dumps(payload)}), {**meta, "outcome": "staged", "why_len": len(why_shown)}


def run(args) -> str:
    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "").strip().lower()
    with _sealed():
        try:
            if action == "stage":
                out, meta = _stage(args)
            elif action == "send":
                out, meta = _refuse("eval_stub_no_send", "Eval stub: nothing was sent."), {"outcome": "eval_stub_no_send"}
            elif action == "cancel":
                out, meta = json.dumps({"ok": True, "outcome": "cancelled", "eval_stub": True}), {"outcome": "cancelled"}
            else:
                out, meta = _refuse("error", "unknown action"), {"outcome": "bad_action"}
        except Exception as exc:  # fail closed, like production
            out, meta = json.dumps({"ok": False, "say": UNAVAILABLE}), {"outcome": "stub_error", "error": type(exc).__name__}
    _log({"action": action, **meta})
    return out


def register(ctx) -> None:
    ctx.register_tool(
        name="sms_stage",
        toolset="smsstage",
        schema=SCHEMA,
        handler=lambda args, **_kw: run(args),
        description="EVAL STUB: stage or cancel one third-party SMS draft; send never sends.",
    )
