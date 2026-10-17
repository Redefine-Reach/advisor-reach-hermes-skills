#!/usr/bin/env python3
"""Redact sensitive spans from session text before eval export (fail-closed)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

REDACTION_VERSION = "2.0.0"

PLACEHOLDER_PHONE = "[REDACTED_PHONE]"
PLACEHOLDER_SSN = "[REDACTED_SSN]"
PLACEHOLDER_EMAIL = "[REDACTED_EMAIL]"
PLACEHOLDER_ADDRESS = "[REDACTED_ADDRESS]"
PLACEHOLDER_ACCOUNT = "[REDACTED_ACCOUNT]"
PLACEHOLDER_CARD = "[REDACTED_CARD]"
PLACEHOLDER_EIN = "[REDACTED_EIN]"
PLACEHOLDER_LOAN = "[REDACTED_LOAN]"
PLACEHOLDER_ROUTING = "[REDACTED_ROUTING]"
PLACEHOLDER_DOB = "[REDACTED_DOB]"
PLACEHOLDER_URL = "[REDACTED_URL]"
PLACEHOLDER_CODE = "[REDACTED_CODE]"
PLACEHOLDER_HEALTH = "[REDACTED_HEALTH]"
PLACEHOLDER_LEGAL = "[REDACTED_LEGAL]"
PLACEHOLDER_KEY = "[REDACTED_KEY]"
PLACEHOLDER_DIGITS = "[REDACTED_DIGITS]"

# --- Primary detectors (redaction pass) ---

_RE_SSN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_RE_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+",
    re.IGNORECASE,
)
_RE_DRIVE = re.compile(
    r"\b(?:https?://)?(?:drive\.google\.com|docs\.google\.com)/[^\s]+",
    re.IGNORECASE,
)
_RE_LISTING = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:zillow|redfin|realtor)\.com/[^\s]+",
    re.IGNORECASE,
)
_RE_PHONE_7 = re.compile(r"\b\d{3}-\d{4}\b")
_RE_PHONE_10 = re.compile(
    r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
)
_RE_PHONE_E164 = re.compile(r"\+\d{10,15}\b")
_RE_STREET = re.compile(
    r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,3}\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place)\b\.?",
    re.IGNORECASE,
)
_RE_CITY_STATE_ZIP = re.compile(
    r"\b[A-Za-z][A-Za-z .\-]{2,30},\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b",
)
_RE_POBOX = re.compile(r"\bP\.?\s*O\.?\s*Box\s+\d+\b", re.IGNORECASE)
_RE_ACCOUNT_PHRASE = re.compile(
    r"\b(?:account\s*(?:number|#|no\.?)|acct\.?\s*#?)\s*[:#]?\s*(\d{4,17})\b",
    re.IGNORECASE,
)
_RE_CHECKING_ENDING = re.compile(
    r"\bchecking\s+ending\s+(\d{4})\b",
    re.IGNORECASE,
)
_RE_CARD_SPACED = re.compile(r"\b(?:\d{4}\s+){3}\d{4}\b")
_RE_EIN = re.compile(r"\b\d{2}-\d{7}\b")
_RE_LOAN = re.compile(r"\bloan\s+(\d{4}-\d{2})\b", re.IGNORECASE)
_RE_LOAN_BARE = re.compile(r"\b\d{4}-\d{2}\b")
_RE_ROUTING = re.compile(r"\b(?:routing|aba)\s*(?:#|number)?\s*[:#]?\s*(\d{9})\b", re.IGNORECASE)
_RE_ROUTING_BARE = re.compile(r"\b\d{9}\b")
_RE_DOB_LABEL = re.compile(
    r"\b(?:DOB|D\.O\.B\.|date of birth|born(?:\s+on)?)\s*[:#]?\s*"
    r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2}|"
    r"[A-Za-z]+\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_RE_DOB_BARE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])[/.-](?:0?[1-9]|[12]\d|3[01])[/.-](?:\d{2}|\d{4})\b",
)
_RE_CODE = re.compile(
    r"\b(?:lockbox|gate|door|garage|alarm)\s+(?:code|pin|#)?(?:\s+is)?\s*[:#]?\s*(\d{3,8})\b",
    re.IGNORECASE,
)
_RE_HEALTH = re.compile(
    r"\b(?:"
    r"knee surgery|hip replacement|had surgery|underwent surgery|surgery for|"
    r"has cancer|diagnosed with cancer|cancer treatment|chemotherapy|chemo\b|"
    r"\btherapy\b|in therapy|seeing a therapist|therapy for|mental health therapy|"
    r"diagnosis of|diagnosed with|medication for|taking medication|"
    r"hospital stay|hospitalized|admitted to the hospital|"
    r"diabetes|type 2 diabetes|anxiety disorder|bipolar disorder|"
    r"patient has|treatment for"
    r")\b[^.\n]{0,100}",
    re.IGNORECASE,
)
_RE_LEGAL = re.compile(
    r"\b(?:"
    r"divorce attorney|family law attorney|\bcustody\b|custody battle|child custody|"
    r"filing for divorce|divorce proceedings|"
    r"lawsuit against|pending lawsuit|sued for|"
    r"bankruptcy filing|filed bankruptcy|chapter 7|chapter 11|"
    r"subpoena|probate court|restraining order|"
    r"my attorney|their lawyer"
    r")\b[^.\n]{0,100}",
    re.IGNORECASE,
)
_RE_NAME_CUE = re.compile(
    r"(?:\b(?:my|our)\s+client\s+)([A-Z][a-z]+(?:\s+[A-Z]\.?)?)",
)
_RE_NAME_TITLE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?)",
)
_RE_NAME_MEETING = re.compile(
    r"\bmeeting with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)
_RE_NAME_CALL = re.compile(r"\bcall\s+([A-Z][a-z]+)\b")
_RE_NAME_NICK = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z])\.(?=\s|$)")
_RE_DIGITS_LONG = re.compile(r"\b\d{9,17}\b")

_SENSITIVE_KEY = re.compile(
    r"(?:ssn|social|email|e-mail|phone|mobile|address|street|dob|birth|password|"
    r"token|secret|account|routing|card|ein|loan|lockbox|gate|alarm|garage)",
    re.IGNORECASE,
)

_FORGET_TOPIC = re.compile(r"(?:^|\s)/new\b", re.IGNORECASE)
_FORGET_CMD = re.compile(
    r"\b(?:forget(?:\s+this|\s+that)?|do not keep|don't keep|donotkeep)\b",
    re.IGNORECASE,
)
_MINOR = re.compile(
    r"\b(?:minor\b|under\s+18|(?:\d{1,2})[- ]year[- ]old\s+child|my\s+(?:son|daughter)\s+who\s+is\s+\d{1,2})\b",
    re.IGNORECASE,
)

# --- Secondary residue detectors (independent patterns; must not import primary regex) ---

_RES_SSN = re.compile(r"\d{3}[-\s]?\d{2}[-\s]?\d{4}")
_RES_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RES_PHONE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\d{3}-\d{4}|\+1\d{10}",
)
_RES_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_RES_STREET = re.compile(
    r"\d{1,5}\s+\w+\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pl)\b",
    re.IGNORECASE,
)
_RES_ACCOUNT = re.compile(r"(?:account|acct).{0,12}\d{4,}", re.IGNORECASE)
_RES_CARD = re.compile(r"\d{4}\s+\d{4}\s+\d{4}\s+\d{4}")
_RES_EIN = re.compile(r"\d{2}-\d{7}")
_RES_HEALTH = re.compile(
    r"\b(?:cancer|chemo|therapy|surgery|diabetes|anxiety|hospital|medication|diagnos)",
    re.IGNORECASE,
)
_RES_LEGAL = re.compile(
    r"\b(?:divorce|custody|attorney|lawsuit|bankruptcy|subpoena|probate|restraining)",
    re.IGNORECASE,
)
_RES_DOB = re.compile(
    r"(?:DOB|born|date of birth).{0,10}\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}",
    re.IGNORECASE,
)
_RES_CODE = re.compile(
    r"(?:lockbox|gate|alarm|garage|door).{0,16}\d{3,8}",
    re.IGNORECASE,
)
_RES_NAME = re.compile(
    r"(?:client\s+[A-Z][a-z]+|Mr\.?\s+[A-Z][a-z]+|meeting with\s+[A-Z][a-z]+|"
    r"[A-Z][a-z]+\s+[A-Z]\.(?:\s|$))",
)
_RES_CLIENT_TAG = re.compile(r"\bCLIENT_\d+\b")

_RESIDUE_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (_RES_SSN, "ssn"),
    (_RES_EMAIL, "email"),
    (_RES_PHONE, "phone"),
    (_RES_URL, "url"),
    (_RES_STREET, "address"),
    (_RES_ACCOUNT, "account"),
    (_RES_CARD, "card"),
    (_RES_EIN, "ein"),
    (_RES_HEALTH, "health"),
    (_RES_LEGAL, "legal"),
    (_RES_DOB, "dob"),
    (_RES_CODE, "code"),
    (_RES_NAME, "name"),
]


class RedactionError(Exception):
    """Fail-closed redaction failure."""


class UnsupportedFieldType(RedactionError):
    pass


@dataclass
class RedactionContext:
    known_names: list[str] = field(default_factory=list)
    _name_map: dict[str, str] = field(default_factory=dict)
    _name_counter: int = 0
    class_counts: dict[str, int] = field(default_factory=dict)

    def placeholder_name(self, raw: str) -> str:
        key = raw.strip().lower()
        if key not in self._name_map:
            self._name_counter += 1
            self._name_map[key] = f"CLIENT_{self._name_counter}"
        return self._name_map[key]

    def bump(self, code: str, n: int = 1) -> None:
        self.class_counts[code] = self.class_counts.get(code, 0) + n


def _norm_tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    cleaned = re.sub(r"[^\w\s]", " ", folded)
    return [t for t in cleaned.split() if t]


def _token_key(token: str) -> str:
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def token_match(haystack: str, needle: str) -> bool:
    """Match reworded do-not-keep / forgotten phrases by normalized token overlap."""
    h = {_token_key(t) for t in _norm_tokens(haystack)}
    n = {_token_key(t) for t in _norm_tokens(needle)}
    if not n:
        return False
    return n.issubset(h)


@dataclass
class ExclusionRules:
    do_not_keep: list[str] = field(default_factory=list)
    opt_out_field: str = "owner_opt_out"

    @classmethod
    def load(cls, path: Path | None) -> ExclusionRules:
        if path is None:
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        phrases = data.get("do_not_keep") or data.get("phrases") or []
        field_name = str(data.get("opt_out_field") or "owner_opt_out")
        return cls(do_not_keep=[str(p) for p in phrases], opt_out_field=field_name)


def load_known_names(path: Path | None) -> list[str]:
    if path is None:
        return []
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise RedactionError(f"known_names_file_mode:{mode:o}")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def load_forgotten(path: Path | None) -> list[str]:
    if path is None:
        return []
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise RedactionError(f"forgotten_file_mode:{mode:o}")
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _collect_session_parts(obj: object) -> list[str]:
    parts: list[str] = []
    if isinstance(obj, str):
        parts.append(obj)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            parts.append(str(key))
            parts.extend(_collect_session_parts(value))
    elif isinstance(obj, list):
        for item in obj:
            parts.extend(_collect_session_parts(item))
    return parts


def collect_session_text(obj: object) -> str:
    return "\n".join(_collect_session_parts(obj))


def session_should_exclude(
    session: object,
    rules: ExclusionRules,
    forgotten: list[str],
) -> str | None:
    if not isinstance(session, dict):
        return "invalid_session"
    if session.get(rules.opt_out_field) or session.get("export_opt_out"):
        return "owner_opt_out"
    blob = collect_session_text(session)
    if _FORGET_TOPIC.search(blob) or _FORGET_CMD.search(blob):
        return "forget_command"
    if _MINOR.search(blob):
        return "minor_mentioned"
    for phrase in rules.do_not_keep:
        if token_match(blob, phrase):
            return "do_not_keep"
    for entry in forgotten:
        if token_match(blob, entry):
            return "forgotten"
    return None


def redact_key(key: str, ctx: RedactionContext) -> str:
    if _SENSITIVE_KEY.search(key):
        ctx.bump("json_key")
        return PLACEHOLDER_KEY
    cleaned, _ = redact_text(key, ctx)
    if cleaned != key:
        ctx.bump("json_key")
        return PLACEHOLDER_KEY if cleaned else PLACEHOLDER_KEY
    return key


def _sub(pattern: re.Pattern[str], repl: str, code: str, text: str, ctx: RedactionContext) -> str:
    def _repl(match: re.Match[str]) -> str:
        ctx.bump(code)
        return repl

    return pattern.sub(_repl, text)


def _redact_known_names(text: str, ctx: RedactionContext) -> str:
    out = text
    for name in ctx.known_names:
        if not name:
            continue
        pat = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        if pat.search(out):
            placeholder = ctx.placeholder_name(name)

            def _kn(m: re.Match[str]) -> str:
                ctx.bump("name")
                return placeholder

            out = pat.sub(_kn, out)
    return out


def _redact_name_cues(text: str, ctx: RedactionContext) -> str:
    out = text

    def _replace_match(m: re.Match[str], name: str) -> str:
        ph = ctx.placeholder_name(name)
        ctx.bump("name")
        return ph

    for pattern in (_RE_NAME_CUE, _RE_NAME_TITLE, _RE_NAME_MEETING, _RE_NAME_CALL):
        out = pattern.sub(lambda m: _replace_match(m, m.group(1)), out)

    def _nick(m: re.Match[str]) -> str:
        name = f"{m.group(1)} {m.group(2)}."
        ph = ctx.placeholder_name(name)
        ctx.bump("name")
        return ph

    out = _RE_NAME_NICK.sub(_nick, out)
    return out


def redact_text(text: str, ctx: RedactionContext | None = None) -> tuple[str, list[str]]:
    """Primary redaction pass. Returns (cleaned, codes applied)."""
    if ctx is None:
        ctx = RedactionContext()
    if not text:
        return text, []

    out = text
    out = _redact_known_names(out, ctx)
    out = _redact_name_cues(out, ctx)
    out = _sub(_RE_EMAIL, PLACEHOLDER_EMAIL, "email", out, ctx)
    out = _sub(_RE_DRIVE, PLACEHOLDER_URL, "url", out, ctx)
    out = _sub(_RE_LISTING, PLACEHOLDER_URL, "url", out, ctx)
    out = _sub(_RE_URL, PLACEHOLDER_URL, "url", out, ctx)
    out = _sub(_RE_POBOX, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_STREET, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_CITY_STATE_ZIP, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_SSN, PLACEHOLDER_SSN, "ssn", out, ctx)
    out = _sub(_RE_EIN, PLACEHOLDER_EIN, "ein", out, ctx)
    out = _sub(_RE_CODE, PLACEHOLDER_CODE, "code", out, ctx)
    out = _sub(_RE_CARD_SPACED, PLACEHOLDER_CARD, "card", out, ctx)
    out = re.sub(
        rf"{re.escape(PLACEHOLDER_CARD)}(?:\s+\d{{4}})+",
        PLACEHOLDER_CARD,
        out,
    )
    out = _sub(_RE_CHECKING_ENDING, PLACEHOLDER_ACCOUNT, "account", out, ctx)
    out = _sub(_RE_ACCOUNT_PHRASE, PLACEHOLDER_ACCOUNT, "account", out, ctx)
    out = _sub(_RE_LOAN, PLACEHOLDER_LOAN, "loan", out, ctx)
    out = _sub(_RE_ROUTING, PLACEHOLDER_ROUTING, "routing", out, ctx)
    out = _sub(_RE_DOB_LABEL, PLACEHOLDER_DOB, "dob", out, ctx)
    out = _sub(_RE_DOB_BARE, PLACEHOLDER_DOB, "dob", out, ctx)
    out = _sub(_RE_PHONE_E164, PLACEHOLDER_PHONE, "phone", out, ctx)
    out = _sub(_RE_PHONE_10, PLACEHOLDER_PHONE, "phone", out, ctx)
    out = _sub(_RE_PHONE_7, PLACEHOLDER_PHONE, "phone", out, ctx)
    out = _sub(_RE_HEALTH, PLACEHOLDER_HEALTH, "health", out, ctx)
    out = _sub(_RE_LEGAL, PLACEHOLDER_LEGAL, "legal", out, ctx)
    out = _sub(_RE_DIGITS_LONG, PLACEHOLDER_DIGITS, "long_digits", out, ctx)

    codes = list(ctx.class_counts.keys())
    return out, codes


def redact(text: str, ctx: RedactionContext | None = None) -> tuple[str, list[str]]:
    """Backward-compatible entry: fresh context per call unless provided."""
    if ctx is None:
        local = RedactionContext()
        cleaned, _ = redact_text(text, local)
        return cleaned, list(local.class_counts.keys())
    cleaned, _ = redact_text(text, ctx)
    return cleaned, list(ctx.class_counts.keys())


def scan_residue_secondary(text: str) -> list[str]:
    """Independent second-pass detector set; any hit => unsafe."""
    found: list[str] = []
    if not text:
        return found
    # Allow our own placeholders and redaction tokens
    scrubbed = text
    for token in (
        PLACEHOLDER_PHONE,
        PLACEHOLDER_SSN,
        PLACEHOLDER_EMAIL,
        PLACEHOLDER_ADDRESS,
        PLACEHOLDER_ACCOUNT,
        PLACEHOLDER_CARD,
        PLACEHOLDER_EIN,
        PLACEHOLDER_LOAN,
        PLACEHOLDER_ROUTING,
        PLACEHOLDER_DOB,
        PLACEHOLDER_URL,
        PLACEHOLDER_CODE,
        PLACEHOLDER_HEALTH,
        PLACEHOLDER_LEGAL,
        PLACEHOLDER_KEY,
        PLACEHOLDER_DIGITS,
    ):
        scrubbed = scrubbed.replace(token, " ")
    if _RES_CLIENT_TAG.search(scrubbed):
        scrubbed = _RES_CLIENT_TAG.sub(" ", scrubbed)
    for pattern, kind in _RESIDUE_CHECKS:
        if pattern.search(scrubbed):
            found.append(kind)
    return list(dict.fromkeys(found))


def redact_fail_closed(
    text: str,
    ctx: RedactionContext | None = None,
) -> tuple[str, list[str], bool, list[str]]:
    """Return (cleaned, codes, ok, residue_kinds)."""
    local = ctx or RedactionContext()
    try:
        cleaned, codes = redact_text(text, local)
        residue = scan_residue_secondary(cleaned)
        ok = len(residue) == 0
        return cleaned, codes, ok, residue
    except Exception:
        return "", [], False, ["detector_error"]


def redact_object(
    obj: object,
    ctx: RedactionContext | None = None,
) -> tuple[object, list[str], bool, list[str]]:
    local = ctx or RedactionContext()
    residue: list[str] = []
    try:
        if isinstance(obj, str):
            cleaned, codes, ok, res = redact_fail_closed(obj, local)
            residue.extend(res)
            return cleaned, codes, ok and len(res) == 0, residue
        if isinstance(obj, dict):
            out: dict[str, object] = {}
            codes_all: list[str] = []
            ok_all = True
            for key, value in obj.items():
                new_key = redact_key(str(key), local)
                new_val, codes, ok, res = redact_object(value, local)
                out[new_key] = new_val
                codes_all.extend(codes)
                residue.extend(res)
                ok_all = ok_all and ok
            codes_all = list(dict.fromkeys(codes_all))
            return out, codes_all, ok_all, list(dict.fromkeys(residue))
        if isinstance(obj, list):
            out_list: list[object] = []
            codes_all: list[str] = []
            ok_all = True
            for item in obj:
                new_val, codes, ok, res = redact_object(item, local)
                out_list.append(new_val)
                codes_all.extend(codes)
                residue.extend(res)
                ok_all = ok_all and ok
            return out_list, list(dict.fromkeys(codes_all)), ok_all, list(dict.fromkeys(residue))
        if isinstance(obj, (int, float, bool)) or obj is None:
            return obj, [], True, []
        raise UnsupportedFieldType(f"unsupported_type:{type(obj).__name__}")
    except UnsupportedFieldType:
        raise
    except Exception:
        return obj, [], False, ["detector_error"]


def secure_mkdir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def secure_write_text(path: Path, data: str) -> None:
    secure_mkdir(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)


def write_manifest(path: Path, counts: dict[str, int]) -> None:
    today = datetime.now(timezone.utc).date()
    payload = {
        "redaction_version": REDACTION_VERSION,
        "counts": counts,
        "generated_at": today.isoformat(),
        "deletion_date": (today + timedelta(days=30)).isoformat(),
    }
    secure_write_text(path, json.dumps(payload, indent=2) + "\n")


def log_counts(counts: dict[str, int]) -> None:
    """Log per-class counts only (no removed text)."""
    print(f"redaction_counts: {json.dumps(counts, sort_keys=True)}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redact sensitive spans from session text.")
    parser.add_argument("--in", dest="inp", type=Path, required=True)
    parser.add_argument("--out", dest="out", type=Path, required=True)
    parser.add_argument(
        "--known-names",
        type=Path,
        help="Optional per-box known names list (file mode must be 0600; never commit)",
    )
    parser.add_argument(
        "--fail-closed",
        action="store_true",
        help="Exit 1 if any sensitive pattern remains after redaction",
    )
    parser.add_argument("--manifest", type=Path, help="Write content-free manifest JSON beside output")
    args = parser.parse_args(argv)
    try:
        raw = args.inp.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print("redaction_failed: decode_error", file=sys.stderr)
        return 1
    ctx = RedactionContext(known_names=load_known_names(args.known_names))
    cleaned, codes, ok, residue = redact_fail_closed(raw, ctx)
    if not ok:
        log_counts(ctx.class_counts)
        print(f"redaction_failed: residue={','.join(residue)}", file=sys.stderr)
        if args.fail_closed:
            return 1
    try:
        secure_write_text(args.out, cleaned)
        if args.manifest:
            write_manifest(args.manifest, ctx.class_counts)
    except OSError as exc:
        print(f"redaction_failed: io_error", file=sys.stderr)
        return 1
    if ctx.class_counts:
        log_counts(ctx.class_counts)
    if args.fail_closed and not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
