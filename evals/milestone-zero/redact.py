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

from conservative_guard import post_redact_unsafe, pre_export_drop_category, scrub_benign
from phrase_match import phrase_hit

REDACTION_VERSION = "2.2.0"

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
    r"litigation|eviction|\bjudge\b|child\s+support|spousal\s+support|prenup|probation|green\s+card)\b",
    re.I,
)
_BENIGN_PHRASES = re.compile(
    r"(?:"
    # No "text <weekday>" hold (Vault b984cba w03): "text Sunday Reyes" is a person, not a day.
    r"\b(?:call|meeting with|see) (?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?\b|"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon|Tues?|Wed(?:nesday)?|Thu(?:rsday)?|Fri|Sat(?:urday)?|Sun(?:day)?)'s\b"
    r")",
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
Aug August Sep Sept September Oct October Nov November Dec December Phoenix Arizona ARIN OWNER Hi Hey Hello Thanks Thank Done Draft Note
Remember Summarize Make Set Use Got Reply Schedule Pick Order Sign Add Call Text Remind Forward Open Show Wire Lender Her His The It Link Card Routing
Client Mr Mrs Ms Dr Why Version Meeting List Fill Wifi FYI MLS PDF LLC DOB SSN EIN AZ Jar""".split()
}
_DATE_WORDS = frozenset("""monday tuesday wednesday thursday friday saturday sunday january february march
april may june july august september october november december""".split())
# No real first names here (Vault N3): the only name ever kept is --owner-name.

# Words after "text" that are not a person (Vault N1: "text <Name> about" must map "<Name>" only).
_TEXT_TARGET_SKIP = frozenset("""
a an the about to for from with when if and or but so on at in into by of now later soon tomorrow today tonight again
first back me him her them us you it its that this these those everyone everybody someone somebody anyone all both
my our your his their message messages msg reminder reminders thread group chat update updates note confirmation
saying asking telling letting re regarding""".split())

# Sentence-start words that are ordinary English, never treated as names (Vault N2 default-deny
# applies only to a capitalized sentence-start word followed by a person verb or 's).
_COMMON_STARTERS = frozenset("""
i im i'm i'll i've id you we they he she it this that these those there here what when where who why how which
the a an and but or so if then also just still yet already only even maybe perhaps please sure okay ok yes yeah no nope
all any each every some most many much more less none nothing everything something anything someone everyone nobody
today tomorrow tonight yesterday now later soon next last first second third new old good great fine perfect
sounds looks seems got get gets getting going went come came coming will would could should can may might must
closing showing showings listing listings inspection inspections appraisal escrow offer offers price pricing contract
counter counteroffer buyer buyers seller sellers lender loan title tour tours open house home property client clients
agent agents team office meeting call calls text texts email emails draft drafts reminder reminders note notes
update updates status payment invoice rent lease deposit earnest docs documents paperwork report reports
morning afternoon evening weekend week month year noon midnight
sent saved staged scheduled booked moved cancelled canceled confirmed done finished ready set added updated
left signed approved declined received called asked said says told wants needs
noted understood thanks thank awesome cool nice sorry yep yup nah right agreed absolutely definitely correct exactly
heads fyi reminder update hey hi hello morning evening dear regards cheers best""".split())

def _load_common_words() -> frozenset[str]:
    path = Path(__file__).resolve().parent / "common_words.txt"
    words = {
        ln.strip().lower() for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }
    return frozenset(words)


_COMMON_WORDS = _load_common_words()
_KNOWN_WORDS: frozenset[str] | None = None


def is_dictionary_word(word: str) -> bool:
    """Ordinary English (common_words.txt plus the starter lists), with simple suffix stripping."""
    global _KNOWN_WORDS
    low = word.lower().replace("'", "").replace("\u2019", "")
    if _KNOWN_WORDS is None:
        _KNOWN_WORDS = _COMMON_WORDS | _COMMON_STARTERS | _TEXT_TARGET_SKIP | _NOT_SURNAME | _PERSON_VERBS | _ADVERBS
    known = _KNOWN_WORDS
    if low in known:
        return True
    stems = []
    for suf, rep in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("d", ""),
                     ("ing", ""), ("ing", "e"), ("ly", "")):
        if low.endswith(suf) and len(low) - len(suf) >= 3:
            stems.append(low[: len(low) - len(suf)] + rep)
    return any(st in known for st in stems)


# Common acronyms / shouting words that are not names (ALL-CAPS rule, Vault b984cba (b)).
_ACRONYMS = frozenset("""
asap fyi mls hoa hvac cma adu llc inc pdf dob ssn ein arin owner sms mms usps ups fedex eta tbd rsvp atm pst mst est cst
utc usa url api crm irs hud fha usda arm apr heloc pmi ltv dti bpo reo nar realtor sqft btw imo lol omg thx pls plz
ooo pto nda loi poa coe tbh aka diy faq gps pin otp kyc ach ira llp esq vin pdt edt cdt mdt hoas mlss pdfs ssns
""".split())

_RE_NAME_EXTRA = re.compile(
    r"(?<![\w\[])((?:Ma?c[A-Z][a-z]+)|(?=[^\W\d_]*[^\x00-\x7f])[^\W\d_a-z][^\W\d_]*[^\W\d_])(?:'s)?(?![\w\]])"
)

# "<Word>'s" contractions that are not possessives. Read ONLY by the sentence-start name test,
# never by the do-not-keep rule-name check or the surname test (Vault df95508 item 4).
_S_CONTRACTIONS = frozenset("let here there that what it who where how".split())

_ADVERBS = frozenset("""also just still already probably definitely maybe really finally actually never always
apparently basically clearly obviously supposedly reportedly honestly literally seriously totally""".split())

# Ordinary lowercase words that can follow "text <name>" and are not a surname.
_NOT_SURNAME = frozenset("""
i im i'm ill i'll id i'd ive i've we were she he they you your u ur pls please asap now later soon tonight today tomorrow
that this about to and or but so if when re saying asking telling letting running coming going leaving heading
back again first quick real hey hi hello thanks ok okay yes no not just also still really the a an for from with
on at in of by my our his her their its it is are was were be been will would can could should may might""".split())

_PERSON_VERBS = frozenset("""
asked asks called calls said says texted texts emailed emails replied replies confirmed confirms wants wanted needs
needed signed agreed approved declined left loved liked hated prefers prefer mentioned told tells sent sends is was
will would can could has had just already still thinks thought decided requested booked cancelled canceled
moved accepted rejected countered responded wrote writes shared""".split())

_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_RE_SPELLED_DIGIT_RUN = re.compile(
    r"\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)\s+){3,}"
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)\b",
    re.I,
)
_RE_DIGIT_SPACED = re.compile(r"(?<![\d$])(?:\d\s+){9,14}\d(?!\d)")
_RE_EMAIL_OBF = re.compile(
    r"\b[a-z0-9._%+\-]+\s+at\s+[a-z0-9._\-]+\s+dot\s+(?:com|org|net|io)\b",
    re.I,
)
_RE_ADDR_LOOSE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){0,2}\b",
)
_RE_ROUTING_BARE = re.compile(r"(?<![\d])\b0\d{8}\b(?!\d)")
_RE_GATE_SPELLED = re.compile(
    r"\b(?:gate|door|lockbox|garage)\s+code\s+is\s+"
    r"((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)\s+){2,6})",
    re.I,
)

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
        r"\blogin\s+(?:is\s+)?\S{4,}",
        r"\bclient_secret\s*=\s*\S+",
        r"\bghp_[A-Za-z0-9]{20,}",
        r"\bapi\s+key\s+\S{4,}",
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
    owner_name: str = ""  # only --owner-name is ever kept (no default owner)
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


def expand_known_names(names: list[str]) -> list[str]:
    expanded: list[str] = []
    for name in names:
        expanded.append(name)
        for part in re.split(r"\s+", name.strip()):
            if len(part) > 1:
                expanded.append(part)
    return list(dict.fromkeys(expanded))


def load_known_names(path: Path | None) -> list[str]:
    if path is None:
        return []
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise RedactionError(f"known_names_file_mode:{mode:o}")
    lines = path.read_text(encoding="utf-8").splitlines()
    raw = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    candidates = expand_known_names(raw)
    ignored = _COMMON_WORDS | STRUCTURAL_ROLE_VALUES | {
        "messages", "message", "role", "content", "source",
        "telnyx_sms", "cli", "api_server", "cron", "telegram", "webhook",
    }
    # Drop a compound candidate too if one of its parts is ordinary/schema text;
    # expand_known_names still preserves any other, potentially identifying parts.
    names = [name for name in candidates if not any(part.lower() in ignored for part in name.split())]
    print(f"known_names_dropped: count={len(candidates) - len(names)}", file=sys.stderr)
    return names


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
    scrub = scrub_benign(_BENIGN_PHRASES.sub(" ", blob))
    topic = pre_export_drop_category(scrub)
    if topic:
        return topic
    if _HEALTH_DROP.search(scrub):
        return "health"
    if _LEGAL_DROP.search(scrub):
        return "legal"
    for phrase in rules.do_not_keep:
        if phrase_hit(blob, phrase) or _rule_name_hit(blob, phrase):
            return "do_not_keep"
    for entry in forgotten:
        if phrase_hit(blob, entry):
            return "forgotten"
    return None


def _rule_name_hit(blob: str, phrase: str) -> bool:
    """A do-not-keep rule naming a person ("<Surname> morning calls") drops any session that
    mentions that name, even when the rest of the wording differs (conservative)."""
    for tok in re.findall(r"\b[A-Z][a-z]{2,}\b", phrase):
        low = tok.lower()
        if low in _NAME_ALLOW or low in _COMMON_STARTERS or low in _TEXT_TARGET_SKIP:
            continue
        if re.search(rf"\b{re.escape(tok)}(?:'s)?\b", blob, re.I):
            return True
    return False


def phone_mask(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"[PHONE ***{digits[-4:]}]"


def _digits_from_words(words: list[str]) -> str:
    return "".join(_DIGIT_WORDS.get(w.lower(), "") for w in words)


def _mask_spelled_digit_run(match: re.Match[str], ctx: RedactionContext) -> str:
    words = match.group(0).split()
    digits = _digits_from_words(words)
    if len(digits) >= 7:
        ctx.bump("phone")
        return f"[PHONE ***{digits[-4:]}]"
    if len(digits) >= 3:
        ctx.bump("credential")
        return PLACEHOLDER_CREDENTIAL
    return match.group(0)


def _mask_spaced_digits(match: re.Match[str], ctx: RedactionContext) -> str:
    digits = re.sub(r"\s+", "", match.group(0))
    if len(digits) >= 10:
        ctx.bump("phone")
        return f"[PHONE ***{digits[-4:]}]"
    return match.group(0)


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

    def replace_lower(m: re.Match[str]) -> str:
        word = m.group(1)
        if word.lower() in allow:
            return m.group(0)
        ctx.bump("name")
        return m.group(0).replace(word, ph(word), 1)

    def replace_text_target(m: re.Match[str]) -> str:
        first, last = m.group(1), m.group(2)
        # A weekday/month word after "text" followed by a capitalized surname is a person
        # ("text Sunday Reyes", "text April Moss"), so it is not kept as a date word.
        date_person = (
            first.lower() in _DATE_WORDS and first[0].isupper() and bool(last) and last[0].isupper()
            and last.lower() not in allow and last.lower() not in _TEXT_TARGET_SKIP
        )
        if (first.lower() in allow or first.lower() in _TEXT_TARGET_SKIP) and not date_person:
            return m.group(0)
        ctx.bump("name")
        out_s = m.group(0).replace(first, ph(first), 1)
        if last and last.lower() not in allow and last.lower() not in _TEXT_TARGET_SKIP and (
            last[0].isupper() or last.lower() not in _NOT_SURNAME
        ):
            ctx.bump("name")
            out_s = out_s[: out_s.rfind(last)] + ph(last) + out_s[out_s.rfind(last) + len(last):]
        return out_s

    # One name token after "text" (any case: texting-style lowercase names count), plus an
    # optional surname (capitalized, or lowercase unless it is an ordinary word). Each token gets its own placeholder, so the cross-turn
    # pass replaces the name alone later ("<Name> confirmed Friday").
    out = re.sub(
        r"\b(?i:text)\s+([A-Za-z][a-z]+)(?:\s+([A-Za-z][a-z]+)\b(?!'))?",
        replace_text_target,
        out,
    )
    out = re.sub(
        r"\btell\s+([a-z]{2,})\s+and\s+([a-z]{2,})",
        lambda m: (
            ctx.bump("name"),
            f"tell {ph(m.group(1))} and {ph(m.group(2))}",
        )[1],
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
            tail = g.group(0)[len(w) :]
            start = g.start(1)
            if (w.lower() in allow and w.lower() not in name_map) or w.startswith("CLIENT_"):
                return w + tail
            before = body[:start].rstrip()
            sentence_start = before == "" or before[-1:] in ".!?:"
            if sentence_start and w.lower() not in name_map:
                # Sentence/reply/"Why:" start (Vault N2): a name when it is not ordinary English
                # and is followed by a person verb, a possessive, or another capitalized name.
                rest = body[g.end(1):]
                nxt_cap = re.match(r"\s+([A-Z][a-z]+)\b", rest)
                nxt_word = re.match(r"\s+([a-z']+)\b", rest)
                possessive = rest.startswith("'s") and w.lower() not in _S_CONTRACTIONS
                # Vault 029b63a: also comma, colon, end of line / alone, or an adverb next
                # ("Percival, can you", "Cornelius: fine", "Octavia", "Thaddeus definitely called",
                # "Grace, Bill, ..." as a list's first item).
                punct_or_end = re.match(r"\s*(?:[,:;]|$|[.!?]\s*$)", rest) is not None
                adverb = bool(nxt_word and (nxt_word.group(1) in _ADVERBS or
                                            (nxt_word.group(1).endswith("ly") and len(nxt_word.group(1)) > 4)))
                person = (nxt_word and nxt_word.group(1) in _PERSON_VERBS) or possessive or punct_or_end or adverb or (
                    nxt_cap and nxt_cap.group(1).lower() not in allow
                    and nxt_cap.group(1).lower() not in _COMMON_STARTERS
                )
                # Vault b984cba (a): a capitalized word at a sentence/line/"Why:" start that is not
                # ordinary English is a name whatever follows ("Philippa—", "Ambrose and",
                # "Evander 👍", "Re: Philippa —", "Ambrose should"). The shape heuristics above
                # stay as an extra layer for dictionary words.
                contraction = re.match(r"['\u2019]([a-rt-z][a-z]*)\b", rest)
                full = w + contraction.group(1) if contraction else w
                if not is_dictionary_word(full) and full.lower() not in allow:
                    person = True
                elif w.lower() in _COMMON_STARTERS:
                    return w + tail
                if not person:
                    return w + tail
            ctx.bump("name")
            return ph(w) + (tail if tail.startswith("'s") else "")
            ctx.bump("name")
            return ph(w)

        body = re.sub(r"\b([A-Z][a-z]{2,})(?:'s)?\b", word, body)
        # Vault df95508 item 3: capitalized names with non-ASCII letters (Zoë, Siobhán, Łukasz) and
        # Mc/Mac names with an inner capital (McAllister, MacKenzie), anywhere in the line.
        body = re.sub(_RE_NAME_EXTRA, lambda g: word(g) if g.group(1)[0].isupper() else g.group(0), body)

        # Vault b984cba (b): an ALL-CAPS word that is not ordinary English and not a common
        # acronym is a name ("EVANDER CALLED"). Placeholders ([PHONE ...], REDACTED_X, CLIENT_n)
        # are never touched.
        def caps(g: re.Match[str]) -> str:
            w = g.group(1)
            contraction = re.match(r"['\u2019]([A-RT-Z][A-Z]*)\b", body[g.end(1):])
            full = w + contraction.group(1) if contraction else w
            low = w.lower()
            if (low in allow and low not in name_map) or low in _ACRONYMS or is_dictionary_word(full):
                return w
            ctx.bump("name")
            return ph(w)

        body = re.sub(r"(?<![\[\w])([A-Z]{3,})(?![\w\]])", caps, body)
        body = re.sub(
            r"\b([a-z]{2,})\b",
            lambda g: g.group(0)
            if g.group(1).lower() in allow or g.group(1).startswith("client_")
            else (ctx.bump("name"), ph(g.group(1)))[1]
            if g.group(1).lower() in {p.lower() for p in ctx.known_names}
            else g.group(0),
            body,
        )
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
    out = _RE_GATE_SPELLED.sub(
        lambda m: (ctx.bump("credential"), PLACEHOLDER_CREDENTIAL)[1],
        out,
    )
    out = _RE_SPELLED_DIGIT_RUN.sub(lambda m: _mask_spelled_digit_run(m, ctx), out)
    out = _RE_DIGIT_SPACED.sub(lambda m: _mask_spaced_digits(m, ctx), out)
    out = _RE_EMAIL_OBF.sub(lambda m: (ctx.bump("email"), PLACEHOLDER_EMAIL)[1], out)
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
    out = _sub(_RE_ADDR_LOOSE, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_STREET, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_CITY_STATE_ZIP, PLACEHOLDER_ADDRESS, "address", out, ctx)
    out = _sub(_RE_SSN, PLACEHOLDER_SSN, "ssn", out, ctx)
    out = _sub(_RE_EIN, PLACEHOLDER_EIN, "ein", out, ctx)
    out = _sub(_RE_CARD_SPACED, PLACEHOLDER_CARD, "card", out, ctx)
    out = re.sub(rf"{re.escape(PLACEHOLDER_CARD)}(?:\s+\d{{4}})+", PLACEHOLDER_CARD, out)
    out = _sub(_RE_CHECKING_ENDING, PLACEHOLDER_ACCOUNT, "account", out, ctx)
    out = _sub(_RE_LOAN, PLACEHOLDER_LOAN, "loan", out, ctx)
    out = _sub(_RE_ROUTING, PLACEHOLDER_ROUTING, "routing", out, ctx)
    out = _sub(_RE_ROUTING_BARE, PLACEHOLDER_ROUTING, "routing", out, ctx)
    out = _sub(_RE_DOB_LABEL, PLACEHOLDER_DOB, "dob", out, ctx)
    out = _sub(_RE_DIGITS_LONG, PLACEHOLDER_DIGITS, "long_digits", out, ctx)
    # Benign holds (weekday phrases) stay held through name redaction.
    out = redact_names(out, ctx)
    out = re.sub("\u2063(\\d+)\u2063", lambda m: hold[int(m.group(1))], out)
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


def redact_fail_closed(text: str, ctx: RedactionContext | None = None) -> tuple[str, list[str], bool, list[str]]:
    local = ctx or RedactionContext()
    try:
        cleaned, codes = redact_text(text, local)
        residue = scan_residue_secondary(cleaned)
        residue = [r for r in dict.fromkeys(residue) if r not in ("phone", "name")]
        ok = len(residue) == 0
        return cleaned, codes, ok, residue
    except Exception:
        return "", [], False, ["detector_error"]


def post_export_safety_flags(text: str) -> list[str]:
    return post_redact_unsafe(text)


# JSON structure is never redacted (Vault, Oct 19): keys stay verbatim, and a role value from this
# vocabulary stays verbatim, so a known-names token such as "messages", "user", "content" or "role"
# can never rename a key or blank a turn's role. Keys still go into every residue/safety scan
# (collect_session_text), so a key holding a phone, email or credential blocks the export.
STRUCTURAL_ROLE_KEYS = frozenset({"role"})
STRUCTURAL_ROLE_VALUES = frozenset(
    {"user", "owner", "human", "assistant", "arin", "agent", "tool", "system", "function", "developer"}
)


def is_structural_value(key: object, value: object) -> bool:
    """True for a role field whose value is a known role name (kept as structure, not text)."""
    return (
        isinstance(key, str)
        and key.strip().lower() in STRUCTURAL_ROLE_KEYS
        and isinstance(value, str)
        and value.strip().lower() in STRUCTURAL_ROLE_VALUES
    )


def redact_key(key: str, ctx: RedactionContext) -> str:
    """Keys are structure: always returned unchanged (see STRUCTURAL_ROLE_KEYS)."""
    return key


def _sensitive_scalar(value: object, ctx: RedactionContext) -> object:
    """Scalar under a sensitive key ("phone", "password", ...): the whole value is replaced."""
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return value
    ctx.bump("json_key")
    return PLACEHOLDER_KEY


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
                new_key = redact_key(key, local) if isinstance(key, str) else key
                if is_structural_value(key, value):
                    out[new_key] = value
                    continue
                if isinstance(key, str) and _SENSITIVE_KEY.search(key) and not isinstance(value, (dict, list)):
                    out[new_key] = _sensitive_scalar(value, local)
                    continue
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
