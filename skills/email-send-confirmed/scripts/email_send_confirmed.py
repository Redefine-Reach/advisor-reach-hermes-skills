#!/usr/bin/env python3
"""Owner-confirmed email from the advisor's Gmail (one recipient).

``stage`` writes a draft and a read-back. It does not send. ``send`` calls
Composio ``GMAIL_SEND_EMAIL`` only after the owner replies ``SEND`` or
``/approve`` and the caller passes ``--attest yes``. Cron and a delegated
child (``HERMES_DELEGATED_CHILD_CONTEXT``) stay ``refused_autonomous``.

The Why line is only in the owner read-back. It is not part of the message
body. This script does not remove ``GMAIL_SEND_EMAIL`` from the model's tool
list; the skill forbids calling that tool, and the box has to drop it for
the ban to be hard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, NoReturn
from urllib.parse import urlparse

ATTESTATION_VERSION = "email-send-v1"
DEFAULT_MAX_BODY_CHARS = 8000
PREVIEW_MAX = 240
DEFAULT_DRAFT_TTL_SECONDS = 1800
CONFIRM_TOKENS = frozenset({"send", "/approve"})
ATTEST_YES = frozenset({"yes", "y", "true", "1"})
TOOL_SLUG = "GMAIL_SEND_EMAIL"
DEFAULT_EXECUTE_URL = "https://backend.composio.dev/api/v3.1/tools/execute/GMAIL_SEND_EMAIL"
DELEGATED_CHILD_ENV = "HERMES_DELEGATED_CHILD_CONTEXT"
WHY_TEXT_MAX = 90
WHY_LINE_MAX = 120
SOURCE_LABELS = {
    "fub_note": "FUB note",
    "fub_record": "FUB record",
    "ghl": "GHL record",
    "calendar": "calendar",
    "owner_text": "your text",
}
NAME_SOURCE_KINDS = frozenset({"gmail", "memory"})
SOURCE_KINDS = frozenset(SOURCE_LABELS) | NAME_SOURCE_KINDS | {"none"}
SOURCE_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WHY_TOKEN_RE = re.compile(r"(?i)(?:\b(?:send|stop)\b|/approve)")
_GSM7_ORDINALS = (
    *range(0x20, 0x5B),
    0x5F,
    *range(0x61, 0x7B),
    0xA1,
    0xA3,
    0xA4,
    0xA5,
    0xA7,
    0xBF,
    0xC4,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xD1,
    0xD6,
    0xD8,
    0xDC,
    0xDF,
    0xE0,
    0xE4,
    0xE5,
    0xE6,
    0xE8,
    0xE9,
    0xEC,
    0xF1,
    0xF2,
    0xF6,
    0xF8,
    0xF9,
    0xFC,
    0x394,
    0x393,
    0x39B,
    0x3A9,
    0x3A0,
    0x3A8,
    0x3A3,
    0x398,
    0x39E,
    0x3A6,
    0x5E,
    0x7B,
    0x7D,
    0x5C,
    0x5B,
    0x5D,
    0x7E,
    0x7C,
    0x20AC,
)
GSM7_CHARS = frozenset(chr(code) for code in _GSM7_ORDINALS)
_WHY_FOLDS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
}
CRON_ENVS = (
    "HERMES_CRON_JOB_ID",
    "HERMES_CRON_JOB_NAME",
    "HERMES_CRON_AUTO_DELIVER_PLATFORM",
    "HERMES_CRON_AUTO_DELIVER_CHAT_ID",
)
HYDRATE_KEYS = (
    "COMPOSIO_API_KEY",
    "TELNYX_SMS_ALLOWED_USERS",
    "TELNYX_SMS_ALLOW_ALL_USERS",
    "TELEGRAM_ALLOWED_USERS",
)
AUDIT_KEYS = (
    "ts",
    "box_id",
    "approver",
    "approved_at",
    "attestation_version",
    "to",
    "from_account",
    "subject_hash",
    "body_hash",
    "body_len",
    "source_kind",
    "provider_message_id",
    "provider_status",
    "outcome",
    "reason",
    "draft_id",
    "provider_called",
)
POD_NAME = re.compile(r"^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)-\d+$")
E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
TELEGRAM_ID_RE = re.compile(r"^[0-9]{5,20}$")
PHONE_CHARS = re.compile(r"^[\d+\s().-]+$")
MULTI_DEST = re.compile(r"[,;\n|&]|\band\b", re.IGNORECASE)
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
FROM_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .@_+'-]{0,79}$")
ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,80}$")
LISTISH = re.compile(
    r"(moo|mutual\s+of\s+omaha|nurture|book of business|\.csv\b|\.xlsx\b|"
    r"lead list|contact list|\beveryone\b)",
    re.IGNORECASE,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2


class GateFailure(Exception):
    """A fail-closed result. ``provider_called`` is always false."""

    def __init__(
        self,
        outcome: str,
        reason: str,
        *,
        field: str | None = None,
        status: int = EXIT_REFUSED,
        extra: dict | None = None,
    ) -> None:
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason
        self.field = field
        self.status = status
        self.extra = extra or {}


def utc_now() -> datetime:
    if os.environ.get("EMAIL_SEND_CONFIRMED_TEST") == "1":
        raw = str(os.environ.get("EMAIL_NOW", "")).strip()
        if raw:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
    return datetime.now(timezone.utc)


def iso(when: datetime) -> str:
    return when.isoformat()


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def redact(text: str) -> str:
    out = str(text or "").replace("\n", " ")
    key = str(os.environ.get("COMPOSIO_API_KEY", "")).strip()
    if key and key in out:
        out = out.replace(key, "[redacted]")
    return out[:500]


def refuse_why(reason: str) -> NoReturn:
    raise GateFailure("refused_no_why", reason, field="why")


def one_line(raw: str) -> str:
    """Fold the plan's punctuation to ASCII and drop newlines."""
    flat = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    folded = "".join(_WHY_FOLDS.get(char, char) for char in flat)
    return re.sub(r"[ \t]+", " ", folded).strip()


