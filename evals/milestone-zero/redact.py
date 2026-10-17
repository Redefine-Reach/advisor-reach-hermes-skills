#!/usr/bin/env python3
"""Library: redact session content for milestone-zero export (no CLI; use export_session_to_case.py)."""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REDACTION_VERSION = "2.1.0"

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_EXCLUDED = 2

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
PLACEHOLDER_CREDENTIAL = "[REDACTED_CREDENTIAL]"
PLACEHOLDER_KEY = "[REDACTED_KEY]"
PLACEHOLDER_DIGITS = "[REDACTED_DIGITS]"

PHONE_MASK_RE = re.compile(r"\[PHONE \*\*\*\d{4}\]")

_STOP = set(
    "a an the of to for in on at and or is are was were be been it its my our your his her their this that with from by as "
    "about into up out not no do did does have has had will would can could should please just also then than so if when "
    "now new next last".split()
)

# Whole-session drop lexicons (export path only; includes reworded forms).
_HEALTH_DROP = re.compile(
    r"\b(?:surger\w*|surgeon|operat(?:ed on|ion)|procedure|cancer|tumou?r|chemo\w*|radiation|biops\w*|diagnos\w*|diabet\w*|"
    r"blood pressure|meds|medicat\w*|prescription|dizz\w*|anxiety|depress\w*|therap(?:y|ist)|counsel(?:or|ing)|scan results|"
    r"hospital\w*|admitted|icu|pregnan\w*|sobriety|rehab\w*|recover(?:y|ing)|illness|injur\w*|disabilit\w*|"
    r"doctor'?s? appointment|health condition|medical|heart condition|hip replacement)\b",
    re.I,
)
_LEGAL_DROP = re.compile(
    r"\b(?:divorc\w*|custody|lawyers?|attorneys?|lawsuit|sued|suing|chapter (?:7|11|13)|bankrupt\w*|subpoena|probate|"
    r"restraining order|served papers|immigration|dui|arrest\w*|court (?:date|hearing)|in court|hearing|settlement|"
    r"litigation|eviction)\b",
    re.I,
)
_BENIGN_PHRASES = re.compile(
    r"\b(?:call|meeting with|text|see) (?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?\b|"
    r"therapy dog|custody of the [a-z ]*keys|chapter 7 of the|doctor'?s office building|hospital-district|medical office lease",
    re.I,
)
_FORGET_TOPIC = re.compile(r"(?:^|\s)/new\b", re.I)
_FORGET_CMD = re.compile(r"\b(?:forget\b|do not keep|don'?t keep|donotkeep)", re.I)
_MINOR = re.compile(
    r"\b(?:minor\b|under\s+18|(?:\d{1,2})[- ]year[- ]old\s+child|my\s+(?:son|daughter)\s+who\s+is\s+\d{1,2})\b",
    re.I,
)

_NAME_ALLOW = {
    w.lower()
    for w in """Monday Tuesday Wednesday Thursday Friday Saturday Sunday Jan January Feb February Mar March Apr April May Jun June Jul July
Aug August Sep Sept September Oct October Nov November Dec December Phoenix Arizona ARIN OWNER Alex Hi Hey Hello Thanks Thank Done Draft Note
Remember Summarize Make Set Use Got Reply Schedule Pick Order Sign Add Call Text Remind Forward Open Show Wire Lender Her His The It Link Card Routing
Client Mr Mrs Ms Dr Why Version Meeting List Fill Wifi FYI MLS PDF LLC DOB SSN EIN AZ""".split()
}

