"""Minimal stand-in for the 6014efa-era sms_send_confirmed.py API, for the sms_stage eval stub
tests only. Synthetic. send() would open a network connection and start a process; the stub
must never call it."""
import socket
import subprocess

OWNER_TEXT_SUFFIX = "from your own text"


class GateFailure(Exception):
    def __init__(self, outcome, reason, **_kw):
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason


def one_line(raw):
    return " ".join(str(raw or "").split())


def strip_why_provenance(why):
    return why


def gate_why_and_body(why, body):
    if why.lower().startswith(("text ", "send ", "tell ")):
        raise GateFailure("refused_why_circular", "why repeats the action")
    if len(why.split()) < 4:
        raise GateFailure("refused_why_generic", "why is too thin")
    return why


def build_why_line(why, kind, date, name, ref):
    why = why.rstrip(" .")
    if kind == "owner_text":
        return f"Why: {why}, {OWNER_TEXT_SUFFIX}.", kind, None, None
    return f"Why: {why} (no source).", kind, None, None


def content_placeholders(body):
    return ["[PRICE]"] if "[PRICE]" in body else []


def format_missing_line(placeholders):
    return "Missing: the price. Reply with it to restage, or DROP to discard." if placeholders else ""


def attestation_text(from_number, dest, body, why_line, missing_line=""):
    lines = [f"You're about to send this text from ARIN's number ({from_number}) to {dest}.", body, why_line]
    if missing_line:
        lines.append(missing_line)
    lines += ["Reply SEND to confirm you authorize this one message and that the recipient may receive it.",
              "Reply SEND to send, DROP to discard.", "The recipient can still opt out with their carrier."]
    return "\n".join(lines)


def send(*_a, **_k):
    socket.create_connection(("api.telnyx.com", 443), timeout=1)
    subprocess.Popen(["true"])
    return 0