def format_source_date(raw: str) -> str:
    text = str(raw or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        refuse_why("source-date must be YYYY-MM-DD")
    if parsed.strftime("%Y-%m-%d") != text:
        refuse_why("source-date must be YYYY-MM-DD")
    return f"{SOURCE_MONTHS[parsed.month - 1]} {parsed.day}"


def build_why_line(
    why_raw: str,
    kind_raw: str,
    date_raw: str,
    name_raw: str,
    ref_raw: str,
) -> tuple[str, str, str, str]:
    """Render the owner Why line. Returns line, kind, ISO date, and ref.

    ``none`` is the only kind allowed without a date, and only with no ref.
    The message body is not touched. The format matches Path A red-390-v2.
    """
    kind = str(kind_raw or "").strip().lower()
    why = one_line(why_raw)
    name = one_line(name_raw)
    ref = str(ref_raw or "").strip()
    date_text = str(date_raw or "").strip()
    if not why or not kind:
        refuse_why("stage requires --why and --source-kind")
    if len(why) > WHY_TEXT_MAX:
        refuse_why(f"why is {len(why)} characters; the limit is {WHY_TEXT_MAX}")
    if kind not in SOURCE_KINDS:
        refuse_why(
            "source-kind must be fub_note, fub_record, ghl, gmail, calendar, owner_text, memory, or none"
        )
    if ref and re.search(r"[\x00-\x1f]", ref):
        refuse_why("source-ref must be one line")
    if kind == "none":
        if date_text or ref:
            refuse_why("source-kind none cannot include a date or ref")
        line = f"Why: {why} (no source)."
        stored_date = ""
    else:
        if not date_text:
            refuse_why("source-date is required unless source-kind is none")
        shown_date = format_source_date(date_text)
        if kind in NAME_SOURCE_KINDS:
            if not name:
                refuse_why("source-name is required for gmail and memory")
            if re.search(r"[,()]", name):
                refuse_why("source-name must not contain commas or parentheses")
            if kind == "gmail":
                label = f"Gmail from {name}"
            elif kind == "memory":
                label = f"ARIN memory: {name}"
            else:
                refuse_why("source-name is not used for this source-kind")
        else:
            label = SOURCE_LABELS[kind]
        line = f"Why: {why} ({label}, {shown_date})."
        stored_date = date_text
    if any(char not in GSM7_CHARS for char in line):
        refuse_why("Why line must be GSM-7")
    if WHY_TOKEN_RE.search(line):
        refuse_why("Why line must not contain SEND, /approve, or STOP")
    if len(line) > WHY_LINE_MAX:
        refuse_why(f"Why line is {len(line)} characters; the limit is {WHY_LINE_MAX}")
    return line, kind, stored_date, ref


def body_preview(body: str) -> str:
    """One line the owner can read. The send still uses the full body."""
    flat = str(body or "").replace("\r\n", "\n").replace("\r", "\n")
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", flat)
    flat = re.sub(r"[ \t]+", " ", flat).strip()
    if len(flat) <= PREVIEW_MAX:
        return flat
    shown = flat[:PREVIEW_MAX].rstrip()
    omitted = len(flat) - len(shown)
    return f"{shown} [+{omitted} characters not shown]"


def attestation_text(
    from_account: str,
    to_addr: str,
    subject: str,
    preview: str,
    why_line: str,
) -> str:
    return (
        f"You're about to send this email from {from_account} to {to_addr}.\n"
        f"Subject: {subject}\n"
        f"Body: {preview}\n"
        f"{why_line}\n"
        "Reply SEND to confirm you authorize this one email and that the recipient may receive it.\n"
        "Reply anything else to cancel."
    )


def classify_phone(raw: str) -> tuple[str, str | None]:
    text = str(raw or "").strip()
    if not text:
        return "invalid", None
    if LISTISH.search(text) or MULTI_DEST.search(text) or len(re.findall(r"\+\d{8,}", text)) > 1:
        return "multi", None
    if not PHONE_CHARS.fullmatch(text):
        return "invalid", None
    if text.startswith("+"):
        candidate = "+" + re.sub(r"\D", "", text)
    else:
        digits = re.sub(r"\D", "", text)
        if len(digits) == 10:
            candidate = "+1" + digits
        elif len(digits) == 11 and digits.startswith("1"):
            candidate = "+" + digits
        else:
            return "invalid", None
    if not E164_RE.fullmatch(candidate):
        return "invalid", None
    return "ok", candidate


def require_phone(raw: str, field: str) -> str:
    kind, number = classify_phone(raw)
    if kind == "multi":
        raise GateFailure(
            "refused_multi",
            "Name one owner number.",
            field=field,
        )
    if kind != "ok" or not number:
        raise GateFailure(
            "error",
            f"{field} is not one E.164 number",
            field=field,
            status=EXIT_ERROR,
        )
    return number


def one_email(raw: str, field: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise GateFailure("error", f"{field} is empty", field=field, status=EXIT_ERROR)
    if LISTISH.search(text) or MULTI_DEST.search(text) or text.count("@") != 1:
        raise GateFailure(
            "refused_multi",
            "Name one recipient. Lists, Cc, and Bcc are refused.",
            field=field,
        )
    local, domain = text.split("@", 1)
    candidate = f"{local}@{domain.lower()}"
    if not EMAIL_RE.fullmatch(candidate):
        raise GateFailure("error", f"{field} is not one email address", field=field, status=EXIT_ERROR)
    return candidate


def require_from_account(raw: str) -> str:
    text = one_line(raw)
    if "@" in text:
        text = one_email(text, "from_account")
    if not text or not FROM_LABEL_RE.fullmatch(text):
        raise GateFailure(
            "error",
            "from-account must be one mailbox or alias",
            field="from_account",
            status=EXIT_ERROR,
        )
    if WHY_TOKEN_RE.search(text):
        raise GateFailure(
            "refused_no_why",
            "from-account must not contain SEND, /approve, or STOP",
            field="from_account",
        )
    return text


def require_connected_account(raw: str) -> str:
    text = str(raw or "").strip()
    if not ACCOUNT_ID_RE.fullmatch(text):
        raise GateFailure(
            "error",
            "connected-account must be the Composio account id",
            field="connected_account",
            status=EXIT_ERROR,
        )
    return text


def require_subject(raw: str) -> str:
    text = one_line(raw)
    if not text:
        raise GateFailure("error", "subject is empty", field="subject", status=EXIT_ERROR)
    if len(text) > 200:
        raise GateFailure(
            "refused_multi",
            f"subject is {len(text)} characters; the limit is 200",
            field="subject",
        )
    if WHY_TOKEN_RE.search(text):
        raise GateFailure(
            "refused_no_why",
            "subject must not contain SEND, /approve, or STOP",
            field="subject",
        )
    return text


def require_body(raw: str) -> str:
    body = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        raise GateFailure("error", "body is empty", field="body", status=EXIT_ERROR)
    if len(body) > DEFAULT_MAX_BODY_CHARS:
        raise GateFailure(
            "refused_multi",
            f"body is {len(body)} characters; the limit is {DEFAULT_MAX_BODY_CHARS} so one confirm stays one email",
            field="body",
        )
    return body


def box_id_from_hostname(hostname: str) -> str | None:
    short = str(hostname or "").strip().lower().split(".")[0]
    match = POD_NAME.fullmatch(short)
    if not match:
        return None
    return match.group(1)


def resolve_box_id(
    hostname: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Pod name wins. A caller-supplied id cannot impersonate another box."""
    env = os.environ if environ is None else environ
    host = socket.gethostname() if hostname is None else hostname
    from_pod = box_id_from_hostname(host)
    if from_pod:
        return from_pod
    url = str(env.get("BOX_PUBLIC_BASE_URL", "")).strip()
    if url:
        label = (urlparse(url).hostname or "").split(".")[0].strip().lower()
        if label:
            return label
    return str(env.get("SMS_BOX_ID", "")).strip().lower()


def paths(environ: Mapping[str, str] | None = None) -> dict[str, Path]:
    env = os.environ if environ is None else environ
    audit = Path(env.get("EMAIL_AUDIT_PATH", "/opt/data/audit/email-outbound.jsonl"))
    drafts = Path(env.get("EMAIL_DRAFT_DIR", "/opt/data/audit/email-drafts"))
    return {"audit": audit, "drafts": drafts}


def draft_ttl(environ: Mapping[str, str] | None = None) -> timedelta:
    env = os.environ if environ is None else environ
    raw = str(env.get("EMAIL_DRAFT_TTL_SECONDS", str(DEFAULT_DRAFT_TTL_SECONDS))).strip()
    try:
        seconds = int(raw)
    except ValueError:
        seconds = DEFAULT_DRAFT_TTL_SECONDS
    return timedelta(seconds=max(0, seconds))


def _env_file_values(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _proc_environ_values(path: Path) -> dict[str, str]:
    try:
        blob = path.read_bytes()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for item in blob.split(b"\0"):
        if b"=" not in item:
            continue
        key_b, value_b = item.split(b"=", 1)
        try:
            key = key_b.decode("utf-8")
            value = value_b.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if key:
            values[key] = value
    return values


def hydrate_email_env() -> list[str]:
    """Fill missing keys from the skill runtime.env file, then pid 1.

    ``execute_code`` may strip ``COMPOSIO_API_KEY`` and ``TELNYX_*`` before
    this process starts. Values already set are left alone.
    """
    if os.environ.get("EMAIL_SEND_CONFIRMED_TEST") == "1" and os.environ.get("EMAIL_HYDRATE_IN_TEST") != "1":
        return []
    runtime_path = Path(
        os.environ.get("EMAIL_RUNTIME_ENV_FILE") or (Path(__file__).resolve().parents[1] / "runtime.env")
    )
    proc_path = Path(os.environ.get("EMAIL_PROC_ENVIRON") or "/proc/1/environ")
    runtime_vals = _env_file_values(runtime_path)
    proc_vals = _proc_environ_values(proc_path)
    filled: list[str] = []
    for key in HYDRATE_KEYS:
        if str(os.environ.get(key, "")).strip():
            continue
        value = runtime_vals.get(key, "").strip() or proc_vals.get(key, "").strip()
        if not value:
            continue
        os.environ[key] = value
        filled.append(key)
    return filled


def phone_allowlist(environ: Mapping[str, str] | None = None) -> set[str]:
    env = os.environ if environ is None else environ
    if truthy(env.get("TELNYX_SMS_ALLOW_ALL_USERS")):
        raise GateFailure(
            "refused_autonomous",
            "TELNYX_SMS_ALLOW_ALL_USERS is set; email send stays closed",
        )
    raw = str(env.get("TELNYX_SMS_ALLOWED_USERS", "")).strip()
    owners: set[str] = set()
    for part in raw.split(","):
        if not part.strip():
            continue
        owners.add(require_phone(part, "approver"))
    return owners


def telegram_allowlist(environ: Mapping[str, str] | None = None) -> set[str]:
    env = os.environ if environ is None else environ
    raw = str(env.get("TELEGRAM_ALLOWED_USERS", "")).strip()
    ids: set[str] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if not TELEGRAM_ID_RE.fullmatch(token):
            raise GateFailure(
                "error",
                "TELEGRAM_ALLOWED_USERS has an entry that is not a numeric user id",
                field="approver",
                status=EXIT_ERROR,
            )
        ids.add(token)
    return ids


def resolve_approver(raw: str, phones: set[str], telegram_ids: set[str]) -> str:
    text = str(raw or "").strip()
    if text in telegram_ids:
        return text
    kind, number = classify_phone(text)
    if kind == "ok" and number and number in phones:
        return number
    if not phones and not telegram_ids:
        raise GateFailure(
            "refused_not_owner",
            "owner allowlist is empty; refusing email send",
            field="approver",
        )
    raise GateFailure(
        "refused_not_owner",
        "approver is not an allowlisted owner of this box",
        field="approver",
    )


def assert_box(box_id: str) -> None:
    if not str(box_id or "").strip():
        raise GateFailure(
            "refused_no_box",
            "box id is unresolved; email send stays closed",
        )


def assert_not_cron(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    for name in CRON_ENVS:
        if str(env.get(name, "")).strip():
            raise GateFailure(
                "refused_autonomous",
                "scheduled and standing jobs cannot send email",
            )


def assert_not_delegated_child(environ: Mapping[str, str] | None = None) -> None:
    """A delegated child must not stage or send (PLAN-subagents §2.6)."""
    env = os.environ if environ is None else environ
    if str(env.get(DELEGATED_CHILD_ENV, "")).strip():
        raise GateFailure(
            "refused_autonomous",
            "a delegated child cannot stage or send email",
        )


def append_audit(path: Path, record: dict) -> None:
    banned = {"body", "subject", "text", "why", "why_line", "preview", "attestation", "api_key"}
    if banned & set(record):
        raise RuntimeError("audit record must not contain the message or the key")
    line = {key: record.get(key) for key in AUDIT_KEYS}
    payload = json.dumps(line, separators=(",", ":"), ensure_ascii=True) + "\n"
    if "\n" in payload[:-1]:
        raise RuntimeError("audit record must be one line")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def audit(
    store: dict[str, Path],
    *,
    box_id: str,
    approver: str,
    to_addr: str,
    from_account: str,
    subject: str,
    body: str,
    outcome: str,
    reason: str,
    source_kind: str = "",
    approved_at: str | None = None,
    draft_id: str | None = None,
    provider_message_id: str | None = None,
    provider_status: str | None = None,
    provider_called: bool = False,
) -> None:
    append_audit(
        store["audit"],
        {
            "ts": iso(utc_now()),
            "box_id": box_id,
            "approver": approver,
            "approved_at": approved_at,
            "attestation_version": ATTESTATION_VERSION,
            "to": to_addr,
            "from_account": from_account,
            "subject_hash": body_hash(subject) if subject else "",
            "body_hash": body_hash(body) if body else "",
            "body_len": len(body),
            "source_kind": source_kind,
            "provider_message_id": provider_message_id,
            "provider_status": provider_status,
            "outcome": outcome,
            "reason": redact(reason),
            "draft_id": draft_id,
            "provider_called": provider_called,
        },
    )


class DraftLock:
    def __init__(self, directory: Path) -> None:
        self.path = directory / ".lock"

    def __enter__(self) -> "DraftLock":
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                self.path.mkdir()
                return self
            except FileExistsError:
                try:
                    stale = time.time() - self.path.stat().st_mtime > 90
                except OSError:
                    stale = False
                if stale:
                    try:
                        self.path.rmdir()
                    except OSError:
                        pass
                    continue
                time.sleep(0.02)
        raise GateFailure(
            "error",
            "another email confirm is in progress; not sending",
            status=EXIT_ERROR,
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.path.rmdir()
        except OSError:
            return


def draft_path(directory: Path, draft_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", draft_id or ""):
        raise GateFailure("error", "draft id is not valid", field="draft_id", status=EXIT_ERROR)
    return directory / f"{draft_id}.json"


def read_draft(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateFailure(
            "error",
            f"draft is unreadable ({exc.__class__.__name__}); not sending",
            status=EXIT_ERROR,
        ) from exc
    if not isinstance(data, dict):
        raise GateFailure("error", "draft is unreadable; not sending", status=EXIT_ERROR)
    return data


def write_draft(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".draft-", dir=path.parent)
    try:
        os.write(fd, blob)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)


def parse_expiry(draft: dict) -> datetime:
    raw = str(draft.get("expires_at") or "")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise GateFailure("error", "draft expiry is unreadable; not sending", status=EXIT_ERROR) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def pending_blocks(directory: Path, now: datetime) -> bool:
    if not directory.exists():
        return False
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        if not isinstance(data, dict) or data.get("status") != "pending":
            continue
        try:
            if now < parse_expiry(data):
                return True
        except GateFailure:
            return True
    return False


def is_confirm(token: str) -> bool:
    return str(token or "").strip().lower() in CONFIRM_TOKENS


def is_attest(token: str) -> bool:
    return str(token or "").strip().lower() in ATTEST_YES


def gmail_arguments(to_addr: str, subject: str, body: str, from_account: str) -> dict:
    """Arguments for one plain-text GMAIL_SEND_EMAIL. No Cc, Bcc, or attachment."""
    arguments = {
        "recipient_email": to_addr,
        "subject": subject,
        "body": body,
        "user_id": "me",
        "is_html": False,
    }
    if "@" in from_account:
        arguments["from_email"] = from_account
    return arguments


def execute_url(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = str(env.get("COMPOSIO_GMAIL_EXECUTE_URL") or DEFAULT_EXECUTE_URL).strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "backend.composio.dev":
        raise GateFailure(
            "error",
            "Gmail execute URL is not the Composio host; not sending",
            field="composio",
            status=EXIT_ERROR,
        )
    if not parsed.path.rstrip("/").endswith("/tools/execute/GMAIL_SEND_EMAIL"):
        raise GateFailure(
            "error",
            "Gmail execute URL is not GMAIL_SEND_EMAIL; not sending",
            field="composio",
            status=EXIT_ERROR,
        )
    return raw


def _message_id(data: object) -> str:
    if isinstance(data, str):
        text = data.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return _message_id(json.loads(text))
            except json.JSONDecodeError:
                return ""
        return ""
    if isinstance(data, dict):
        for key in ("id", "message_id", "messageId"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("response_data", "data", "result"):
            if key in data:
                found = _message_id(data.get(key))
                if found:
                    return found
    return ""


def interpret_provider(status: int, raw: bytes) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and payload.get("success") is True and payload.get("message_id"):
        return {
            "success": True,
            "message_id": str(payload["message_id"]),
            "provider_status": str(payload.get("provider_status") or "accepted"),
            "provider_called": True,
            "error": "",
        }
    if isinstance(payload, dict) and payload.get("successful") is True:
        message_id = _message_id(payload.get("data"))
        if not message_id:
            return {
                "success": False,
                "message_id": "",
                "provider_status": "accepted",
                "provider_called": True,
                "error": "provider returned no message id; this draft will not be retried",
            }
        return {
            "success": True,
            "message_id": message_id,
            "provider_status": "accepted",
            "provider_called": True,
            "error": "",
        }
    reason = ""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            reason = str(err.get("message") or "")
        elif err:
            reason = str(err)
        elif payload.get("message"):
            reason = str(payload.get("message"))
    if not reason:
        reason = f"composio http {status}"
    return {
        "success": False,
        "message_id": "",
        "provider_status": "error",
        "provider_called": True,
        "error": redact(reason),
    }


def execute_gmail(to_addr: str, subject: str, body: str, from_account: str, connected_account: str) -> dict:
    api_key = str(os.environ.get("COMPOSIO_API_KEY", "")).strip()
    if not api_key:
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "provider_called": False,
            "error": "COMPOSIO_API_KEY is not set",
            "field": "composio",
        }
    try:
        url = execute_url()
    except GateFailure as failure:
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "provider_called": False,
            "error": failure.reason,
            "field": failure.field or "composio",
        }
    payload = {
        "connected_account_id": connected_account,
        "version": "latest",
        "arguments": gmail_arguments(to_addr, subject, body, from_account),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(1_000_000)
            status = int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        raw = exc.read(1_000_000)
        return interpret_provider(int(exc.code), raw)
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "provider_called": True,
            "error": "provider timed out; this draft will not be retried",
        }
    return interpret_provider(status, raw)


def parse_transport_stdout(stdout: str, stderr: str, code: int) -> dict:
    try:
        payload = json.loads(stdout or "null")
    except json.JSONDecodeError:
        payload = None
    if code != 0 or not isinstance(payload, dict):
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "provider_called": True,
            "error": redact(stderr or stdout or f"transport exit {code}"),
        }
    return interpret_provider(200, json.dumps(payload).encode("utf-8"))


def deliver(to_addr: str, subject: str, body: str, from_account: str, connected_account: str) -> dict:
    """One Gmail send. Test mode never falls through to Composio."""
    arguments = gmail_arguments(to_addr, subject, body, from_account)
    if "cc" in arguments or "bcc" in arguments or "extra_recipients" in arguments or "attachment" in arguments:
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "provider_called": False,
            "error": "refusing a send that is not one plain recipient",
        }
    if os.environ.get("EMAIL_SEND_CONFIRMED_TEST") == "1":
        transport = os.environ.get("EMAIL_SEND_TRANSPORT", "").strip()
        if not transport:
            return {
                "success": False,
                "message_id": "",
                "provider_status": "error",
                "provider_called": False,
                "error": "test mode has no transport",
            }
        request = {
            "tool_slug": TOOL_SLUG,
            "connected_account_id": connected_account,
            "arguments": arguments,
        }
        kept = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "LANG", "CALLS")
            if key in os.environ
        }
        proc = subprocess.run(
            [transport],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env=kept,
        )
        return parse_transport_stdout(proc.stdout, proc.stderr, proc.returncode)
    return execute_gmail(to_addr, subject, body, from_account, connected_account)


def emit(payload: dict, status: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return status


def context() -> dict:
    hydrate_email_env()
    box_id = resolve_box_id()
    assert_not_cron()
    assert_not_delegated_child()
    assert_box(box_id)
    phones = phone_allowlist()
    telegram = telegram_allowlist()
    if not phones and not telegram:
        raise GateFailure(
            "refused_not_owner",
            "owner allowlist is empty; refusing email send",
        )
    store = paths()
    return {
        "box_id": box_id,
        "phones": phones,
        "telegram": telegram,
        "owners": phones | telegram,
        "store": store,
    }


def refuse_context(
    failure: GateFailure,
    *,
    approver: str = "",
    to_addr: str = "",
    from_account: str = "",
    subject: str = "",
    body: str = "",
) -> int:
    try:
        audit(
            paths(),
            box_id=resolve_box_id(),
            approver=approver,
            to_addr=to_addr,
            from_account=from_account,
            subject=subject,
            body=body,
            outcome=failure.outcome,
            reason=failure.reason,
            provider_called=False,
        )
    except Exception:
        pass
    payload = {
        "ok": False,
        "outcome": failure.outcome,
        "reason": failure.reason,
        "provider_called": False,
    }
    if failure.field:
        payload["field"] = failure.field
    payload.update(failure.extra)
    return emit(payload, failure.status)


def stage(
    approver_raw: str,
    to_raw: str,
    subject_raw: str,
    body_raw: str,
    from_account_raw: str,
    connected_account_raw: str,
    why_raw: str = "",
    source_kind_raw: str = "",
    source_date_raw: str = "",
    source_name_raw: str = "",
    source_ref_raw: str = "",
) -> int:
    approver = ""
    to_addr = ""
    from_account = ""
    subject = ""
    body = ""
    try:
        ctx = context()
        approver = resolve_approver(approver_raw, ctx["phones"], ctx["telegram"])
        to_addr = one_email(to_raw, "to")
        from_account = require_from_account(from_account_raw)
        connected_account = require_connected_account(connected_account_raw)
        subject = require_subject(subject_raw)
        body = require_body(body_raw)
        why_line, source_kind, source_date, source_ref = build_why_line(
            why_raw,
            source_kind_raw,
            source_date_raw,
            source_name_raw,
            source_ref_raw,
        )
        preview = body_preview(body)
        now = utc_now()
        with DraftLock(ctx["store"]["drafts"]):
            if pending_blocks(ctx["store"]["drafts"], now):
                raise GateFailure(
                    "refused_multi",
                    "a draft is already waiting for SEND; cancel it before staging another",
                )
            draft_id = os.urandom(8).hex()
            expires = now + draft_ttl()
            record = {
                "draft_id": draft_id,
                "status": "pending",
                "box_id": ctx["box_id"],
                "approver": approver,
                "to": to_addr,
                "from_account": from_account,
                "connected_account": connected_account,
                "subject": subject,
                "body": body,
                "body_hash": body_hash(body),
                "subject_hash": body_hash(subject),
                "attestation_version": ATTESTATION_VERSION,
                "why_line": why_line,
                "source_kind": source_kind,
                "source_date": source_date,
                "source_ref": source_ref,
                "created_at": iso(now),
                "expires_at": iso(expires),
            }
            write_draft(draft_path(ctx["store"]["drafts"], draft_id), record)
        shown = attestation_text(from_account, to_addr, subject, preview, why_line)
        return emit(
            {
                "ok": True,
                "outcome": "staged",
                "draft_id": draft_id,
                "to": to_addr,
                "from_account": from_account,
                "subject": subject,
                "body_len": len(body),
                "body_hash": record["body_hash"],
                "body_preview": preview,
                "attestation_version": ATTESTATION_VERSION,
                "source_kind": source_kind,
                "source_date": source_date,
                "why_line": why_line,
                "expires_at": record["expires_at"],
                "attestation": shown,
                "provider_called": False,
            },
            EXIT_OK,
        )
    except GateFailure as failure:
        return refuse_context(
            failure,
            approver=approver,
            to_addr=to_addr,
            from_account=from_account,
            subject=subject,
            body=body,
        )


def cancel_draft(directory: Path, draft_id: str, reason: str) -> dict | None:
    path = draft_path(directory, draft_id)
    if not path.exists():
        return None
    data = read_draft(path)
    original_body = str(data.get("body") or "")
    original_subject = str(data.get("subject") or "")
    if data.get("status") == "pending":
        data["status"] = "cancelled"
        data["cancelled_reason"] = reason
        data["body"] = ""
        data["subject"] = ""
        write_draft(path, data)
    data["body"] = original_body
    data["subject"] = original_subject
    return data


def send(draft_id: str, confirm: str, attest: str) -> int:
    ctx: dict = {}
    draft: dict = {}
    held_body = ""
    held_subject = ""
    try:
        ctx = context()
        with DraftLock(ctx["store"]["drafts"]):
            path = draft_path(ctx["store"]["drafts"], draft_id)
            if not path.exists():
                raise GateFailure("error", "draft was not found", field="draft_id", status=EXIT_ERROR)
            draft = read_draft(path)
            body = str(draft.get("body") or "")
            subject = str(draft.get("subject") or "")
            held_body = body
            held_subject = subject
            to_addr = str(draft.get("to") or "")
            from_account = str(draft.get("from_account") or "")
            connected_account = str(draft.get("connected_account") or "")
            approver = str(draft.get("approver") or "")
            status = str(draft.get("status") or "")
            if status == "sent":
                raise GateFailure(
                    "refused_duplicate",
                    "this draft was already sent",
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if status == "sending":
                raise GateFailure(
                    "error",
                    "send already started for this draft; not sending again",
                    status=EXIT_ERROR,
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if status != "pending":
                raise GateFailure(
                    "refused_no_confirm",
                    "this draft is not waiting for a confirm",
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if utc_now() >= parse_expiry(draft):
                draft["status"] = "cancelled"
                draft["cancelled_reason"] = "expired"
                draft["body"] = ""
                draft["subject"] = ""
                write_draft(path, draft)
                raise GateFailure(
                    "refused_no_confirm",
                    "confirmation window expired; stage the message again",
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if approver not in ctx["owners"] or draft.get("box_id") != ctx["box_id"]:
                raise GateFailure(
                    "refused_not_owner",
                    "draft owner or box no longer matches",
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if draft.get("attestation_version") != ATTESTATION_VERSION:
                raise GateFailure(
                    "error",
                    "draft attestation version is stale; stage the message again",
                    status=EXIT_ERROR,
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if not is_confirm(confirm):
                draft["status"] = "cancelled"
                draft["cancelled_reason"] = "confirm was not SEND"
                draft["body"] = ""
                draft["subject"] = ""
                write_draft(path, draft)
                raise GateFailure(
                    "refused_no_confirm",
                    "confirm was not SEND; the draft is cancelled",
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if not is_attest(attest):
                raise GateFailure(
                    "refused_no_attestation",
                    "attestation was not accepted; not sending",
                    field="attest",
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            if not body or not subject or len(body) > DEFAULT_MAX_BODY_CHARS:
                raise GateFailure(
                    "error",
                    "staged message is no longer sendable as one email",
                    status=EXIT_ERROR,
                    extra={"draft_id": draft_id, "to": to_addr},
                )
            draft["status"] = "sending"
            write_draft(path, draft)
            approved_at = iso(utc_now())
            try:
                result = deliver(to_addr, subject, body, from_account, connected_account)
            except Exception as exc:
                result = {
                    "success": False,
                    "message_id": "",
                    "provider_status": "error",
                    "provider_called": True,
                    "error": exc.__class__.__name__,
                }
            provider_called = bool(result.get("provider_called"))
            message_id = str(result.get("message_id") or "")
            if result.get("success") and not message_id:
                result = {
                    "success": False,
                    "message_id": "",
                    "provider_status": result.get("provider_status") or "accepted",
                    "provider_called": True,
                    "error": "provider returned no message id; this draft will not be retried",
                }
                provider_called = True
            if result.get("success"):
                draft["status"] = "sent"
                draft["provider_message_id"] = message_id
                draft["approved_at"] = approved_at
                draft["body"] = ""
                draft["subject"] = ""
                write_draft(path, draft)
                audit(
                    ctx["store"],
                    box_id=ctx["box_id"],
                    approver=approver,
                    to_addr=to_addr,
                    from_account=from_account,
                    subject=subject,
                    body=body,
                    source_kind=str(draft.get("source_kind") or ""),
                    outcome="sent",
                    reason="provider accepted",
                    approved_at=approved_at,
                    draft_id=draft_id,
                    provider_message_id=message_id,
                    provider_status=result.get("provider_status") or "accepted",
                    provider_called=True,
                )
                return emit(
                    {
                        "ok": True,
                        "outcome": "sent",
                        "reason": "provider accepted",
                        "draft_id": draft_id,
                        "to": to_addr,
                        "from_account": from_account,
                        "subject": subject,
                        "provider_message_id": message_id,
                        "provider_status": result.get("provider_status") or "accepted",
                        "provider_called": True,
                    },
                    EXIT_OK,
                )
            draft["status"] = "error"
            draft["provider_error"] = redact(str(result.get("error") or "provider rejected the send"))
            draft["body"] = ""
            draft["subject"] = ""
            write_draft(path, draft)
            reason = str(result.get("error") or "provider rejected the send")
            audit(
                ctx["store"],
                box_id=ctx["box_id"],
                approver=approver,
                to_addr=to_addr,
                from_account=from_account,
                subject=subject,
                body=body,
                source_kind=str(draft.get("source_kind") or ""),
                outcome="error",
                reason=reason,
                approved_at=approved_at,
                draft_id=draft_id,
                provider_message_id=result.get("message_id") or None,
                provider_status=result.get("provider_status") or "error",
                provider_called=provider_called,
            )
            payload = {
                "ok": False,
                "outcome": "error",
                "reason": redact(reason),
                "draft_id": draft_id,
                "to": to_addr,
                "from_account": from_account,
                "provider_status": result.get("provider_status") or "error",
                "provider_called": provider_called,
            }
            if result.get("field"):
                payload["field"] = result["field"]
            return emit(payload, EXIT_ERROR)
    except GateFailure as failure:
        approver = str(draft.get("approver") or "")
        to_addr = str(draft.get("to") or "")
        from_account = str(draft.get("from_account") or "")
        body = held_body or str(draft.get("body") or "")
        subject = held_subject or str(draft.get("subject") or "")
        box_id = str(ctx.get("box_id") or resolve_box_id())
        try:
            audit(
                ctx.get("store") or paths(),
                box_id=box_id,
                approver=approver,
                to_addr=to_addr,
                from_account=from_account,
                subject=subject,
                body=body,
                source_kind=str(draft.get("source_kind") or ""),
                outcome=failure.outcome,
                reason=failure.reason,
                draft_id=draft_id,
                provider_called=False,
            )
        except Exception:
            pass
        payload = {
            "ok": False,
            "outcome": failure.outcome,
            "reason": failure.reason,
            "provider_called": False,
            "draft_id": draft_id,
        }
        if failure.field:
            payload["field"] = failure.field
        payload.update(failure.extra)
        return emit(payload, failure.status)


def cancel(draft_id: str) -> int:
    try:
        ctx = context()
        with DraftLock(ctx["store"]["drafts"]):
            path = draft_path(ctx["store"]["drafts"], draft_id)
            if not path.exists():
                raise GateFailure("error", "draft was not found", field="draft_id", status=EXIT_ERROR)
            current = read_draft(path)
            if current.get("status") != "pending":
                raise GateFailure(
                    "refused_no_confirm",
                    "this draft is not waiting for a confirm",
                    extra={"draft_id": draft_id},
                )
            data = cancel_draft(ctx["store"]["drafts"], draft_id, "owner cancelled")
        if data is None:
            raise GateFailure("error", "draft was not found", field="draft_id", status=EXIT_ERROR)
        audit(
            ctx["store"],
            box_id=ctx["box_id"],
            approver=str(data.get("approver") or ""),
            to_addr=str(data.get("to") or ""),
            from_account=str(data.get("from_account") or ""),
            subject=str(data.get("subject") or ""),
            body=str(data.get("body") or ""),
            source_kind=str(data.get("source_kind") or ""),
            outcome="refused_no_confirm",
            reason="owner cancelled",
            draft_id=draft_id,
            provider_called=False,
        )
        return emit(
            {
                "ok": True,
                "outcome": "cancelled",
                "reason": "owner cancelled",
                "draft_id": draft_id,
                "provider_called": False,
            },
            EXIT_OK,
        )
    except GateFailure as failure:
        return refuse_context(failure)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="email_send_confirmed",
        description="Stage and send one owner-confirmed Gmail message.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    stage_cmd = sub.add_parser("stage", help="Record one draft. Does not send.")
    stage_cmd.add_argument("--approver", required=True)
    stage_cmd.add_argument("--to", required=True)
    stage_cmd.add_argument("--subject", required=True)
    stage_cmd.add_argument("--body", required=True)
    stage_cmd.add_argument("--from-account", required=True)
    stage_cmd.add_argument("--connected-account", required=True)
    # Missing Why args are refused in stage() as refused_no_why, not by argparse.
    stage_cmd.add_argument("--why", default="")
    stage_cmd.add_argument("--source-kind", default="")
    stage_cmd.add_argument("--source-date", default="")
    stage_cmd.add_argument("--source-name", default="")
    stage_cmd.add_argument("--source-ref", default="")

    send_cmd = sub.add_parser("send", help="Send one staged draft after SEND and attestation.")
    send_cmd.add_argument("--draft-id", required=True)
    send_cmd.add_argument("--confirm", required=True)
    send_cmd.add_argument("--attest", required=True)

    cancel_cmd = sub.add_parser("cancel", help="Cancel one staged draft. Does not send.")
    cancel_cmd.add_argument("--draft-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "stage":
        return stage(
            args.approver,
            args.to,
            args.subject,
            args.body,
            args.from_account,
            args.connected_account,
            args.why,
            args.source_kind,
            args.source_date,
            args.source_name,
            args.source_ref,
        )
    if args.cmd == "send":
        return send(args.draft_id, args.confirm, args.attest)
    if args.cmd == "cancel":
        return cancel(args.draft_id)
    return emit({"ok": False, "outcome": "error", "reason": "unknown command", "provider_called": False}, EXIT_ERROR)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(EXIT_ERROR)
