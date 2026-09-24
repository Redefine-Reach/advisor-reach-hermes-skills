#!/usr/bin/env python3
"""Owner-confirmed third-party SMS (RED-390 PR1).

One staged draft plus one explicit confirm becomes one send through the
existing Hermes Telnyx adapter (``hermes send --to telnyx_sms:<E.164>``),
which is ``team-telnyx/telnyx-hermes-sms`` @ a7d209f on the box
(``TelnyxSmsAdapter.send(chat_id=E.164)``, From = ``TELNYX_SMS_FROM_NUMBER``).

This script does not talk to Telnyx itself and does not accept a From override.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

ATTESTATION_VERSION = "red-390-v1"
SPIKE_BOX_ID = "advisor-reach-internal"
DEFAULT_MAX_BODY_CHARS = 640
DEFAULT_DRAFT_TTL_SECONDS = 1800
CONFIRM_TOKENS = frozenset({"send", "/approve"})
ATTEST_YES = frozenset({"yes", "y", "true", "1"})
CRON_ENVS = (
    "HERMES_CRON_JOB_ID",
    "HERMES_CRON_JOB_NAME",
    "HERMES_CRON_AUTO_DELIVER_PLATFORM",
    "HERMES_CRON_AUTO_DELIVER_CHAT_ID",
)
AUDIT_KEYS = (
    "ts",
    "box_id",
    "approver",
    "approved_at",
    "attestation_version",
    "dest",
    "from",
    "body_hash",
    "body_len",
    "telnyx_message_id",
    "provider_status",
    "outcome",
    "reason",
    "draft_id",
    "provider_called",
)
POD_NAME = re.compile(r"^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)-\d+$")
E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
PHONE_CHARS = re.compile(r"^[\d+\s().-]+$")
MULTI_DEST = re.compile(r"[,;\n|&]|\band\b", re.IGNORECASE)
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
    return datetime.now(timezone.utc)


def iso(when: datetime) -> str:
    return when.isoformat()


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def attestation_text(from_number: str, dest: str, body: str) -> str:
    return (
        f"You're about to send this text from ARIN's number ({from_number}) to {dest}.\n"
        f"{body}\n"
        "Reply SEND to confirm you authorize this one message and that the recipient may receive it.\n"
        "Reply anything else to cancel. Carrier STOP still works for them."
    )


def classify_phone(raw: str) -> tuple[str, str | None]:
    """Return ``(ok|multi|invalid, e164)`` for one destination or approver."""
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
            "MoO lists, nurture, and any multi-recipient send are refused. Name one person.",
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
    audit = Path(env.get("SMS_AUDIT_PATH", "/opt/data/audit/sms-outbound.jsonl"))
    opt_out = Path(env.get("SMS_OPT_OUT_FILE", "/opt/data/audit/sms-opt-out.txt"))
    drafts = Path(env.get("SMS_DRAFT_DIR", "/opt/data/audit/sms-drafts"))
    return {"audit": audit, "opt_out": opt_out, "drafts": drafts}


def max_body_chars(environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    raw = str(env.get("SMS_MAX_BODY_CHARS", str(DEFAULT_MAX_BODY_CHARS))).strip()
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_MAX_BODY_CHARS
    if parsed < 1:
        return DEFAULT_MAX_BODY_CHARS
    return min(parsed, DEFAULT_MAX_BODY_CHARS)


def draft_ttl(environ: Mapping[str, str] | None = None) -> timedelta:
    env = os.environ if environ is None else environ
    raw = str(env.get("SMS_DRAFT_TTL_SECONDS", str(DEFAULT_DRAFT_TTL_SECONDS))).strip()
    try:
        seconds = int(raw)
    except ValueError:
        seconds = DEFAULT_DRAFT_TTL_SECONDS
    return timedelta(seconds=max(0, seconds))


def allowlist(environ: Mapping[str, str] | None = None) -> set[str]:
    env = os.environ if environ is None else environ
    if truthy(env.get("TELNYX_SMS_ALLOW_ALL_USERS")):
        raise GateFailure(
            "refused_autonomous",
            "TELNYX_SMS_ALLOW_ALL_USERS is set; third-party send stays closed",
        )
    raw = str(env.get("TELNYX_SMS_ALLOWED_USERS", "")).strip()
    if not raw:
        raise GateFailure(
            "refused_not_owner",
            "owner allowlist is empty; refusing third-party send",
        )
    owners: set[str] = set()
    for part in raw.split(","):
        if not part.strip():
            continue
        number = require_phone(part, "approver")
        owners.add(number)
    if not owners:
        raise GateFailure(
            "refused_not_owner",
            "owner allowlist is empty; refusing third-party send",
        )
    return owners


def from_number(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = str(env.get("TELNYX_SMS_FROM_NUMBER", "")).strip()
    if not raw:
        raise GateFailure(
            "error",
            "TELNYX_SMS_FROM_NUMBER is not set; not sending",
            field="from",
            status=EXIT_ERROR,
        )
    return require_phone(raw, "from")


def assert_spike_box(box_id: str) -> None:
    if box_id != SPIKE_BOX_ID:
        raise GateFailure(
            "refused_spike_box",
            f"third-party SMS is enabled only on {SPIKE_BOX_ID}",
        )


def assert_not_cron(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    for name in CRON_ENVS:
        if str(env.get(name, "")).strip():
            raise GateFailure(
                "refused_autonomous",
                "scheduled and standing jobs cannot send a third-party SMS",
            )


def load_opt_outs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateFailure(
            "error",
            f"opt-out list is unreadable ({exc.__class__.__name__}); not sending",
            status=EXIT_ERROR,
        ) from exc
    denied: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        kind, number = classify_phone(entry)
        if kind != "ok" or not number:
            raise GateFailure(
                "error",
                f"opt-out list line {line_no} is not one E.164 number; not sending",
                status=EXIT_ERROR,
            )
        denied.add(number)
    return denied


def assert_not_opted_out(dest: str, path: Path) -> None:
    if dest in load_opt_outs(path):
        raise GateFailure(
            "refused_stop",
            f"{dest} is on the local opt-out list; not sending",
        )


def append_audit(path: Path, record: dict) -> None:
    if "body" in record or "text" in record:
        raise RuntimeError("audit record must not contain the message body")
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
    dest: str,
    from_number_value: str,
    body: str,
    outcome: str,
    reason: str,
    approved_at: str | None = None,
    draft_id: str | None = None,
    telnyx_message_id: str | None = None,
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
            "dest": dest,
            "from": from_number_value,
            "body_hash": body_hash(body) if body else "",
            "body_len": len(body),
            "telnyx_message_id": telnyx_message_id,
            "provider_status": provider_status,
            "outcome": outcome,
            "reason": reason.replace("\n", " ")[:500],
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
            "another SMS confirm is in progress; not sending",
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


def build_hermes_argv(dest: str, body_file: str, environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    binary = str(env.get("HERMES_BIN", "hermes")).strip() or "hermes"
    return [
        binary,
        "send",
        "--to",
        f"telnyx_sms:{dest}",
        "--json",
        "--file",
        body_file,
    ]


def parse_provider_stdout(stdout: str, stderr: str, code: int) -> dict:
    payload: dict = {}
    raw = stdout.strip()
    if raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            loaded = None
            if start >= 0 and end > start:
                try:
                    loaded = json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    loaded = None
        if isinstance(loaded, dict):
            payload = loaded
    if payload.get("success") and not payload.get("error") and not payload.get("skipped"):
        return {
            "success": True,
            "message_id": str(payload.get("message_id") or ""),
            "provider_status": str(payload.get("provider_status") or "accepted"),
            "error": "",
        }
    error = payload.get("error") or stderr.strip() or f"send exit {code}"
    return {
        "success": False,
        "message_id": str(payload.get("message_id") or ""),
        "provider_status": str(payload.get("provider_status") or "error"),
        "error": str(error).replace("\n", " ")[:500],
    }


def deliver(dest: str, body: str) -> dict:
    """One adapter send. Test mode never falls through to Hermes."""
    if os.environ.get("SMS_SEND_CONFIRMED_TEST") == "1":
        transport = os.environ.get("SMS_SEND_TRANSPORT", "").strip()
        if not transport:
            return {
                "success": False,
                "message_id": "",
                "provider_status": "error",
                "error": "test mode has no transport",
            }
        proc = subprocess.run(
            [transport],
            input=json.dumps({"to": dest, "text": body}),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return parse_provider_stdout(proc.stdout, proc.stderr, proc.returncode)

    fd = -1
    body_file = ""
    try:
        fd, body_file = tempfile.mkstemp(prefix="sms-body-", suffix=".txt")
        os.write(fd, body.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        proc = subprocess.run(
            build_hermes_argv(dest, body_file),
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        return parse_provider_stdout(proc.stdout, proc.stderr, proc.returncode)
    except FileNotFoundError:
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "error": "hermes send is not available",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message_id": "",
            "provider_status": "error",
            "error": "hermes send timed out; this draft will not be retried",
        }
    finally:
        if fd >= 0:
            os.close(fd)
        if body_file and os.path.exists(body_file):
            os.unlink(body_file)


def emit(payload: dict, status: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return status


def context() -> dict:
    box_id = resolve_box_id()
    assert_spike_box(box_id)
    assert_not_cron()
    owners = allowlist()
    sender = from_number()
    store = paths()
    return {"box_id": box_id, "owners": owners, "from": sender, "store": store}


def refuse_context(failure: GateFailure, *, approver: str = "", dest: str = "", body: str = "") -> int:
    """Best-effort audit when the gate fails before or without a provider call."""
    try:
        box_id = resolve_box_id()
        sender = ""
        try:
            sender = from_number()
        except GateFailure:
            sender = ""
        audit(
            paths(),
            box_id=box_id,
            approver=approver,
            dest=dest,
            from_number_value=sender,
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


def stage(approver_raw: str, dest_raw: str, body_raw: str) -> int:
    try:
        ctx = context()
        approver = require_phone(approver_raw, "approver")
        if approver not in ctx["owners"]:
            raise GateFailure(
                "refused_not_owner",
                "approver is not an allowlisted owner of this box",
                field="approver",
            )
        dest = require_phone(dest_raw, "dest")
        if dest == approver or dest == ctx["from"]:
            raise GateFailure(
                "refused_not_third_party",
                "that number is the owner thread or the box number; reply normally",
                field="dest",
            )
        body = str(body_raw or "").strip()
        limit = max_body_chars()
        if not body:
            raise GateFailure("error", "body is empty", field="body", status=EXIT_ERROR)
        if len(body) > limit:
            raise GateFailure(
                "refused_multi",
                f"body is {len(body)} characters; the limit is {limit} so one confirm stays one send",
                field="body",
            )
        assert_not_opted_out(dest, ctx["store"]["opt_out"])
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
                "dest": dest,
                "from": ctx["from"],
                "body": body,
                "body_hash": body_hash(body),
                "attestation_version": ATTESTATION_VERSION,
                "created_at": iso(now),
                "expires_at": iso(expires),
            }
            write_draft(draft_path(ctx["store"]["drafts"], draft_id), record)
        shown = attestation_text(ctx["from"], dest, body)
        return emit(
            {
                "ok": True,
                "outcome": "staged",
                "draft_id": draft_id,
                "dest": dest,
                "from": ctx["from"],
                "body_len": len(body),
                "body_hash": record["body_hash"],
                "attestation_version": ATTESTATION_VERSION,
                "expires_at": record["expires_at"],
                "attestation": shown,
                "provider_called": False,
            },
            EXIT_OK,
        )
    except GateFailure as failure:
        approver = ""
        dest = ""
        body = str(body_raw or "").strip()
        kind, number = classify_phone(approver_raw)
        if kind == "ok" and number:
            approver = number
        kind, number = classify_phone(dest_raw)
        if kind == "ok" and number:
            dest = number
        return refuse_context(failure, approver=approver, dest=dest, body=body)


def cancel_draft(directory: Path, draft_id: str, reason: str) -> dict | None:
    path = draft_path(directory, draft_id)
    if not path.exists():
        return None
    data = read_draft(path)
    original_body = str(data.get("body") or "")
    if data.get("status") == "pending":
        data["status"] = "cancelled"
        data["cancelled_reason"] = reason
        data["body"] = ""
        write_draft(path, data)
    data["body"] = original_body
    return data


def send(draft_id: str, confirm: str, attest: str) -> int:
    ctx: dict = {}
    draft: dict = {}
    held_body = ""
    try:
        ctx = context()
        with DraftLock(ctx["store"]["drafts"]):
            path = draft_path(ctx["store"]["drafts"], draft_id)
            if not path.exists():
                raise GateFailure("error", "draft was not found", field="draft_id", status=EXIT_ERROR)
            draft = read_draft(path)
            body = str(draft.get("body") or "")
            held_body = body
            dest = str(draft.get("dest") or "")
            approver = str(draft.get("approver") or "")
            status = str(draft.get("status") or "")
            if status == "sent":
                raise GateFailure(
                    "refused_duplicate",
                    "this draft was already sent",
                    extra={"draft_id": draft_id, "dest": dest},
                )
            if status == "sending":
                raise GateFailure(
                    "error",
                    "send already started for this draft; not sending again",
                    status=EXIT_ERROR,
                    extra={"draft_id": draft_id, "dest": dest},
                )
            if status != "pending":
                raise GateFailure(
                    "refused_no_confirm",
                    "this draft is not waiting for a confirm",
                    extra={"draft_id": draft_id, "dest": dest},
                )
            if utc_now() >= parse_expiry(draft):
                draft["status"] = "cancelled"
                draft["cancelled_reason"] = "expired"
                draft["body"] = ""
                write_draft(path, draft)
                raise GateFailure(
                    "refused_no_confirm",
                    "confirmation window expired; stage the message again",
                    extra={"draft_id": draft_id, "dest": dest},
                )
            if approver not in ctx["owners"] or draft.get("from") != ctx["from"]:
                raise GateFailure(
                    "refused_not_owner",
                    "draft owner or From no longer matches this box",
                    extra={"draft_id": draft_id, "dest": dest},
                )
            if not is_confirm(confirm):
                draft["status"] = "cancelled"
                draft["cancelled_reason"] = "confirm was not SEND"
                draft["body"] = ""
                write_draft(path, draft)
                raise GateFailure(
                    "refused_no_confirm",
                    "confirm was not SEND; the draft is cancelled",
                    extra={"draft_id": draft_id, "dest": dest},
                )
            if not is_attest(attest):
                raise GateFailure(
                    "refused_no_attestation",
                    "attestation was not accepted; not sending",
                    field="attest",
                    extra={"draft_id": draft_id, "dest": dest},
                )
            assert_not_opted_out(dest, ctx["store"]["opt_out"])
            if len(body) > max_body_chars() or not body:
                raise GateFailure(
                    "error",
                    "staged body is no longer sendable as one message",
                    status=EXIT_ERROR,
                    extra={"draft_id": draft_id, "dest": dest},
                )
            draft["status"] = "sending"
            write_draft(path, draft)
            approved_at = iso(utc_now())
            try:
                result = deliver(dest, body)
            except Exception as exc:
                result = {
                    "success": False,
                    "message_id": "",
                    "provider_status": "error",
                    "error": exc.__class__.__name__,
                }
            provider_called = True
            if result.get("success"):
                message_id = str(result.get("message_id") or "")
                if not message_id:
                    result = {
                        "success": False,
                        "message_id": "",
                        "provider_status": result.get("provider_status") or "accepted",
                        "error": "provider returned no message id; this draft will not be retried",
                    }
                else:
                    draft["status"] = "sent"
                    draft["telnyx_message_id"] = message_id
                    draft["approved_at"] = approved_at
                    draft["body"] = ""
                    write_draft(path, draft)
                    audit(
                        ctx["store"],
                        box_id=ctx["box_id"],
                        approver=approver,
                        dest=dest,
                        from_number_value=ctx["from"],
                        body=body,
                        outcome="sent",
                        reason="provider accepted",
                        approved_at=approved_at,
                        draft_id=draft_id,
                        telnyx_message_id=message_id,
                        provider_status=result.get("provider_status") or "accepted",
                        provider_called=True,
                    )
                    return emit(
                        {
                            "ok": True,
                            "outcome": "sent",
                            "reason": "provider accepted",
                            "draft_id": draft_id,
                            "dest": dest,
                            "from": ctx["from"],
                            "telnyx_message_id": message_id,
                            "provider_status": result.get("provider_status") or "accepted",
                            "provider_called": True,
                        },
                        EXIT_OK,
                    )
            draft["status"] = "error"
            draft["provider_error"] = result.get("error") or "provider rejected the send"
            draft["body"] = ""
            write_draft(path, draft)
            reason = str(result.get("error") or "provider rejected the send")
            audit(
                ctx["store"],
                box_id=ctx["box_id"],
                approver=approver,
                dest=dest,
                from_number_value=ctx["from"],
                body=body,
                outcome="error",
                reason=reason,
                approved_at=approved_at,
                draft_id=draft_id,
                telnyx_message_id=result.get("message_id") or None,
                provider_status=result.get("provider_status") or "error",
                provider_called=provider_called,
            )
            return emit(
                {
                    "ok": False,
                    "outcome": "error",
                    "reason": reason,
                    "draft_id": draft_id,
                    "dest": dest,
                    "from": ctx["from"],
                    "provider_status": result.get("provider_status") or "error",
                    "provider_called": True,
                },
                EXIT_ERROR,
            )
    except GateFailure as failure:
        approver = str(draft.get("approver") or "")
        dest = str(draft.get("dest") or "")
        body = held_body or str(draft.get("body") or "")
        sender = str(ctx.get("from") or "")
        box_id = str(ctx.get("box_id") or resolve_box_id())
        try:
            audit(
                ctx.get("store") or paths(),
                box_id=box_id,
                approver=approver,
                dest=dest,
                from_number_value=sender,
                body=body,
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
            data = cancel_draft(ctx["store"]["drafts"], draft_id, "owner cancelled")
        if data is None:
            raise GateFailure("error", "draft was not found", field="draft_id", status=EXIT_ERROR)
        audit(
            ctx["store"],
            box_id=ctx["box_id"],
            approver=str(data.get("approver") or ""),
            dest=str(data.get("dest") or ""),
            from_number_value=ctx["from"],
            body=str(data.get("body") or ""),
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


def deny(approver_raw: str, dest_raw: str) -> int:
    try:
        ctx = context()
        approver = require_phone(approver_raw, "approver")
        if approver not in ctx["owners"]:
            raise GateFailure(
                "refused_not_owner",
                "approver is not an allowlisted owner of this box",
                field="approver",
            )
        dest = require_phone(dest_raw, "dest")
        path = ctx["store"]["opt_out"]
        existing = load_opt_outs(path)
        if dest not in existing:
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, (dest + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        outcome = "already_opted_out" if dest in existing else "opt_out_recorded"
        audit(
            ctx["store"],
            box_id=ctx["box_id"],
            approver=approver,
            dest=dest,
            from_number_value=ctx["from"],
            body="",
            outcome=outcome,
            reason="local opt-out list updated" if outcome == "opt_out_recorded" else "already listed",
            provider_called=False,
        )
        return emit(
            {
                "ok": True,
                "outcome": outcome,
                "dest": dest,
                "provider_called": False,
            },
            EXIT_OK,
        )
    except GateFailure as failure:
        approver = ""
        dest = ""
        kind, number = classify_phone(approver_raw)
        if kind == "ok" and number:
            approver = number
        kind, number = classify_phone(dest_raw)
        if kind == "ok" and number:
            dest = number
        return refuse_context(failure, approver=approver, dest=dest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sms_send_confirmed",
        description="Stage and send one owner-confirmed third-party SMS.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    stage_cmd = sub.add_parser("stage", help="Record one draft. Does not send.")
    stage_cmd.add_argument("--approver", required=True)
    stage_cmd.add_argument("--dest", required=True)
    stage_cmd.add_argument("--body", required=True)

    send_cmd = sub.add_parser("send", help="Send one staged draft after SEND and attestation.")
    send_cmd.add_argument("--draft-id", required=True)
    send_cmd.add_argument("--confirm", required=True)
    send_cmd.add_argument("--attest", required=True)

    cancel_cmd = sub.add_parser("cancel", help="Cancel one staged draft. Does not send.")
    cancel_cmd.add_argument("--draft-id", required=True)

    deny_cmd = sub.add_parser("deny", help="Add one number to the local opt-out list. Does not send.")
    deny_cmd.add_argument("--approver", required=True)
    deny_cmd.add_argument("--dest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "stage":
        return stage(args.approver, args.dest, args.body)
    if args.cmd == "send":
        return send(args.draft_id, args.confirm, args.attest)
    if args.cmd == "cancel":
        return cancel(args.draft_id)
    if args.cmd == "deny":
        return deny(args.approver, args.dest)
    return emit({"ok": False, "outcome": "error", "reason": "unknown command"}, EXIT_ERROR)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(EXIT_ERROR)