_RE_SSN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_RE_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I)
_RE_DRIVE = re.compile(r"\b(?:https?://)?(?:drive\.google\.com|docs\.google\.com)/[^\s]+", re.I)
_RE_LISTING = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:zillow|redfin|realtor)\.com/[^\s]+",
    re.I,
)
_RE_STREET = re.compile(
    r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,3}\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place)\b\.?",
    re.I,
)
_RE_CITY_STATE_ZIP = re.compile(r"\b[A-Za-z][A-Za-z .\-]{2,30},\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
_RE_POBOX = re.compile(r"\bP\.?\s*O\.?\s*Box\s+\d+\b", re.I)
_RE_CHECKING_ENDING = re.compile(r"\bchecking\s+ending\s+(\d{4})\b", re.I)
_RE_LOAN = re.compile(r"\bloan\s+(\d{4}-\d{2})\b", re.I)
_RE_ROUTING = re.compile(r"\b(?:routing|aba)\s*(?:#|number)?\s*[:#]?\s*(\d{9})\b", re.I)
_RE_EIN = re.compile(r"\b\d{2}-\d{7}\b")
_RE_DOB_LABEL = re.compile(
    r"\b(?:DOB|D\.O\.B\.|date of birth|born(?:\s+on)?|birthday|b-?day)\s*(?:is|on|:)?\s*"
    r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2}|"
    r"[A-Za-z]+\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
_RE_DOB_ANY = re.compile(
    r"\b(?:birthday|b-?day|dob|born)\s*(?:is|on|:)?\s*(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
    re.I,
)
_RE_DIGITS_LONG = re.compile(r"\b\d{9,17}\b")
_RE_CARD_SPACED = re.compile(r"\b(?:\d{4}\s+){3}\d{4}\b")
_CARD_ANY = re.compile(r"(?<![\d$,])(?:\d{4}[-\s]){3}\d{4}(?!\d)|(?<![\d$,])\d{15,19}(?!\d)")
_SHORT_ACCT = re.compile(r"\b(?:account|acct)\.?\s*(?:number|no\.?|#)?\s*[:#]?\s*\d{4,17}\b", re.I)
_BARE_URL = re.compile(r"\b[A-Za-z0-9\-]+\.(?:com|org|net|io|ai|co)/\S+", re.I)
_PHONE_10 = re.compile(r"(?<![\d$,])(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
_PHONE_7 = re.compile(r"(?<![\d$,.\-])\d{3}[-\s.]\d{4}(?![\d\-])")
_CRED_PATTERNS = [
    re.compile(p)
    for p in (
        r"\bsk_(?:test|live)_[A-Za-z0-9]{6,}",
        r"\bAKIA[A-Z0-9]{8,}",
        r"\bBearer\s+[A-Za-z0-9._\-]{8,}",
        r"\b(?:password|passwd|passcode|pin)\s*(?:is|:|=)\s*\S+",
        r"\b(?:api[ _-]?key|secret|token)\s*(?:is|:|=)?\s*[A-Za-z0-9_\-.]{8,}",
        r"\bwifi password:?\s*\S+",
        r"\b(?:lockbox|gate|door|garage|alarm)\s+(?:code|pin)\s*(?:is|:)?\s*\d{3,8}",
    )
]

_SENSITIVE_KEY = re.compile(
    r"(?:ssn|social|email|e-mail|phone|mobile|address|street|dob|birth|password|"
    r"token|secret|account|routing|card|ein|loan|lockbox|gate|alarm|garage)",
    re.I,
)

# Secondary residue (independent patterns).
_RES_SSN = re.compile(r"\d{3}[-\s]?\d{2}[-\s]?\d{4}")
_RES_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RES_PHONE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\d{3}[-\s.]\d{4}|\+1\d{10}",
)
_RES_URL = re.compile(r"https?://\S+|www\.\S+|\b[A-Za-z0-9\-]+\.(?:com|org|net|io)\S*", re.I)
_RES_STREET = re.compile(r"\d{1,5}\s+\w+\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pl)\b", re.I)
_RES_ACCOUNT = re.compile(r"(?:account|acct).{0,12}\d{4,}", re.I)
_RES_CARD = re.compile(r"\d{4}\s+\d{4}\s+\d{4}\s+\d{4}|\d{15,19}")
_RES_EIN = re.compile(r"\d{2}-\d{7}")
_RES_HEALTH = re.compile(
    r"\b(?:cancer|chemo|surger|therapy|diabetes|anxiety|hospital|medication|diagnos|heart condition)\b",
    re.I,
)
_RES_LEGAL = re.compile(
    r"\b(?:divorce|custody|attorney|lawsuit|bankruptcy|subpoena|probate|restraining|settlement)\b",
    re.I,
)
_RES_DOB = re.compile(r"(?:DOB|born|birthday).{0,10}\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", re.I)
_RES_CRED = re.compile(
    r"sk_(?:test|live)_|AKIA|Bearer\s+|password\s*(?:is|:)|api[ _-]?key|wifi password",
    re.I,
)
_RES_CLIENT_TAG = re.compile(r"\bCLIENT_\d+\b")


class RedactionError(Exception):
    pass


class UnsupportedFieldType(RedactionError):
    pass


@dataclass
class RedactionContext:
    known_names: list[str] = field(default_factory=list)
    owner_name: str = "Alex"
    class_counts: dict[str, int] = field(default_factory=dict)
    _name_map: dict[str, str] = field(default_factory=dict)

    def placeholder_name(self, raw: str) -> str:
        key = raw.strip().lower()
        if key not in self._name_map:
            self._name_map[key] = f"CLIENT_{len(self._name_map) + 1}"
        return self._name_map[key]

    def bump(self, code: str, n: int = 1) -> None:
        self.class_counts[code] = self.class_counts.get(code, 0) + n


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


def _stem(token: str) -> str:
    t = token.lower().replace("\u2019", "'")
    t = re.sub(r"'s$|s'$", "", t)
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _toks(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[A-Za-z0-9\u2019']+", text) if t.lower() not in _STOP]


def phrase_hit(text: str, phrase: str, thresh: float = 0.75) -> bool:
    need = _toks(phrase)
    if len(need) < 2:
        return bool(need) and need[0] in set(_toks(text))
    have = set(_toks(text))
    return sum(1 for t in need if t in have) / len(need) >= thresh


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


def session_drop_reason(
    session: object,
    rules: ExclusionRules,
    forgotten: list[str],
) -> str | None:
    """Whole-session drop rules (export path only)."""
    if not isinstance(session, dict):
        return "invalid_session"
    if session.get(rules.opt_out_field) or session.get("export_opt_out"):
        return "owner_opt_out"
    blob = collect_session_text(session)
    if "\x00" in blob:
        return "detector_error"
    if _FORGET_TOPIC.search(blob) or _FORGET_CMD.search(blob):
        return "forget_command"
    if _MINOR.search(blob):
        return "minor_mentioned"
    scrub = _BENIGN_PHRASES.sub(" ", blob)
    if _HEALTH_DROP.search(scrub):
        return "health"
    if _LEGAL_DROP.search(scrub):
        return "legal"
    for phrase in rules.do_not_keep:
        if phrase_hit(blob, phrase):
            return "do_not_keep"
    for entry in forgotten:
        if phrase_hit(blob, entry):
            return "forgotten"
    return None


def phone_mask(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"[PHONE ***{digits[-4:]}]"


def _sub(pattern: re.Pattern[str], repl: str, code: str, text: str, ctx: RedactionContext) -> str:
    def _repl(m: re.Match[str]) -> str:
        ctx.bump(code)
        return repl

    return pattern.sub(_repl, text)


def redact_names(text: str, ctx: RedactionContext) -> str:
    owner = ctx.owner_name.lower()
    allow = _NAME_ALLOW | {owner}
    name_map = ctx._name_map

    def ph(name: str) -> str:
        return ctx.placeholder_name(name)

    out = text
    for nm in ctx.known_names:
        if nm:
            out = re.sub(
                rf"\b{re.escape(nm)}\b",
                lambda m, n=nm: (ctx.bump("name"), ph(n))[1],
                out,
                flags=re.I,
            )

    def fix_line(line: str) -> str:
        m = re.match(r"^(\s*(?:OWNER \([^)]*\)|ARIN):\s*)(.*)$", line)
        head, body = (m.group(1), m.group(2)) if m else ("", line)
        body = re.sub(
            r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.\s+([A-Z][a-z]+)",
            lambda g: (ctx.bump("name"), ph(g.group(1)))[1],
            body,
        )
        body = re.sub(
            r"\b([A-Z][a-z]+)\s+[A-Z]\.(?=\s|$|[,;:])",
            lambda g: (ctx.bump("name"), ph(f"{g.group(1)} {g.group(0).split()[-1]}"))[1],
            body,
        )

        def word(g: re.Match[str]) -> str:
            w = g.group(1)
            start = g.start(1)
            if w.lower() in allow or w.startswith("CLIENT_"):
                return w
            before = body[:start].rstrip()
            sentence_start = before == "" or before[-1:] in ".!?:"
            nxt = re.match(r"\s+([A-Z][a-z]+)\b", body[g.end(1) :])
            if sentence_start and not (nxt and nxt.group(1).lower() not in allow):
                return w
            ctx.bump("name")
            return ph(w)

        body = re.sub(r"\b([A-Z][a-z]{2,})(?:'s)?\b", word, body)
        return head + body

    return "\n".join(fix_line(ln) for ln in out.split("\n"))


def redact_text(text: str, ctx: RedactionContext) -> tuple[str, list[str]]:
    if not text:
        return text, []
    out = text
    hold: list[str] = []

    def _hold(m: re.Match[str]) -> str:
        hold.append(m.group(0))
        return f"\u2063{len(hold) - 1}\u2063"

    out = _BENIGN_PHRASES.sub(_hold, out)
    for pat in _CRED_PATTERNS:
        out = pat.sub(lambda m: (ctx.bump("credential"), PLACEHOLDER_CREDENTIAL)[1], out)
    out = _CARD_ANY.sub(lambda m: (ctx.bump("card"), PLACEHOLDER_CARD)[1], out)
    out = _SHORT_ACCT.sub(lambda m: (ctx.bump("account"), PLACEHOLDER_ACCOUNT)[1], out)
    out = _RE_DOB_ANY.sub(lambda m: (ctx.bump("dob"), PLACEHOLDER_DOB)[1], out)
    out = _BARE_URL.sub(lambda m: (ctx.bump("url"), PLACEHOLDER_URL)[1], out)
    out = _PHONE_10.sub(lambda m: (ctx.bump("phone"), phone_mask(m))[1], out)
    out = _PHONE_7.sub(lambda m: (ctx.bump("phone"), phone_mask(m))[1], out)
    out = _sub(_RE_EMAIL, PLACEHOLDER_EMAIL, "email", out, ctx)
    out = _sub(_RE_DRIVE, PLACEHOLDER_URL, "url", out, ctx)
    out = _sub(_RE_LISTING, PLACEHOLDER_URL, "url", out, ctx)
    out = _sub(_RE_URL, PLACEHOLDER_URL, "url", out, ctx)
    out = _sub(_RE_POBOX, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_STREET, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_CITY_STATE_ZIP, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_SSN, PLACEHOLDER_SSN, "ssn", out, ctx)
    out = _sub(_RE_EIN, PLACEHOLDER_EIN, "ein", out, ctx)
    out = _sub(_RE_CARD_SPACED, PLACEHOLDER_CARD, "card", out, ctx)
    out = re.sub(rf"{re.escape(PLACEHOLDER_CARD)}(?:\s+\d{{4}})+", PLACEHOLDER_CARD, out)
    out = _sub(_RE_CHECKING_ENDING, PLACEHOLDER_ACCOUNT, "account", out, ctx)
    out = _sub(_RE_LOAN, PLACEHOLDER_LOAN, "loan", out, ctx)
    out = _sub(_RE_ROUTING, PLACEHOLDER_ROUTING, "routing", out, ctx)
    out = _sub(_RE_DOB_LABEL, PLACEHOLDER_DOB, "dob", out, ctx)
    out = _sub(_RE_DIGITS_LONG, PLACEHOLDER_DIGITS, "long_digits", out, ctx)
    out = re.sub("\u2063(\\d+)\u2063", lambda m: hold[int(m.group(1))], out)
    out = redact_names(out, ctx)
    return out, list(ctx.class_counts.keys())


def redact(text: str, ctx: RedactionContext | None = None) -> tuple[str, list[str]]:
    local = ctx or RedactionContext()
    cleaned, _ = redact_text(text, local)
    return cleaned, list(local.class_counts.keys())


def scan_residue_secondary(text: str) -> list[str]:
    found: list[str] = []
    if not text:
        return found
    scrubbed = text
    for token in (
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
        PLACEHOLDER_CREDENTIAL,
        PLACEHOLDER_KEY,
        PLACEHOLDER_DIGITS,
    ):
        scrubbed = scrubbed.replace(token, " ")
    scrubbed = PHONE_MASK_RE.sub(" ", scrubbed)
    if _RES_CLIENT_TAG.search(scrubbed):
        scrubbed = _RES_CLIENT_TAG.sub(" ", scrubbed)
    scrubbed = _BENIGN_PHRASES.sub(" ", scrubbed)
    checks = [
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
        (_RES_CRED, "credential"),
    ]
    for pattern, kind in checks:
        if pattern.search(scrubbed):
            found.append(kind)
    return list(dict.fromkeys(found))


def own_residue(text: str) -> list[str]:
    scrub = _BENIGN_PHRASES.sub(" ", text)
    found: list[str] = []
    if re.search(r"@\w", text):
        found.append("email")
    if re.search(r"https?://|www\.", text, re.I):
        found.append("url")
    if re.search(r"(?<![\d$,])\d{9,}", text):
        found.append("long_digits")
    if re.search(r"(?<![\d$,.\-])\d{3}[-\s.]\d{4}(?![\d\-])", text):
        found.append("phone7")
    if any(p.search(text) for p in _CRED_PATTERNS):
        found.append("credential")
    if _HEALTH_DROP.search(scrub) or _LEGAL_DROP.search(scrub):
        found.append("health_legal")
    return found


def redact_fail_closed(text: str, ctx: RedactionContext | None = None) -> tuple[str, list[str], bool, list[str]]:
    local = ctx or RedactionContext()
    try:
        cleaned, codes = redact_text(text, local)
        residue = scan_residue_secondary(cleaned) + own_residue(cleaned)
        residue = [r for r in dict.fromkeys(residue) if r not in ("phone", "name")]
        ok = len(residue) == 0
        return cleaned, codes, ok, residue
    except Exception:
        return "", [], False, ["detector_error"]


def redact_key(key: str, ctx: RedactionContext) -> str:
    if _SENSITIVE_KEY.search(key):
        ctx.bump("json_key")
        return PLACEHOLDER_KEY
    cleaned, _ = redact_text(key, ctx)
    if cleaned != key:
        ctx.bump("json_key")
        return PLACEHOLDER_KEY
    return key


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
            return out, list(dict.fromkeys(codes_all)), ok_all, list(dict.fromkeys(residue))
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


def load_session_payload(path: Path) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    if b"\x00" in raw_bytes:
        raise ValueError("nul")
    text = raw_bytes.decode("utf-8")
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("session_not_object")
        return data
    return {"owner_text": text, "messages": [{"role": "user", "content": text}]}


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
    print(f"redaction_counts: {json.dumps(counts, sort_keys=True)}", file=sys.stderr)


def log_excluded(category: str) -> None:
    print(f"excluded_sessions: 1 category={category}", file=sys.stderr)
