#!/usr/bin/env python3
"""Client-profile rules tool. One JSON object on stdout. Stdlib only.

Data root: $CLIENT_PROFILE_ROOT or /opt/data/client-profile.
Config:    $CLIENT_PROFILE_ROOT/config.json  {"enabled": true|false, ...}
           A stored consent_required key is ignored and is not a consent step.
           Research is public information only. Never contact the client or lead.
Audit:     <root>/../audit/client-profile.jsonl

Network is used only by `search`, and only to call Exa when a key is set.
No CRM write, no Human Design, no street-address field.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
SCHEMA_PATH = ASSETS / "brief.schema.json"
TEMPLATE_PATH = ASSETS / "template.html"

CLIENT_RE = re.compile(r"^c[0-9a-f]{16}$")
EVIDENCE_RE = re.compile(r"^ev_[0-9a-f]{8,32}$")
STREET_TYPES = (
    r"(?:street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|court|ct|"
    r"way|place|pl|terrace|ter|circle|cir|parkway|pkwy|trail|trl|highway|hwy)"
)
STREET_RE = re.compile(
    rf"\b\d{{1,6}}\s+(?:[A-Za-z0-9.'-]+\s+){{0,4}}{STREET_TYPES}\.?\b",
    re.IGNORECASE,
)
UNIT_RE = re.compile(
    r"\b(?:apt|apartment|unit|ste|suite)\.?\s*#?\s*\d+[A-Za-z]?\b",
    re.IGNORECASE,
)
POBOX_RE = re.compile(r"\bP\.?\s*O\.?\s*Box\s+\d+\b", re.IGNORECASE)
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b"
)
DOB_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
    r"|\b(?:birthday|date of birth|born on|born|dob)\b",
    re.IGNORECASE,
)
INJECT_RE = re.compile(
    r"(ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions"
    r"|disregard\s+(?:the\s+)?(?:system|previous)"
    r"|you\s+are\s+now\b"
    r"|<\s*/?\s*system\s*>"
    r"|exfiltrate"
    r"|javascript\s*:)",
    re.IGNORECASE,
)
AGE_RE = re.compile(
    r"\bage[d]?\s*:?\s*(\d{1,3})\b"
    r"|\b(\d{1,3})\s*(?:years?\s*old|yo)\b"
    r"|\b(\d{1,3})\s*-\s*years?\s*-\s*old\b",
    re.IGNORECASE,
)
MINOR_RE = re.compile(
    r"\bappears to be a minor\b|\bsubject is a minor\b|\bminor child\b"
    r"|\bunder-?\s*18\b|\bhigh school student\b|\bmiddle school student\b"
    r"|\belementary school student\b",
    re.IGNORECASE,
)
CTA_RE = re.compile(
    r"\b(?:text|sms|call|phone|dial)\b[^\n]{0,40}?\d{3}[-.\s]?\d{4}\b"
    r"|\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b"
    r"|\b\d{3}-\d{4}\b",
    re.IGNORECASE,
)
INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "l.instagram.com",
}

LEXICON: list[tuple[str, re.Pattern[str]]] = [
    (
        "religion",
        re.compile(
            r"\b(?:church|mosque|synagogue|christian|muslim|jewish|catholic|"
            r"baptist|hindu|buddhist|religion|religious|worship(?:per|ping)?|"
            r"congregation)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "familial_status",
        re.compile(
            r"\b(?:teens?|children|kids|pregnan(?:t|cy)|familial status|"
            r"household makeup|minor children)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "disability",
        re.compile(
            r"\b(?:disabilit(?:y|ies)|disabled|wheelchair|special needs)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "national_origin",
        re.compile(
            r"\bnational origin\b"
            r"|\bsurname\b.{0,48}\b(?:suggests|indicates|implies|means)\b"
            r"|\blast name\b.{0,48}\b(?:suggests|indicates|implies)\b"
            r"|\b(?:irish|mexican|chinese|korean|vietnamese|italian|polish|"
            r"nigerian|indian|pakistani|arab|hispanic|latino|latina|asian|"
            r"european|african)\s+(?:origin|descent|heritage|ancestry)\b"
            r"|\bethnicity\b",
            re.IGNORECASE,
        ),
    ),
    (
        "race",
        re.compile(
            r"\brace\b|\bskin colou?r\b|\bpeople of colou?r\b"
            r"|\b(?:white|black|asian|hispanic)\s+(?:client|buyer|seller|"
            r"person|people|family|families)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "color",
        re.compile(r"\bpeople of colou?r\b|\bskin colou?r\b", re.IGNORECASE),
    ),
    (
        "sex",
        re.compile(
            r"\b(?:sexual orientation|gender identity|transgender|lesbian|"
            r"bisexual|gay)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "marital_status",
        re.compile(
            r"\b(?:marital status|married|divorced|widowed|unmarried|"
            r"single (?:mom|mother|dad|father|parent))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "source_of_income",
        re.compile(
            r"\b(?:source of income|section 8|housing voucher|public assistance)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "steering",
        re.compile(
            r"neighborhoods?\s+fit|people like them|good schools"
            r"|schools for (?:kids|families|people)|\bsteering\b",
            re.IGNORECASE,
        ),
    ),
]

WARNING_TEXT = {
    "address_tokens_stripped": "Address-like tokens were removed and were not searched.",
    "email_stripped": "Email-like tokens were removed and were not searched.",
    "phone_stripped": "Phone-like tokens were removed and were not searched.",
    "dob_stripped": "Birth-date tokens were removed and were not searched.",
    "instructions_removed": "Instruction-like lines were removed from untrusted text.",
}

QUERY_CAP = 8
# Six public targets, always. Known profile URLs fill any room left under the cap.
QUERY_TARGETS = (
    {"target": "linkedin", "stem": "LinkedIn", "include_domains": ["linkedin.com"]},
    {"target": "x", "stem": "X", "include_domains": ["x.com", "twitter.com"]},
    {"target": "company", "stem": "company site"},
    {"target": "news", "stem": "news", "category": "news"},
    {"target": "podcast", "stem": "podcast"},
    {"target": "general", "stem": "", "type": "keyword"},
)
SEARCH_UNAVAILABLE = (
    "Search is unavailable. No Exa key is set, so this brief was not filled from a multi-source search."
)
WEB_SEARCH_UNAVAILABLE = "Web search is unavailable."
NOTES_ONLY = (
    "Owner notes can add to a brief that already has public sources. They cannot replace a search."
)
OWN_INTAKE_REQUIRED = (
    "This record has not finished search and identity for its own intake. "
    "Start a fresh intake for a new person."
)
REUSE_NAME = (
    "A later intake is a different person. Name this client to reuse that record."
)
SEARCH_REQUIRED = "Run search first."
NEED_ANCHOR = (
    "Identity confidence is Low. No source matches this company, link, or city plus role or state. "
    "Send a profile link or company."
)
EXA_TOP = 3
EXA_TEXT_CHARS = 1000
EXCERPT_CAP = 1200
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}
CONFIRMED_WORD = re.compile(r"\bconfirmed\b", re.IGNORECASE)
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "phd", "md", "esq"}
NAME_TITLES = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor", "rev",
    "reverend", "hon", "honorable", "sir", "dame", "lady", "lord",
    "capt", "captain", "col", "colonel", "gen", "general", "sgt", "coach",
}
# Both the given name and the surname have to be common. A rare surname is not.
COMMON_GIVEN = frozenset({
    "james", "john", "robert", "michael", "william", "david", "richard", "joseph",
    "thomas", "charles", "christopher", "daniel", "matthew", "anthony", "mark",
    "donald", "steven", "andrew", "paul", "joshua", "kenneth", "kevin", "brian",
    "george", "timothy", "ronald", "edward", "jason", "jeffrey", "ryan", "jacob",
    "gary", "nicholas", "eric", "jonathan", "stephen", "larry", "justin", "scott",
    "brandon", "benjamin", "samuel", "raymond", "gregory", "alexander", "patrick",
    "frank", "jack", "dennis", "jerry", "mary", "patricia", "jennifer", "linda",
    "elizabeth", "barbara", "susan", "jessica", "sarah", "karen",
})
COMMON_SURNAMES = frozenset({
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
    "rodriguez", "martinez", "hernandez", "lopez", "gonzalez", "wilson", "anderson",
    "thomas", "taylor", "moore", "jackson", "martin", "lee", "perez", "thompson",
    "white", "harris", "sanchez", "clark", "ramirez", "lewis", "robinson", "walker",
    "young", "allen", "king", "wright", "scott", "torres", "nguyen", "hill",
    "flores", "green", "adams", "nelson", "baker", "hall", "rivera", "campbell",
    "mitchell", "carter", "roberts",
})
PURGE_DAYS = 90
ARTIFACT_DAYS = 7


# Set while identity, brief, or render runs search in-process. The search
# result stays in the folder; the caller prints its own JSON.
_emit_sink: list[tuple[dict, int]] | None = None


def emit(obj: dict, code: int = 0) -> None:
    if _emit_sink is not None:
        _emit_sink.append((obj, code))
        raise SystemExit(code)
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    raise SystemExit(code)


def fail(error: str, message: str, extra: dict | None = None) -> None:
    obj: dict = {"ok": False, "error": error, "message": message}
    if extra:
        obj.update(extra)
    emit(obj, 1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def data_root() -> Path:
    raw = os.environ.get("CLIENT_PROFILE_ROOT")
    return Path(raw) if raw else Path("/opt/data/client-profile")


def config_path() -> Path:
    return data_root() / "config.json"


def audit_path() -> Path:
    return data_root().parent / "audit" / "client-profile.jsonl"


def _cfg_value(key: str) -> str:
    try:
        cfg = json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return ""
    val = cfg.get(key) if isinstance(cfg, dict) else ""
    return val.strip() if isinstance(val, str) else ""


def artifact_dir() -> Path:
    # The agent's terminal tool runs with a filtered env, so fall back to the
    # values the installer recorded from the box env (served at /f/).
    raw = os.environ.get("ARTIFACT_DIR") or _cfg_value("artifact_dir")
    return Path(raw) if raw else data_root() / "artifacts"


def load_config() -> dict | None:
    path = config_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def mask_owner_number(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "***"
    return "***" + digits[-4:]


def public_config(cfg: dict | None) -> dict | None:
    if not isinstance(cfg, dict):
        return cfg
    shown = dict(cfg)
    shown.pop("consent_required", None)
    if shown.get("exa_api_key"):
        shown["exa_api_key"] = "set"
    if "owner_number" in shown:
        shown["owner_number"] = mask_owner_number(shown.get("owner_number"))
    return shown


def is_enabled() -> bool:
    cfg = load_config()
    return bool(cfg and cfg.get("enabled") is True)


def is_consent_required() -> bool:
    # Existing boxes store consent_required: true. That key must not gate research.
    return False


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def client_path(client_id: str) -> Path | None:
    if not CLIENT_RE.fullmatch(client_id or ""):
        return None
    return data_root() / client_id


def require_client(client_id: str) -> Path:
    path = client_path(client_id)
    if path is None or not (path / "intake.json").is_file():
        fail("unknown_client", "Unknown client id.")
    return path


def audit(action: str, client_id: str | None, counts: dict, actor: str | None) -> None:
    rec = {
        "ts": now_iso(),
        "action": action,
        "client_id": client_id,
        "counts": counts,
        "actor": actor or "unspecified",
    }
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec, separators=(",", ":")) + "\n")


def gate(actor: str | None, *, mutate: bool) -> str:
    if actor == "other":
        fail("owner_only", "This skill runs only for the box owner.")
    if mutate and not is_enabled():
        fail(
            "disabled",
            "Client profile is off. config.json is missing or enabled is false.",
        )
    return actor or "unspecified"


def warning(code: str) -> dict:
    return {"code": code, "message": WARNING_TEXT.get(code, code)}


def unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def redact(text: str) -> tuple[str, list[str]]:
    codes: list[str] = []

    def sub(pattern: re.Pattern[str], code: str, value: str) -> str:
        updated, count = pattern.subn(" ", value)
        if count:
            codes.append(code)
        return updated

    cleaned = text or ""
    cleaned = sub(STREET_RE, "address_tokens_stripped", cleaned)
    cleaned = sub(UNIT_RE, "address_tokens_stripped", cleaned)
    cleaned = sub(POBOX_RE, "address_tokens_stripped", cleaned)
    cleaned = sub(ZIP_RE, "address_tokens_stripped", cleaned)
    cleaned = sub(EMAIL_RE, "email_stripped", cleaned)
    cleaned = sub(PHONE_RE, "phone_stripped", cleaned)
    cleaned = sub(DOB_RE, "dob_stripped", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;-")
    return cleaned, unique(codes)


def strip_instructions(text: str) -> tuple[str, bool]:
    kept: list[str] = []
    removed = False
    for line in (text or "").splitlines():
        if INJECT_RE.search(line):
            removed = True
            continue
        kept.append(line)
    return "\n".join(kept).strip(), removed


def sanitize_untrusted(text: str) -> tuple[str, list[str]]:
    without, injected = strip_instructions(text or "")
    cleaned, codes = redact(without)
    if injected:
        codes.append("instructions_removed")
    return cleaned, unique(codes)


def dangerous_url(url: str) -> bool:
    compact = re.sub(r"\s+", "", url or "").lower()
    return compact.startswith(("javascript:", "data:", "vbscript:", "file:"))


def is_http_url(url: str) -> bool:
    if dangerous_url(url):
        return False
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def is_instagram(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    return host in INSTAGRAM_HOSTS or host.endswith(".instagram.com")


def escape_quotes(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def contains_blocked_token(value: str) -> bool:
    return bool(
        STREET_RE.search(value)
        or UNIT_RE.search(value)
        or POBOX_RE.search(value)
        or ZIP_RE.search(value)
        or EMAIL_RE.search(value)
        or PHONE_RE.search(value)
        or DOB_RE.search(value)
    )


def url_has_blocked_token(url: str) -> bool:
    decoded = unquote(url or "")
    return contains_blocked_token(decoded.replace("-", " ").replace("_", " ").replace("/", " "))


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def guardrail_const(schema: dict | None = None) -> str:
    doc = schema or load_schema()
    return doc["properties"]["guardrail_notice"]["const"]


def resolve_ref(root: dict, ref: str) -> dict:
    node: object = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(ref)
        node = node[part]
    if not isinstance(node, dict):
        raise KeyError(ref)
    return node


def schema_validate(instance: object, schema: dict, path: str, root: dict, errors: list[dict]) -> None:
    if "$ref" in schema:
        schema_validate(instance, resolve_ref(root, schema["$ref"]), path, root, errors)
        return
    if "const" in schema and instance != schema["const"]:
        errors.append({"code": "schema", "path": path, "message": "const mismatch"})
        return
    if "enum" in schema and instance not in schema["enum"]:
        errors.append({"code": "schema", "path": path, "message": "enum mismatch"})
        return
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(instance, dict):
            errors.append({"code": "schema", "path": path, "message": "expected object"})
            return
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append({"code": "schema", "path": f"{path}/{key}", "message": "required"})
        if schema.get("additionalProperties") is False:
            allowed = set((schema.get("properties") or {}).keys())
            for key in instance:
                if key not in allowed:
                    errors.append({"code": "schema", "path": f"{path}/{key}", "message": "unexpected property"})
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in instance:
                schema_validate(instance[key], sub, f"{path}/{key}", root, errors)
        return
    if expected == "array":
        if not isinstance(instance, list):
            errors.append({"code": "schema", "path": path, "message": "expected array"})
            return
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append({"code": "schema", "path": path, "message": "minItems"})
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append({"code": "schema", "path": path, "message": "maxItems"})
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                schema_validate(item, item_schema, f"{path}/{index}", root, errors)
        return
    if expected == "string":
        if not isinstance(instance, str):
            errors.append({"code": "schema", "path": path, "message": "expected string"})
            return
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append({"code": "schema", "path": path, "message": "minLength"})
        return
    if expected == "boolean":
        if not isinstance(instance, bool):
            errors.append({"code": "schema", "path": path, "message": "expected boolean"})
        return


def walk_strings(obj: object, path: str = ""):
    if isinstance(obj, str):
        yield path or "/", obj
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk_strings(value, f"{path}/{index}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk_strings(value, f"{path}/{key}")


def screen_brief(brief: dict) -> list[dict]:
    errors: list[dict] = []
    for path, text in walk_strings(brief):
        if MINOR_RE.search(text):
            errors.append({"code": "minor", "path": path, "message": "Subject appears to be a minor. Stop."})
        for match in AGE_RE.finditer(text):
            raw = next(group for group in match.groups() if group is not None)
            age = int(raw)
            if age < 18:
                errors.append({"code": "minor", "path": path, "message": "Subject appears to be a minor. Stop."})
            else:
                errors.append({"code": "fair_housing", "category": "age", "path": path})
        for category, pattern in LEXICON:
            if pattern.search(text):
                errors.append({"code": "fair_housing", "category": category, "path": path})
        if CTA_RE.search(text):
            errors.append({"code": "outbound_cta", "path": path, "message": "Brief contains a phone number or text-this-number instruction."})
        if STREET_RE.search(text) or POBOX_RE.search(text) or UNIT_RE.search(text):
            errors.append({"code": "street_address", "path": path, "message": "Brief contains a street address."})
        if CONFIRMED_WORD.search(text):
            errors.append({
                "code": "identity_overclaim",
                "path": path,
                "message": "Rate identity confidence High, Medium, or Low.",
            })
    return dedupe_errors(errors)


def dedupe_errors(errors: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for err in errors:
        key = json.dumps(err, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(err)
    return out


def load_evidence(path: Path) -> list[dict]:
    file_path = path / "evidence.jsonl"
    if not file_path.is_file():
        return []
    rows = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def save_evidence(path: Path, rows: list[dict]) -> None:
    file_path = path / "evidence.jsonl"
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    tmp = file_path.with_suffix(".jsonl.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, file_path)


def load_identity(path: Path) -> dict | None:
    file_path = path / "identity.json"
    if not file_path.is_file():
        return None
    data = json.loads(file_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def confirmed_ids(rows: list[dict]) -> set[str]:
    return {row["evidence_id"] for row in rows if row.get("identity_status") == "confirmed"}


def claim_targets(brief: dict) -> list[tuple[str, dict, bool]]:
    """Return (path, object, low_allowed). low_allowed is true only in the appendix."""
    found: list[tuple[str, dict, bool]] = []
    style = brief.get("communication_style")
    if isinstance(style, dict):
        found.append(("/communication_style", style, False))
    for key in ("how_to_communicate", "client_stated", "recommendations"):
        for index, item in enumerate(brief.get(key) or []):
            if isinstance(item, dict):
                found.append((f"/{key}/{index}", item, False))
    for key in ("verified_facts", "observations", "hypotheses"):
        for index, item in enumerate(brief.get(key) or []):
            if isinstance(item, dict):
                found.append((f"/{key}/{index}", item, False))
    for key in ("decision_speed", "yes_to_hear"):
        item = brief.get(key)
        if isinstance(item, dict):
            found.append((f"/{key}", item, False))
    for index, item in enumerate(brief.get("likely_objections") or []):
        if isinstance(item, dict):
            found.append((f"/likely_objections/{index}", item, False))
    play = brief.get("appointment_playbook") or {}
    if isinstance(play, dict):
        opening = play.get("opening")
        if isinstance(opening, dict):
            found.append(("/appointment_playbook/opening", opening, False))
        for index, item in enumerate(play.get("lead_points") or []):
            if isinstance(item, dict):
                found.append((f"/appointment_playbook/lead_points/{index}", item, False))
        pricing = play.get("pricing_conversation")
        if isinstance(pricing, dict):
            found.append(("/appointment_playbook/pricing_conversation", pricing, False))
    appendix = brief.get("appendix") or {}
    if isinstance(appendix, dict):
        for index, item in enumerate(appendix.get("low_confidence") or []):
            if isinstance(item, dict):
                found.append((f"/appendix/low_confidence/{index}", item, True))
    return found


def evaluate_brief(path: Path, brief: dict) -> dict:
    schema = load_schema()
    errors: list[dict] = []
    warnings: list[dict] = []
    schema_validate(brief, schema, "", schema, errors)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "brief": None}
    # A refused search, a missed search, or a search that kept nothing cannot
    # be replaced by owner notes. Stop before a brief is stored.
    if search_needs_anchor(path):
        return {
            "ok": False,
            "errors": [{"code": "need_anchor", "message": NEED_ANCHOR}],
            "warnings": warnings,
            "brief": None,
        }
    if search_missed(path):
        return {
            "ok": False,
            "errors": [{"code": "couldnt_find", "message": "couldn't find"}],
            "warnings": warnings,
            "brief": None,
        }
    identity = load_identity(path)
    if not identity or identity.get("status") != "confirmed":
        return {
            "ok": False,
            "errors": [{"code": "identity_not_confirmed", "message": "No brief until the owner picks a candidate."}],
            "warnings": warnings,
            "brief": None,
        }
    errors.extend(screen_brief(brief))
    rows = load_evidence(path)
    known = {row["evidence_id"]: row for row in rows}
    confirmed = confirmed_ids(rows)
    style = brief["communication_style"]
    disc = style["disc_hypothesis"].strip()
    insufficient = disc.lower() == "insufficient evidence"
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    parts = split_name(intake.get("name") or "")
    if not parts:
        errors.append({"code": "couldnt_find", "message": "couldn't find"})
    else:
        first, last = parts
        candidate = int(identity.get("candidate") or 0)
        sources = full_name_source_count(rows, candidate, first, last)
        matches = web_match_count(rows, first, last)
        allowed = allowed_identity_level(sources, matches)
        if search_conflicts(path):
            allowed = "low"
        claimed = brief["identity_match"]["level"]
        if LEVEL_RANK[claimed] > LEVEL_RANK[allowed]:
            brief["identity_match"]["level"] = allowed
            warnings.append({
                "code": "identity_downgraded",
                "path": "/identity_match/level",
                "from": claimed,
                "to": allowed,
            })
    search_doc = load_search(path)
    public_confirmed = any(
        row.get("identity_status") == "confirmed" and row.get("origin") == "web" for row in rows
    )
    if search_doc and search_doc.get("status") == "unavailable":
        errors.append({"code": "search_unavailable", "message": SEARCH_UNAVAILABLE})
        if any(row.get("origin") == "web" for row in rows):
            errors.append({"code": "thin_without_search", "message": SEARCH_UNAVAILABLE})
    elif not public_confirmed:
        errors.append({"code": "notes_only", "message": NOTES_ONLY})
    elif search_doc and search_doc.get("status") == "done":
        cited_urls = set()
        for source in (brief.get("appendix") or {}).get("sources") or []:
            if isinstance(source, dict) and source.get("url"):
                cited_urls.add(canon_url(source["url"]))
        confirmed_urls = {
            canon_url(row.get("url") or "")
            for row in rows
            if row.get("identity_status") == "confirmed" and row.get("url")
        }
        for source in search_doc.get("sources") or []:
            url = source.get("url") or ""
            # Other people's profiles stay in search.json. Cite only the person who was picked.
            if not url or canon_url(url) not in confirmed_urls:
                continue
            if canon_url(url) not in cited_urls:
                errors.append({"code": "uncited_source", "path": "/appendix/sources", "url": url})
    if insufficient:
        if style.get("confidence") != "low":
            previous = style.get("confidence")
            style["confidence"] = "low"
            warnings.append({
                "code": "confidence_downgraded",
                "path": "/communication_style/confidence",
                "from": previous,
                "to": "low",
            })
    elif "hypothesis" not in disc.lower():
        errors.append({"code": "disc_not_labeled_hypothesis", "path": "/communication_style/disc_hypothesis"})
    play = brief["appointment_playbook"]
    if intake.get("type") == "listing" and "pricing_conversation" not in play:
        errors.append({"code": "pricing_conversation_required", "path": "/appointment_playbook/pricing_conversation"})
    for claim_path, claim, low_allowed in claim_targets(brief):
        ids = claim.get("evidence_ids") or []
        distinct = []
        for evidence_id in ids:
            if evidence_id not in distinct:
                distinct.append(evidence_id)
        if claim_path == "/communication_style" and insufficient:
            continue
        if not distinct:
            errors.append({"code": "uncited_trait", "path": claim_path})
            continue
        for evidence_id in distinct:
            row = known.get(evidence_id)
            if row is None:
                errors.append({"code": "unknown_evidence", "path": claim_path, "evidence_id": evidence_id})
            elif row.get("identity_status") != "confirmed" or evidence_id not in confirmed:
                errors.append({"code": "unconfirmed_evidence", "path": claim_path, "evidence_id": evidence_id})
        confidence = claim.get("confidence")
        if confidence == "high" and len(distinct) < 2:
            claim["confidence"] = "medium"
            warnings.append({"code": "confidence_downgraded", "path": claim_path + "/confidence", "from": "high", "to": "medium"})
            confidence = "medium"
        if confidence == "low" and not low_allowed:
            errors.append({"code": "low_confidence_outside_appendix", "path": claim_path})
    appendix = brief.get("appendix") or {}
    for index, source in enumerate(appendix.get("sources") or []):
        evidence_id = source.get("evidence_id")
        row = known.get(evidence_id)
        if row is None or row.get("identity_status") != "confirmed":
            errors.append({"code": "unconfirmed_evidence", "path": f"/appendix/sources/{index}", "evidence_id": evidence_id})
        if not is_http_url(source.get("url") or ""):
            errors.append({"code": "rejected_url", "path": f"/appendix/sources/{index}"})
    errors = dedupe_errors(errors)
    # A brief can be stored only after this folder finished its own search
    # and identity. A copied record from another person does not count.
    if not errors and not own_pipeline_complete(path):
        errors.append({"code": "own_intake_required", "message": OWN_INTAKE_REQUIRED})
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "brief": None}
    return {"ok": True, "errors": [], "warnings": warnings, "brief": brief}


def html_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def cited_html(item: object) -> str:
    if not isinstance(item, dict):
        return "<p>None recorded.</p>"
    text = html_escape(item.get("text") or "")
    ids = ", ".join(html_escape(i) for i in item.get("evidence_ids") or [])
    cite = f" <span class=\"cite\">{ids}</span>" if ids else ""
    return f"<p>{text}{cite}</p>"


def render_items(items: list) -> str:
    if not items:
        return "<p>None recorded.</p>"
    parts = ["<ul>"]
    for item in items:
        if isinstance(item, str):
            parts.append(f"<li>{html_escape(item)}</li>")
            continue
        text = html_escape(item.get("text") or "")
        ids = ", ".join(html_escape(i) for i in item.get("evidence_ids") or [])
        conf = item.get("confidence")
        extra = f" <span class=\"conf\">{html_escape(conf)}</span>" if conf else ""
        cite = f" <span class=\"cite\">{ids}</span>" if ids else ""
        parts.append(f"<li>{text}{extra}{cite}</li>")
    parts.append("</ul>")
    return "".join(parts)


def fill_template(template: str, mapping: dict[str, str]) -> str:
    pattern = re.compile("|".join(re.escape(key) for key in mapping))

    def repl(match: re.Match[str]) -> str:
        return mapping[match.group(0)]

    return pattern.sub(repl, template)


def build_html(path: Path, brief: dict) -> str:
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    play = brief["appointment_playbook"]
    style = brief["communication_style"]
    appt = intake.get("appt_at") or ""
    appt_html = f" · {html_escape(appt)}" if appt else ""
    pricing = play.get("pricing_conversation")
    if pricing:
        pricing_html = f"<h2>Pricing conversation</h2><p>{html_escape(pricing.get('text') or '')}</p>"
    elif intake.get("type") == "listing":
        pricing_html = "<h2>Pricing conversation</h2><p>Missing.</p>"
    else:
        pricing_html = ""
    search_doc = load_search(path)
    if search_doc and search_doc.get("status") == "unavailable":
        search_notice = f"<p class=\"banner\">{html_escape(SEARCH_UNAVAILABLE)}</p>"
    elif search_doc and search_doc.get("status") == "done":
        notice = (
            f"Searched {search_doc.get('query_count')} public queries and kept "
            f"{search_doc.get('source_count')} sources."
        )
        note = search_doc.get("excluded_note") or ""
        if isinstance(note, str) and note.strip():
            notice = notice + " " + note.strip()
        search_notice = "<p class=\"banner\">" + html_escape(notice) + "</p>"
    elif search_doc and search_doc.get("status") == "need_anchor":
        search_notice = "<p class=\"banner\">" + html_escape(search_doc.get("message") or NEED_ANCHOR) + "</p>"
    else:
        search_notice = ""
    mapping = {
        "{{NAME}}": html_escape(intake.get("name") or ""),
        "{{CITY}}": html_escape(intake.get("city") or ""),
        "{{APPT_TYPE}}": html_escape(intake.get("type") or ""),
        "{{APPT_AT}}": appt_html,
        "{{GUARDRAIL}}": html_escape(brief.get("guardrail_notice") or ""),
        "{{SEARCH_NOTICE}}": search_notice,
        "{{SNAPSHOT}}": html_escape(brief.get("snapshot") or ""),
        "{{IDENTITY_LEVEL}}": html_escape(show_level((brief.get("identity_match") or {}).get("level") or "")),
        "{{IDENTITY_BASIS}}": html_escape((brief.get("identity_match") or {}).get("basis") or ""),
        "{{DECISION_SPEED}}": cited_html(brief.get("decision_speed")),
        "{{YES_TO_HEAR}}": cited_html(brief.get("yes_to_hear")),
        "{{OBJECTIONS}}": render_items(brief.get("likely_objections") or []),
        "{{DISC}}": html_escape(style.get("disc_hypothesis") or ""),
        "{{DISC_CONFIDENCE}}": html_escape(style.get("confidence") or ""),
        "{{HOW}}": render_items(brief.get("how_to_communicate") or []),
        "{{OPENING}}": html_escape((play.get("opening") or {}).get("text") or ""),
        "{{LEADS}}": render_items(play.get("lead_points") or []),
        "{{QUESTIONS}}": render_items(play.get("questions") or []),
        "{{AVOID}}": render_items(play.get("avoid") or []),
        "{{CLOSE}}": html_escape(play.get("close") or ""),
        "{{PRICING}}": pricing_html,
        "{{VERIFIED}}": render_items(brief.get("verified_facts") or []),
        "{{STATED}}": render_items(brief.get("client_stated") or []),
        "{{OBSERVATIONS}}": render_items(brief.get("observations") or []),
        "{{HYPOTHESES}}": render_items(brief.get("hypotheses") or []),
        "{{RECOMMENDATIONS}}": render_items(brief.get("recommendations") or []),
        "{{UNKNOWNS}}": render_items(brief.get("what_we_dont_know") or []),
        "{{APPENDIX}}": render_items((brief.get("appendix") or {}).get("low_confidence") or []),
        "{{SOURCES}}": render_sources(cited_sources(brief)),
    }
    return fill_template(TEMPLATE_PATH.read_text(encoding="utf-8"), mapping)


def cited_sources(brief: dict) -> list:
    """Appendix on the page is the sources the brief actually cites, not every hit."""
    sources = (brief.get("appendix") or {}).get("sources") or []
    if not isinstance(sources, list):
        return []
    cited: set[str] = set()
    for _path, claim, _low in claim_targets(brief):
        for evidence_id in claim.get("evidence_ids") or []:
            if isinstance(evidence_id, str) and evidence_id:
                cited.add(evidence_id)
    if not cited:
        return [source for source in sources if isinstance(source, dict)]
    return [
        source for source in sources
        if isinstance(source, dict) and source.get("evidence_id") in cited
    ]


def render_sources(sources: list) -> str:
    if not sources:
        return "<p>None recorded.</p>"
    parts = ['<ul class="sources">']
    for source in sources:
        title = html_escape(source.get("title") or "")
        url = html_escape(source.get("url") or "")
        evidence_id = html_escape(source.get("evidence_id") or "")
        parts.append(f"<li>{title} <span class=\"cite\">{evidence_id} {url}</span></li>")
    parts.append("</ul>")
    return "".join(parts)


def weasyprint_binary() -> str | None:
    override = os.environ.get("WEASYPRINT_BIN", "").strip()
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        return None
    binary = "/usr/bin/weasyprint"
    if os.path.isfile(binary) and os.access(binary, os.X_OK):
        return binary
    return None


def _pdfinfo_pages(path: Path) -> int | None:
    binary = shutil.which("pdfinfo")
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            tail = line.split(":", 1)[-1].strip()
            if tail.isdigit() and int(tail) > 0:
                return int(tail)
    return None


def _pdf_inflated(data: bytes) -> bytes:
    """Join the file with its FlateDecode streams so page objects are visible.

    WeasyPrint compresses /Type /Page into object streams. pdfinfo still counts
    those pages. A raw regex on the compressed bytes does not.
    """
    parts = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = match.group(1)
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                parts.append(zlib.decompress(raw, wbits))
                break
            except zlib.error:
                continue
    return b"\n".join(parts)


def pdf_page_count(path: Path) -> int | None:
    """Return the page count pdfinfo prints as Pages."""
    reported = _pdfinfo_pages(path)
    if reported:
        return reported
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"%PDF-"):
        return None
    count = len(re.findall(rb"/Type\s*/Page(?!s)", _pdf_inflated(data)))
    return count or None


_REAL_WEASY: dict[str, bool] = {}


def real_weasyprint(binary: str) -> bool:
    cached = _REAL_WEASY.get(binary)
    if cached is not None:
        return cached
    try:
        text = Path(binary).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    ok = "weasyprint" in text.lower()
    _REAL_WEASY[binary] = ok
    return ok


def weasyprint_document_pages(html_path: Path, pdf_path: Path) -> int | None:
    """Render a PDF and return the page count pdfinfo would print.

    len(document.pages) can disagree with the file pdfinfo reads. The count
    used for trimming and the JSON pages field is the written PDF's count.
    None means no PDF was written, or the converter was a stub that does not
    report pages. Callers then fall back to estimate_pages.
    """
    binary = weasyprint_binary()
    if not binary:
        return None
    if pdf_path.exists():
        pdf_path.unlink()

    def file_pages() -> int | None:
        if pdf_path.is_file() and pdf_path.stat().st_size > 0:
            return pdf_page_count(pdf_path)
        return None

    if real_weasyprint(binary):
        code = (
            "import sys\n"
            "from weasyprint import HTML\n"
            "document = HTML(filename=sys.argv[1]).render()\n"
            "document.write_pdf(sys.argv[2])\n"
            "print(len(document.pages))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code, str(html_path), str(pdf_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            proc = None
        if proc is not None and proc.returncode == 0 and pdf_path.is_file():
            counted = file_pages()
            if counted:
                return counted
            lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
            if lines and lines[-1].isdigit():
                return int(lines[-1])
        if pdf_path.exists():
            pdf_path.unlink()
        try:
            proc = subprocess.run(
                [binary, "--uncompressed-pdf", str(html_path), str(pdf_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode == 0 and pdf_path.is_file():
            return file_pages()
        return None
    try:
        proc = subprocess.run(
            [binary, str(html_path), str(pdf_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not pdf_path.is_file():
        return None
    return file_pages()


def parse_flags(args: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    positional: list[str] = []
    opts: dict[str, list[str]] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            positional.extend(args[index + 1 :])
            break
        if token.startswith("--"):
            body = token[2:]
            if "=" in body:
                key, value = body.split("=", 1)
                opts.setdefault(key, []).append(value)
                index += 1
                continue
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                opts.setdefault(body, []).append("true")
                index += 1
                continue
            opts.setdefault(body, []).append(args[index + 1])
            index += 2
            continue
        positional.append(token)
        index += 1
    return positional, opts


def flag(opts: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = opts.get(name)
    if not values:
        return default
    return values[-1]


def actor_of(opts: dict[str, list[str]]) -> str | None:
    return flag(opts, "actor")


def reject_address_flag(argv: list[str]) -> None:
    for token in argv:
        if token == "--address" or token.startswith("--address="):
            fail("no_address_field", "Street address is not collected.")


def name_tokens(name: str) -> list[str]:
    raw_tokens: list[str] = []
    for raw in re.split(r"\s+", (name or "").strip()):
        cleaned = raw.strip(".,;:\"'`“”")
        if cleaned:
            raw_tokens.append(cleaned)
    while raw_tokens and raw_tokens[0].casefold().rstrip(".") in NAME_TITLES:
        raw_tokens.pop(0)
    tokens: list[str] = []
    for cleaned in raw_tokens:
        if cleaned.casefold().rstrip(".") in NAME_SUFFIXES:
            continue
        tokens.append(cleaned)
    return tokens


def split_name(name: str) -> tuple[str, str] | None:
    tokens = name_tokens(name)
    if len(tokens) < 2:
        return None
    return tokens[0], tokens[-1]


def word_present(text: str, word: str) -> bool:
    if not word:
        return False
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text or "", re.IGNORECASE) is not None


def full_name_match(text: str, first: str, last: str) -> bool:
    return word_present(text, first) and word_present(text, last)


def is_common_name(first: str, last: str) -> bool:
    return first.casefold() in COMMON_GIVEN and last.casefold() in COMMON_SURNAMES


def has_profile_url(intake: dict, rows: list[dict] | None = None) -> bool:
    urls = [url for url in (intake.get("urls") or []) if isinstance(url, str)]
    for row in rows or []:
        # Search hits do not count. A link the advisor added does.
        if row.get("via") == "exa" or row.get("origin") != "web":
            continue
        if isinstance(row.get("url"), str):
            urls.append(row["url"])
    return any(is_http_url(url) and not is_instagram(url) for url in urls)


def row_name_match(row: dict, first: str, last: str) -> bool:
    if row.get("identity_status") == "inaccessible":
        return False
    if row.get("origin") == "manual":
        return True
    blob = f"{row.get('title') or ''} {row.get('excerpt') or ''}"
    return full_name_match(blob, first, last)


def full_name_source_count(rows: list[dict], candidate: int, first: str, last: str) -> int:
    keys: list[str] = []
    for row in rows:
        if int(row.get("candidate") or 0) != candidate:
            continue
        if row.get("identity_status") != "confirmed":
            continue
        blob = f"{row.get('title') or ''} {row.get('excerpt') or ''}"
        if not full_name_match(blob, first, last):
            continue
        key = (row.get("url") or "").strip() or str(row.get("evidence_id") or "")
        if key and key not in keys:
            keys.append(key)
    return len(keys)


def web_match_count(rows: list[dict], first: str, last: str) -> int:
    numbers: list[int] = []
    for row in rows:
        if row.get("origin") == "manual" or row.get("identity_status") == "inaccessible":
            continue
        blob = f"{row.get('title') or ''} {row.get('excerpt') or ''}"
        if not full_name_match(blob, first, last):
            continue
        number = int(row.get("candidate") or 0)
        if number not in numbers:
            numbers.append(number)
    return len(numbers)


def allowed_identity_level(source_count: int, match_count: int) -> str:
    # High needs two or more full-name sources and fewer than three people.
    # A single source, or three or more candidate matches, is never high.
    if source_count >= 2 and match_count < 3:
        return "high"
    if source_count >= 2 and match_count >= 3:
        return "medium"
    if source_count == 1 and match_count < 3:
        return "medium"
    return "low"


def show_level(level: str) -> str:
    return {"high": "High", "medium": "Medium", "low": "Low"}.get((level or "").lower(), "Low")


def visible_text(html: str) -> str:
    visible = re.sub(r"<style\b[^>]*>.*?</style>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    visible = re.sub(r"<script\b[^>]*>.*?</script>", " ", visible, flags=re.IGNORECASE | re.DOTALL)
    plain = re.sub(r"<[^>]+>", " ", visible)
    return re.sub(r"\s+", " ", plain).strip()


def estimate_pages(html: str) -> int:
    # Fallback only, used when WeasyPrint did not report a document page count.
    # Stylesheet text is not copy. Counting it made a one-page brief look like two.
    plain = visible_text(html)
    return 1 if len(plain) <= 3800 else (1 + (len(plain) - 1) // 3800)


def trim_one_bullet(brief: dict) -> bool:
    """Drop one lowest-value bullet. Keep every section's last required item and 3 sources."""
    steps = (
        ("what_we_dont_know", None, 1),
        ("appointment_playbook", "avoid", 1),
        ("appointment_playbook", "questions", 1),
        ("how_to_communicate", None, 1),
        ("likely_objections", None, 1),
        ("recommendations", None, 1),
        ("hypotheses", None, 1),
        ("observations", None, 1),
        ("verified_facts", None, 1),
        ("client_stated", None, 1),
        ("appendix", "sources", 3),
    )
    for parent, child, minimum in steps:
        box = brief.get(parent)
        if child is None:
            items = box
        elif isinstance(box, dict):
            items = box.get(child)
        else:
            items = None
        if isinstance(items, list) and len(items) > minimum:
            items.pop()
            return True
    return shorten_one_prose(brief)


def shorten_one_prose(brief: dict) -> bool:
    """Shorten the longest prose field once. Leave a readable remainder."""
    targets: list[tuple[dict, str, int]] = []

    def add(box: object, key: str, floor: int) -> None:
        if isinstance(box, dict):
            text = box.get(key)
            if isinstance(text, str) and len(text) > floor:
                targets.append((box, key, floor))

    add(brief, "snapshot", 90)
    add(brief.get("identity_match"), "basis", 48)
    add(brief.get("decision_speed"), "text", 48)
    add(brief.get("yes_to_hear"), "text", 48)
    play = brief.get("appointment_playbook")
    if isinstance(play, dict):
        add(play.get("opening"), "text", 48)
        add(play, "close", 48)
        add(play.get("pricing_conversation"), "text", 48)
    if not targets:
        return False
    box, key, floor = max(targets, key=lambda item: len(item[0][item[1]]))
    text = box[key].strip()
    parts = [part for part in re.split(r"(?<=[.!?])\s+", text) if part]
    if len(parts) >= 2 and len(" ".join(parts[:-1])) >= floor:
        shortened = " ".join(parts[:-1])
    elif len(text) > floor:
        shortened = text[:floor].rstrip(" ,;:") + "…"
    else:
        return False
    if len(shortened) >= len(text):
        return False
    box[key] = shortened
    return True


def build_queries(name: str, city: str, urls: list[str], company: str = "") -> tuple[list[dict], list[dict], list[str]]:
    codes: list[str] = []
    clean_name, name_codes = redact(name)
    clean_city, city_codes = redact(city)
    clean_company, company_codes = redact(company) if company else ("", [])
    codes.extend(name_codes)
    codes.extend(city_codes)
    codes.extend(company_codes)
    if (
        contains_blocked_token(clean_name)
        or contains_blocked_token(clean_city)
        or contains_blocked_token(clean_company)
    ):
        fail("address_token_in_query", "A query would have contained a blocked token.")
    queries: list[dict] = []
    quoted_name = escape_quotes(clean_name)
    quoted_city = escape_quotes(clean_city)
    quoted_company = escape_quotes(clean_company)
    company_bit = f' "{quoted_company}"' if clean_company else ""
    for spec in QUERY_TARGETS:
        stem = spec["stem"]
        if clean_name and clean_city:
            text = f'"{quoted_name}" "{quoted_city}"{company_bit}' + (f" {stem}" if stem else "")
        elif clean_name:
            text = f'"{quoted_name}"{company_bit}' + (f" {stem}" if stem else "")
        else:
            continue
        item = {"q": text, "target": spec["target"]}
        if spec.get("include_domains"):
            item["include_domains"] = list(spec["include_domains"])
        if spec.get("category"):
            item["category"] = spec["category"]
        if spec.get("type"):
            item["type"] = spec["type"]
        queries.append(item)
    company_hosts: list[str] = []
    for url in urls:
        if not isinstance(url, str) or not is_http_url(url) or is_instagram(url):
            continue
        host = host_of(url)
        if host and host not in SOCIAL_HOSTS and host not in company_hosts:
            company_hosts.append(host)
    if company_hosts:
        for item in queries:
            if item.get("target") == "company" and "include_domains" not in item:
                item["include_domains"] = company_hosts[:3]
    inaccessible: list[dict] = []
    for url in urls:
        if url_has_blocked_token(url):
            codes.append("address_tokens_stripped")
            continue
        if is_instagram(url):
            inaccessible.append({
                "url": url,
                "reason": "private_or_login_walled_instagram",
                "fetched": False,
            })
            continue
        if not is_http_url(url):
            continue
        if len(queries) >= QUERY_CAP:
            break
        if clean_company:
            queries.append({"q": f'"{quoted_name}" "{quoted_company}" {url}', "target": "url"})
        else:
            queries.append({"q": f'"{quoted_name}" {url}', "target": "url"})
    safe = []
    for item in queries[:QUERY_CAP]:
        text = item["q"]
        url_part = text.split(" ", 1)[-1] if text.count(" ") else ""
        body = text
        if url_part.startswith("http://") or url_part.startswith("https://"):
            body = text[: text.rfind(url_part)]
        if contains_blocked_token(body):
            fail("address_token_in_query", "A query would have contained a blocked token.")
        safe.append(item)
    listed = []
    for index, item in enumerate(safe):
        row = dict(item)
        row["id"] = f"q{index + 1}"
        listed.append(row)
    return listed, inaccessible, unique(codes)


def cmd_selftest() -> None:
    checks = []
    cfg = load_config()
    checks.append({"name": "config", "ok": cfg is not None})
    checks.append({"name": "enabled", "ok": bool(cfg and cfg.get("enabled") is True)})
    data_ok = True
    try:
        data_root().mkdir(parents=True, exist_ok=True)
        probe = data_root() / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        data_ok = False
    checks.append({"name": "data_dir", "ok": data_ok})
    schema_ok = False
    try:
        schema = load_schema()
        schema_ok = schema.get("title") == "Client profile brief" and "guardrail_notice" in schema.get("properties", {})
    except (OSError, json.JSONDecodeError, KeyError):
        schema_ok = False
    checks.append({"name": "schema", "ok": schema_ok})
    checks.append({"name": "template", "ok": TEMPLATE_PATH.is_file()})
    checks.append({"name": "public_research", "ok": is_consent_required() is False})
    checks.append({"name": "exa", "ok": True, "present": bool(exa_key())})
    present = os.path.isfile("/usr/bin/weasyprint") and os.access("/usr/bin/weasyprint", os.X_OK)
    checks.append({"name": "weasyprint", "ok": True, "present": present})
    required = [c for c in checks if c["name"] != "weasyprint"]
    emit({"ok": all(c["ok"] for c in required), "checks": checks})


def cmd_status() -> None:
    cfg = load_config()
    count = 0
    root = data_root()
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and (child / "intake.json").is_file():
                count += 1
    emit({
        "ok": True,
        "enabled": bool(cfg and cfg.get("enabled") is True),
        "client_count": count,
        "config": public_config(cfg),
    })


def cmd_intake(opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    name = flag(opts, "name")
    city = flag(opts, "city")
    appt_type = (flag(opts, "type") or "").lower()
    if not name or not name.strip():
        fail("missing_name", "Name is required.")
    if not city or not city.strip():
        fail("missing_city", "City is required.")
    if appt_type not in {"buyer", "listing", "other"}:
        fail("bad_type", "Type must be buyer, listing, or other.")
    urls = opts.get("url") or []
    for url in urls:
        if dangerous_url(url) or not is_http_url(url):
            fail("rejected_url", "Only http(s) URLs are accepted.")
    company = flag(opts, "company") or ""
    role = flag(opts, "role") or ""
    clean_name, name_codes = redact(name)
    clean_city, city_codes = redact(city)
    clean_company, company_codes = redact(company) if company else ("", [])
    clean_role, role_codes = redact(role) if role else ("", [])
    codes = unique(name_codes + city_codes + company_codes + role_codes)
    if not clean_name:
        fail("name_empty_after_redaction", "Name was empty after removing blocked tokens.")
    if not clean_city:
        fail("city_empty_after_redaction", "City was empty after removing blocked tokens.")
    tz_name = flag(opts, "tz")
    if tz_name:
        try:
            ZoneInfo(tz_name)
        except Exception:
            fail("bad_tz", "Timezone must be an IANA name.")
    appt_at = flag(opts, "appt-at")
    if appt_at:
        try:
            parsed = datetime.fromisoformat(appt_at.replace("Z", "+00:00"))
        except ValueError:
            fail("bad_appt_at", "appt-at must be ISO-8601.")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        appt_at = parsed.isoformat()
    inaccessible = []
    stored_urls = []
    for url in urls:
        if is_instagram(url):
            inaccessible.append({"url": url, "reason": "private_or_login_walled_instagram", "fetched": False})
        else:
            stored_urls.append(url)
    client_id = "c" + secrets.token_hex(8)
    folder = data_root() / client_id
    folder.mkdir(parents=True, exist_ok=False)
    intake = {
        "name": clean_name,
        "city": clean_city,
        "type": appt_type,
        "urls": stored_urls,
        "company": clean_company,
        "role": clean_role,
        "inaccessible_urls": inaccessible,
        "appt_at": appt_at,
        "tz": tz_name,
        "created_at": now_iso(),
        "address_tokens_stripped": "address_tokens_stripped" in codes,
    }
    write_json(folder / "intake.json", intake)
    audit("intake", client_id, {"clients": 1}, actor)
    result: dict = {"ok": True, "client_id": client_id}
    if codes:
        result["warnings"] = [warning(code) for code in codes]
    if inaccessible:
        result["inaccessible"] = inaccessible
    emit(result)


def cmd_queries(client_id: str, opts: dict[str, list[str]]) -> None:
    gate(actor_of(opts), mutate=False)
    if not is_enabled():
        fail("disabled", "Client profile is off. config.json is missing or enabled is false.")
    path = require_client(client_id)
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    urls = list(intake.get("urls") or [])
    for item in intake.get("inaccessible_urls") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    queries, inaccessible, codes = build_queries(
        intake.get("name") or "",
        intake.get("city") or "",
        urls,
        intake.get("company") or "",
    )
    if not queries:
        fail("no_queries", "No safe name-and-city query could be built.")
    result: dict = {"ok": True, "queries": queries}
    if inaccessible:
        result["inaccessible"] = inaccessible
    if codes:
        result["warnings"] = [warning(code) for code in codes]
    emit(result)


def exa_key() -> str:
    env = os.environ.get("EXA_API_KEY", "").strip()
    if env:
        return env
    return _cfg_value("exa_api_key")


def exa_base() -> str:
    """API root. EXA_API_BASE, then EXA_BASE_URL, then config exa_base_url, then api.exa.ai.

    A proxy value may already end in /search. That segment is removed here so
    /search and /contents are joined once, with no doubled slash.
    config.json may carry exa_base_url. The key is EXA_API_KEY, then exa_api_key.
    """
    chosen = ""
    for name in ("EXA_API_BASE", "EXA_BASE_URL"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            chosen = raw
            break
    if not chosen:
        chosen = _cfg_value("exa_base_url")
    if not chosen:
        chosen = "https://api.exa.ai"
    root = chosen.rstrip("/")
    if root.lower().endswith("/search"):
        root = root[: -len("/search")].rstrip("/")
    return root or "https://api.exa.ai"


def exa_url(path: str) -> str:
    endpoint = path if path.startswith("/") else "/" + path
    return exa_base() + endpoint


def canon_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"{host}{path}"


class ExaError(Exception):
    """Exa refused the call or returned a body this skill cannot use."""


def exa_post(path: str, payload: dict, key: str) -> dict:
    req = urllib.request.Request(
        exa_url(path),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "advisorreach-client-profile",
            "x-api-key": key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ExaError(f"Exa returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExaError("Exa could not be reached.") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExaError("Exa returned a non-JSON response.") from exc
    if not isinstance(parsed, dict):
        raise ExaError("Exa returned an unexpected response.")
    return parsed


def exa_search_body(query: dict) -> dict:
    body: dict = {
        "query": query["q"],
        "numResults": EXA_TOP,
        "type": query.get("type") or "auto",
        "contents": {
            "text": {"maxCharacters": EXA_TEXT_CHARS},
            # highlights is a string array on the response. numSentences is
            # deprecated and was not returning the employer sentence. The
            # query steers that array at this search. extras.links is how a
            # company page returns linkedin.com/in/<handle> when the text does not.
            "highlights": {"maxCharacters": 2000, "query": query["q"]},
            "extras": {"links": 10},
        },
    }
    domains = query.get("include_domains")
    if domains:
        body["includeDomains"] = domains
    if query.get("category"):
        body["category"] = query["category"]
    return body


def result_text(row: dict) -> str:
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        return text
    bits = text_bits(text)
    if bits:
        return " ".join(bits)
    return result_snippet(row)


def text_bits(value: object) -> list[str]:
    """Strings from Exa text, highlight, or entity fields, including wrapped objects."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        bits: list[str] = []
        for key in ("text", "snippet", "highlight", "summary", "name", "company"):
            bits.extend(text_bits(value.get(key)))
        return bits
    if isinstance(value, list):
        bits = []
        for item in value:
            bits.extend(text_bits(item))
        return bits
    return []


# Scores and ids are not page text. Every other string is, including a company
# name that Exa puts under entities, extras.links, or a nested highlight.
CORPUS_SKIP = {
    "score",
    "highlightScores",
    "highlight_scores",
    "id",
    "publishedDate",
    "published_date",
    "image",
    "favicon",
    "costDollars",
}


def harvest_strings(value: object, key: str | None = None) -> list[str]:
    if key in CORPUS_SKIP:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        found: list[str] = []
        for child_key, child in value.items():
            found.extend(harvest_strings(child, str(child_key)))
        return found
    if isinstance(value, list):
        found = []
        for child in value:
            found.extend(harvest_strings(child, key))
        return found
    return []


def result_corpus(row: dict) -> str:
    """Every string Exa returned for the page, not only title and opening text."""
    return " ".join(harvest_strings(row))


def result_snippet(row: dict) -> str:
    """Employer and query matches that may sit outside the opening text."""
    parts: list[str] = []
    for key in ("snippet", "summary", "author", "company", "employer", "highlights", "entities", "extras", "subpages"):
        parts.extend(harvest_strings(row.get(key), key))
    return " ".join(parts)


def mentioned_linkedin_handles(text: str) -> set[str]:
    """Profile handles linked from a page, including /in/dkmarshall on a company site."""
    found: set[str] = set()
    for match in re.finditer(r"linkedin\.com/(?:in|posts)/([A-Za-z0-9%]{3,})", text or "", re.IGNORECASE):
        token = unquote(match.group(1)).split("_", 1)[0].strip().casefold()
        if token in {"company", "feed", "posts", "pub", "school", "showcase"}:
            continue
        if len(token) >= 3:
            found.add(token)
    return found


def load_search(path: Path) -> dict | None:
    file_path = path / "search.json"
    if not file_path.is_file():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def search_missed(path: Path) -> bool:
    doc = load_search(path)
    if not doc:
        return False
    if doc.get("status") == "couldnt_find":
        return True
    return doc.get("status") == "done" and int(doc.get("source_count") or 0) == 0


def search_needs_anchor(path: Path) -> bool:
    doc = load_search(path)
    return bool(doc and doc.get("status") == "need_anchor")


def search_file_missing(path: Path) -> bool:
    return not (path / "search.json").is_file()


def require_search_file(path: Path) -> None:
    if search_file_missing(path):
        fail("search_required", SEARCH_REQUIRED)


def ensure_search(client_id: str, path: Path, opts: dict[str, list[str]]) -> None:
    """Run search when a later step was called before it. Never call that a miss."""
    global _emit_sink
    existing = load_search(path)
    if existing:
        # A 401 or network failure already stamped the file. That is not a miss.
        # Ask for op:search, which sees the box Exa env. A missing key keeps its own message.
        if existing.get("message") == WEB_SEARCH_UNAVAILABLE:
            fail("search_required", SEARCH_REQUIRED)
        return
    # No Exa key means the search itself cannot run. Do not write couldnt_find.
    if not exa_key():
        require_search_file(path)
    sink: list[tuple[dict, int]] = []
    previous = _emit_sink
    _emit_sink = sink
    try:
        cmd_search(client_id, opts)
    except SystemExit:
        pass
    finally:
        _emit_sink = previous
    if not sink:
        fail("search_required", SEARCH_REQUIRED)
    payload, code = sink[-1]
    if code:
        error = payload.get("error") if isinstance(payload, dict) else ""
        message = payload.get("message") if isinstance(payload, dict) else ""
        # A 401 or network failure is not a miss. Ask for op:search, which sees the box Exa env.
        if error == "search_unavailable":
            fail("search_required", SEARCH_REQUIRED)
        if not (path / "search.json").is_file():
            fail(str(error or "search_required"), str(message or SEARCH_REQUIRED))


def search_conflicts(path: Path) -> bool:
    doc = load_search(path)
    return bool(doc and doc.get("conflict") is True)


def names_equal(left: str, right: str) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def stored_name(path: Path) -> str:
    try:
        intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(intake, dict):
        return ""
    name = intake.get("name")
    return name if isinstance(name, str) else ""


def stamp_search(path: Path, doc: dict) -> None:
    doc["intake_name"] = stored_name(path)
    write_json(path / "search.json", doc)


def own_pipeline_complete(path: Path) -> bool:
    """Search and identity both finished inside this client's folder."""
    name = stored_name(path)
    if not name.strip():
        return False
    search = load_search(path)
    if not search or search.get("status") != "done":
        return False
    try:
        count = int(search.get("source_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return False
    if not names_equal(str(search.get("intake_name") or ""), name):
        return False
    identity = load_identity(path)
    if not identity or identity.get("status") != "confirmed":
        return False
    return names_equal(str(identity.get("intake_name") or ""), name)


def later_different_person(path: Path) -> bool:
    """True when a newer intake uses a different name than this client."""
    name = stored_name(path)
    try:
        intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    created = intake.get("created_at") if isinstance(intake, dict) else ""
    if not isinstance(created, str):
        created = ""
    root = data_root()
    if not root.is_dir():
        return False
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name == path.name:
            continue
        if not CLIENT_RE.fullmatch(folder.name):
            continue
        other_file = folder / "intake.json"
        if not other_file.is_file():
            continue
        try:
            other = json.loads(other_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(other, dict):
            continue
        other_name = other.get("name") if isinstance(other.get("name"), str) else ""
        other_created = other.get("created_at") if isinstance(other.get("created_at"), str) else ""
        if not other_name.strip() or names_equal(other_name, name):
            continue
        if other_created > created:
            return True
    return False


def refuse_unnamed_reuse(path: Path, opts: dict[str, list[str]]) -> None:
    if not later_different_person(path):
        return
    named = flag(opts, "name") or ""
    if names_equal(named, stored_name(path)):
        return
    fail("reuse_name", REUSE_NAME)


def phrase_present(text: str, phrase: str) -> bool:
    phrase = (phrase or "").strip()
    if len(phrase) < 2:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text or "", re.IGNORECASE) is not None


def place_phrases(city: str) -> list[str]:
    raw = (city or "").strip()
    if not raw:
        return []
    phrases = [raw]
    head = re.split(r"[,/]", raw, maxsplit=1)[0].strip()
    tokens = head.split()
    if len(tokens) >= 2 and re.fullmatch(r"[A-Za-z]{2}", tokens[-1]):
        head = " ".join(tokens[:-1]).strip()
    if head and head.casefold() not in {item.casefold() for item in phrases}:
        phrases.append(head)
    return [item for item in phrases if len(item) >= 2]


def profile_marker(url: str) -> str:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    slug = (parsed.path or "").rstrip("/").lower()
    if host == "linkedin.com" and slug.startswith("/in/") and slug != "/in":
        return "linkedin:" + slug
    if host in {"x.com", "twitter.com"} and slug.count("/") == 1 and slug != "/":
        return "x:" + slug
    return ""


def link_matches(url: str, given: list[str]) -> bool:
    canon = canon_url(url)
    marker = profile_marker(url)
    for item in given:
        if not isinstance(item, str) or not item.strip():
            continue
        other = canon_url(item)
        if other and canon == other:
            return True
        other_marker = profile_marker(item)
        if marker and other_marker and marker == other_marker:
            return True
    return False


STATE_NAMES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut", "de": "delaware",
    "dc": "district of columbia", "fl": "florida", "ga": "georgia", "hi": "hawaii",
    "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa",
    "ks": "kansas", "ky": "kentucky", "la": "louisiana", "me": "maine",
    "md": "maryland", "ma": "massachusetts", "mi": "michigan", "mn": "minnesota",
    "ms": "mississippi", "mo": "missouri", "mt": "montana", "ne": "nebraska",
    "nv": "nevada", "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico",
    "ny": "new york", "nc": "north carolina", "nd": "north dakota", "oh": "ohio",
    "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania", "ri": "rhode island",
    "sc": "south carolina", "sd": "south dakota", "tn": "tennessee", "tx": "texas",
    "ut": "utah", "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
}
SOCIAL_HOSTS = {
    "linkedin.com", "x.com", "twitter.com", "facebook.com", "instagram.com",
    "youtube.com", "tiktok.com",
}


def host_of(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def state_signals(city: str) -> tuple[list[str], list[str]]:
    """Full state names, then uppercase abbreviations, taken from the city field."""
    raw = (city or "").strip()
    names: list[str] = []
    abbrs: list[str] = []
    match = re.search(r"(?:,|/|\s)([A-Za-z]{2})\s*$", raw)
    if match:
        abbr = match.group(1).casefold()
        if abbr in STATE_NAMES:
            abbrs.append(match.group(1).upper())
            names.append(STATE_NAMES[abbr])
    folded = raw.casefold()
    for abbr, name in STATE_NAMES.items():
        if phrase_present(folded, name) and name not in names:
            names.append(name)
            token = abbr.upper()
            if token not in abbrs:
                abbrs.append(token)
    return names, abbrs


def state_in_text(text: str, city: str) -> bool:
    names, abbrs = state_signals(city)
    for name in names:
        if phrase_present(text, name):
            return True
    for abbr in abbrs:
        if re.search(rf"(?<!\w){re.escape(abbr)}(?!\w)", text or ""):
            return True
    return False


def domain_matches(url: str, given: list[str]) -> bool:
    host = host_of(url)
    if not host or host in SOCIAL_HOSTS:
        return False
    for item in given:
        other = host_of(item)
        if other and other == host and other not in SOCIAL_HOSTS:
            return True
    return False


def given_urls(intake: dict) -> list[str]:
    return [item for item in (intake.get("urls") or []) if isinstance(item, str)]


def company_slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (company or "").casefold())


def company_host_hit(url: str, company: str) -> bool:
    """True when the page itself is on the company's domain."""
    slug = company_slug(company)
    if len(slug) < 3:
        return False
    host = host_of(url)
    return bool(host) and any(label == slug for label in host.split("."))


def company_slug_hit(value: str, company: str) -> bool:
    """Company token in a URL path or domain. Underscores do not hide it."""
    slug = company_slug(company)
    if len(slug) < 3:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(slug)}(?![a-z0-9])", value or "", re.IGNORECASE) is not None


def company_spaced_hit(value: str, company: str) -> bool:
    """AdvisorReach also matches 'Advisor Reach' and advisorreach.ai. Not 'advisor will reach'."""
    parts = re.findall(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+", company or "")
    if len(parts) < 2:
        return False
    pattern = r"[\W_]*".join(re.escape(part) for part in parts)
    return re.search(rf"(?<!\w){pattern}(?!\w)", value or "", re.IGNORECASE) is not None


def linkedin_handle(url: str) -> str:
    """Profile or post handle. /in/dkmarshall and /posts/dkmarshall_... are one person."""
    if host_of(url) != "linkedin.com":
        return ""
    parts = [part for part in (urlparse(url or "").path or "").split("/") if part]
    if len(parts) < 2:
        return ""
    kind = parts[0].casefold()
    rest = parts[1]
    if kind == "in":
        handle = rest
    elif kind == "posts":
        handle = rest.split("_", 1)[0]
    else:
        return ""
    handle = handle.strip().casefold()
    if len(handle) < 3:
        return ""
    return handle


def source_matches_anchors(title: str, excerpt: str, url: str, intake: dict, snippet: str = "") -> bool:
    """Company name, highlight, domain, or a given url. City alone is not a person."""
    blob = f"{title or ''} {excerpt or ''} {snippet or ''}"
    company = (intake.get("company") or "").strip()
    role = (intake.get("role") or "").strip()
    urls = given_urls(intake)
    company_hit = bool(company) and (
        phrase_present(blob, company)
        or company_slug_hit(blob, company)
        or company_spaced_hit(blob, company)
        or company_host_hit(url, company)
        or company_slug_hit(url, company)
    )
    link_hit = link_matches(url, urls) or domain_matches(url, urls)
    if company or urls:
        return company_hit or link_hit
    city_hit = any(phrase_present(blob, phrase) for phrase in place_phrases(intake.get("city") or ""))
    if not city_hit:
        return False
    role_hit = bool(role) and phrase_present(blob, role)
    return role_hit or state_in_text(blob, intake.get("city") or "")


def search_count(raw: int, deduped: int, name_matched: int, anchor_kept: int) -> dict:
    return {
        "raw": raw,
        "deduped": deduped,
        "name_matched": name_matched,
        "anchor_kept": anchor_kept,
    }


def excluded_people_note(count: int) -> str:
    if count <= 0:
        return ""
    if count == 1:
        return "1 other person with this name was excluded."
    return f"{count} other people with this name were excluded."


def exa_payload_failed(payload: dict) -> bool:
    """HTTP 200 that is still an auth or transport error, with no results."""
    results = payload.get("results")
    if isinstance(results, list) and results:
        return False
    if payload.get("error"):
        return True
    errors = payload.get("errors")
    return bool(errors)


def write_search_unavailable(
    path: Path,
    client_id: str,
    actor: str | None,
    queries: list[dict],
    raw_count: int,
) -> None:
    stamp_search(path, {
        "status": "unavailable",
        "message": WEB_SEARCH_UNAVAILABLE,
        "query_count": len(queries),
        "queries": [query["q"] for query in queries],
        "targets": [query.get("target") for query in queries],
        "source_count": 0,
        "sources": [],
        "profile_count": 0,
        "conflict": False,
        "counts": search_count(raw_count, 0, 0, 0),
        "dropped": [],
    })
    audit("search", client_id, {"queries": len(queries), "sources": 0}, actor)
    fail("search_unavailable", WEB_SEARCH_UNAVAILABLE)


def write_couldnt_find(
    path: Path,
    client_id: str,
    actor: str | None,
    queries: list[dict],
    inaccessible: list[dict],
    codes: list[str],
    counts: dict | None = None,
    dropped: list | None = None,
) -> None:
    stamp_search(path, {
        "status": "couldnt_find",
        "message": "couldn't find",
        "query_count": len(queries),
        "queries": [query["q"] for query in queries],
        "targets": [query.get("target") for query in queries],
        "source_count": 0,
        "sources": [],
        "profile_count": 0,
        "conflict": False,
        "counts": counts or search_count(0, 0, 0, 0),
        "dropped": dropped or [],
    })
    audit("search", client_id, {"queries": len(queries), "sources": 0}, actor)
    missed = {
        "ok": False,
        "error": "couldnt_find",
        "status": "couldnt_find",
        "message": "couldn't find",
        "query_count": len(queries),
        "source_count": 0,
    }
    if inaccessible:
        missed["inaccessible"] = inaccessible
    if codes:
        missed["warnings"] = [warning(code) for code in codes]
    emit(missed, 1)


def cmd_search(client_id: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    urls = list(intake.get("urls") or [])
    for item in intake.get("inaccessible_urls") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    queries, inaccessible, codes = build_queries(
        intake.get("name") or "",
        intake.get("city") or "",
        urls,
        intake.get("company") or "",
    )
    if not queries:
        fail("no_queries", "No safe name-and-city query could be built.")
    key = exa_key()
    if not key:
        stamp_search(path, {
            "status": "unavailable",
            "message": SEARCH_UNAVAILABLE,
            "query_count": 0,
            "source_count": 0,
            "sources": [],
            "conflict": False,
            "counts": search_count(0, 0, 0, 0),
        })
        fail("search_unavailable", SEARCH_UNAVAILABLE)
    parts = split_name(intake.get("name") or "")
    if not parts:
        stamp_search(path, {
            "status": "unavailable",
            "message": "couldn't find",
            "query_count": 0,
            "source_count": 0,
            "sources": [],
            "conflict": False,
            "counts": search_count(0, 0, 0, 0),
        })
        fail("couldnt_find", "couldn't find")
    first, last = parts
    rows = [row for row in load_evidence(path) if row.get("via") != "exa"]
    found: list[dict] = []
    seen: set[str] = set()
    need_text: list[str] = []
    raw_count = 0
    succeeded = 0
    for query in queries:
        try:
            payload = exa_post("/search", exa_search_body(query), key)
        except ExaError:
            continue
        if exa_payload_failed(payload):
            continue
        succeeded += 1
        for raw in payload.get("results") or []:
            if not isinstance(raw, dict):
                continue
            raw_count += 1
            url = raw.get("url") if isinstance(raw.get("url"), str) else ""
            if not is_http_url(url) or dangerous_url(url) or is_instagram(url):
                continue
            key_url = canon_url(url)
            if not key_url or key_url in seen:
                continue
            seen.add(key_url)
            title = raw.get("title") if isinstance(raw.get("title"), str) else ""
            text = result_text(raw)
            snippet = result_snippet(raw)
            corpus = result_corpus(raw)
            item = {
                "url": url,
                "title": title,
                "text": text,
                "snippet": snippet,
                "corpus": corpus,
                "query": query["q"],
                "target": query.get("target") or "",
            }
            found.append(item)
            if not text.strip() and not snippet.strip():
                need_text.append(url)
    if succeeded == 0:
        save_evidence(path, rows)
        write_search_unavailable(path, client_id, actor, queries, raw_count)
    if need_text:
        try:
            filled = exa_post("/contents", {
                "urls": need_text,
                "text": {"maxCharacters": EXA_TEXT_CHARS},
                "highlights": {"maxCharacters": 2000},
                "extras": {"links": 10},
            }, key)
        except ExaError:
            filled = {}
        by_url = {}
        if isinstance(filled, dict) and not exa_payload_failed(filled):
            for raw in filled.get("results") or []:
                if isinstance(raw, dict) and isinstance(raw.get("url"), str):
                    by_url[canon_url(raw["url"])] = raw
        for item in found:
            if item["text"].strip():
                continue
            raw = by_url.get(canon_url(item["url"]))
            if not raw:
                continue
            item["text"] = result_text(raw)
            fetched_snippet = result_snippet(raw)
            if fetched_snippet:
                item["snippet"] = f"{item.get('snippet') or ''} {fetched_snippet}".strip()
            fetched_corpus = result_corpus(raw)
            if fetched_corpus:
                item["corpus"] = f"{item.get('corpus') or ''} {fetched_corpus}".strip()
            if not item["title"] and isinstance(raw.get("title"), str):
                item["title"] = raw["title"]
    dropped: list[dict] = []
    kept: list[dict] = []
    for item in found:
        snippet = item.get("snippet") or ""
        blob = item.get("corpus") or f"{item['title']} {item['text']} {snippet}"
        if not full_name_match(blob, first, last):
            dropped.append({"url": item["url"], "reason": "name_mismatch"})
            continue
        cleaned, _ = sanitize_untrusted(item["text"] or snippet or item["title"])
        if not cleaned:
            dropped.append({"url": item["url"], "reason": "empty_text"})
            continue
        title_clean, _ = sanitize_untrusted(item["title"] or item["url"])
        if len(cleaned) > EXCERPT_CAP:
            cleaned = cleaned[:EXCERPT_CAP]
        kept.append({
            "url": item["url"],
            "title": title_clean or item["url"],
            "excerpt": cleaned,
            "query": item["query"],
            "target": item["target"],
            "text": item["text"] or "",
            "snippet": snippet,
            "corpus": item.get("corpus") or blob,
        })
    tally = search_count(raw_count, len(found), len(kept), 0)
    if not kept:
        save_evidence(path, rows)
        write_couldnt_find(path, client_id, actor, queries, inaccessible, codes, tally, dropped)
    # A city alone does not make a page this person. Pages that fail the
    # company, url, or city-plus-role/state check are left out.
    matched: list[dict] = []
    excluded_markers: list[str] = []
    excluded_pages = 0
    pending: list[dict] = []
    anchored_handles: set[str] = set()
    for item in kept:
        marker = profile_marker(item["url"])
        item["profile"] = marker
        corpus = item.get("corpus") or ""
        if source_matches_anchors(
            item["title"],
            corpus or item.get("text") or item["excerpt"],
            item["url"],
            intake,
            item.get("snippet") or "",
        ):
            matched.append(item)
            handle = linkedin_handle(item["url"])
            if handle:
                anchored_handles.add(handle)
            # The company site often links the person's LinkedIn instead of
            # repeating the employer on every post.
            if company_host_hit(item["url"], intake.get("company") or "") or company_slug_hit(corpus, intake.get("company") or ""):
                anchored_handles.update(mentioned_linkedin_handles(corpus))
            continue
        pending.append(item)
    # A company-anchored /in/dkmarshall page keeps that handle's other posts, and the reverse.
    for item in pending:
        handle = linkedin_handle(item["url"])
        if handle and handle in anchored_handles:
            matched.append(item)
            continue
        dropped.append({"url": item["url"], "reason": "namesake"})
        marker = item.get("profile") or ""
        if marker:
            if marker not in excluded_markers:
                excluded_markers.append(marker)
        else:
            excluded_pages += 1
    excluded_people = len(excluded_markers) + excluded_pages
    note = excluded_people_note(excluded_people)
    tally = search_count(raw_count, len(found), len(kept), len(matched))
    if not matched:
        save_evidence(path, rows)
        stamp_search(path, {
            "status": "need_anchor",
            "message": NEED_ANCHOR,
            "query_count": len(queries),
            "queries": [query["q"] for query in queries],
            "targets": [query.get("target") for query in queries],
            "source_count": 0,
            "sources": [],
            "profile_count": 0,
            "conflict": False,
            "excluded_people": excluded_people,
            "excluded_note": note,
            "counts": tally,
            "dropped": dropped,
        })
        audit("search", client_id, {"queries": len(queries), "sources": 0}, actor)
        missed = {
            "ok": False,
            "error": "need_anchor",
            "status": "need_anchor",
            "message": NEED_ANCHOR,
            "query_count": len(queries),
            "source_count": 0,
            "excluded_people": excluded_people,
        }
        if note:
            missed["excluded_note"] = note
        if inaccessible:
            missed["inaccessible"] = inaccessible
        if codes:
            missed["warnings"] = [warning(code) for code in codes]
        emit(missed, 1)
    # One person per matching LinkedIn or X profile. A page with no profile
    # joins that person only when there is a single profile. It is never
    # copied onto every person.
    profiles: list[str] = []
    for item in matched:
        if item["profile"] and item["profile"] not in profiles:
            profiles.append(item["profile"])
    linkedin_n = sum(1 for marker in profiles if marker.startswith("linkedin:"))
    x_n = sum(1 for marker in profiles if marker.startswith("x:"))
    # One LinkedIn and one X for the same company are one person. Two profiles
    # of the same kind stay split so two different people are not merged.
    same_person = bool((intake.get("company") or "").strip() or given_urls(intake)) and linkedin_n <= 1 and x_n <= 1
    used = [int(row.get("candidate") or 0) for row in rows]
    start = (max(used) + 1) if used else 1
    profile_n = {marker: start + index for index, marker in enumerate(profiles)}
    loose = {"n": start + len(profiles), "ids": {}}
    conflict = False if same_person else len(profiles) > 1

    def candidate_numbers(item: dict) -> list[int]:
        if same_person:
            return [start]
        if item["profile"]:
            return [profile_n[item["profile"]]]
        if len(profiles) == 1:
            return [profile_n[profiles[0]]]
        if not profiles:
            return [start]
        url = item["url"]
        if url not in loose["ids"]:
            loose["ids"][url] = loose["n"]
            loose["n"] += 1
        return [loose["ids"][url]]

    sources = []
    for item in matched:
        for number in candidate_numbers(item):
            evidence_id = "ev_" + secrets.token_hex(8)
            rows.append({
                "evidence_id": evidence_id,
                "url": item["url"],
                "title": item["title"],
                "excerpt": item["excerpt"],
                "origin": "web",
                "query": item["query"],
                "candidate": number,
                "identity_status": "unconfirmed",
                "added_at": now_iso(),
                "fetched": True,
                "via": "exa",
                "target": item["target"],
                "profile": item["profile"],
            })
            sources.append({
                "evidence_id": evidence_id,
                "url": item["url"],
                "title": item["title"],
                "target": item["target"],
                "candidate": number,
            })
    save_evidence(path, rows)
    stored = {
        "status": "done",
        "query_count": len(queries),
        "queries": [query["q"] for query in queries],
        "targets": [query.get("target") for query in queries],
        "source_count": len(sources),
        "sources": sources,
        "profile_count": len(profiles),
        "conflict": conflict,
        "excluded_people": excluded_people,
        "excluded_note": note,
        "counts": tally,
        "dropped": dropped,
    }
    stamp_search(path, stored)
    audit("search", client_id, {"queries": len(queries), "sources": len(sources)}, actor)
    result = {
        "ok": True,
        "status": "done",
        "query_count": len(queries),
        "source_count": len(sources),
        "sources": sources,
        "excluded_people": excluded_people,
        "conflict": conflict,
        "counts": tally,
    }
    if note:
        result["excluded_note"] = note
    if inaccessible:
        result["inaccessible"] = inaccessible
    if codes:
        result["warnings"] = [warning(code) for code in codes]
    emit(result)


def cmd_evidence_add(client_id: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
    url = flag(opts, "url") or ""
    title = flag(opts, "title") or ""
    excerpt = flag(opts, "excerpt") or ""
    origin = (flag(opts, "origin") or "").lower()
    query = flag(opts, "query") or ""
    candidate_raw = flag(opts, "candidate")
    if origin not in {"web", "manual"}:
        fail("bad_origin", "Origin must be web or manual.")
    if dangerous_url(url):
        fail("rejected_url", "javascript and other active URLs are rejected.")
    if origin == "web" and not is_http_url(url):
        fail("rejected_url", "Web evidence needs an http(s) URL.")
    if not candidate_raw or not re.fullmatch(r"[1-9]\d*", candidate_raw):
        fail("bad_candidate", "Candidate must be a positive integer.")
    cleaned, codes = sanitize_untrusted(excerpt)
    if not cleaned:
        fail("empty_excerpt", "Excerpt is empty.")
    title_clean, title_codes = sanitize_untrusted(title)
    query_clean, query_codes = sanitize_untrusted(query)
    codes = unique(codes + title_codes + query_codes)
    if not query_clean:
        fail("empty_query", "Query is empty after removing blocked tokens.")
    truncated = False
    if len(cleaned) > EXCERPT_CAP:
        cleaned = cleaned[:EXCERPT_CAP]
        truncated = True
    evidence_id = "ev_" + secrets.token_hex(8)
    inaccessible = origin == "web" and is_instagram(url)
    record = {
        "evidence_id": evidence_id,
        "url": "" if inaccessible else url,
        "title": title_clean,
        "excerpt": "" if inaccessible else cleaned,
        "origin": origin,
        "query": query_clean,
        "candidate": int(candidate_raw),
        "identity_status": "inaccessible" if inaccessible else "unconfirmed",
        "added_at": now_iso(),
        "fetched": False if inaccessible else origin == "web",
    }
    if inaccessible:
        record["inaccessible"] = True
        record["reason"] = "private_or_login_walled_instagram"
    rows = load_evidence(path)
    if origin == "manual":
        # Owner-pasted evidence never shares a candidate with web results. After the owner
        # replied NONE, the public matches are dropped and whoever remains is numbered from 1,
        # so the pasted notes are 1 when they are the only candidate left.
        ident = path / "identity.json"
        rejected = False
        if ident.is_file():
            try:
                rejected = json.loads(ident.read_text(encoding="utf-8")).get("status") == "none"
            except Exception:
                rejected = False
        if rejected:
            rows = [r for r in rows if r.get("origin") == "manual"]
            ident.unlink()
            mapping: dict[int, int] = {}
            next_n = 1
            for row in rows:
                old = int(row.get("candidate") or 0)
                if old not in mapping:
                    mapping[old] = next_n
                    next_n += 1
                row["candidate"] = mapping[old]
            record["candidate"] = next_n
        else:
            web_nums = {int(r.get("candidate") or 0) for r in rows if r.get("origin") != "manual"}
            if record["candidate"] in web_nums:
                record["candidate"] = max(int(r.get("candidate") or 0) for r in rows) + 1
    rows.append(record)
    save_evidence(path, rows)
    if origin == "web" and is_http_url(url) and not is_instagram(url):
        intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
        stored = [item for item in (intake.get("urls") or []) if isinstance(item, str)]
        if url not in stored:
            stored.append(url)
            intake["urls"] = stored
            write_json(path / "intake.json", intake)
    audit("evidence_add", client_id, {"evidence": 1}, actor)
    result: dict = {"ok": True, "evidence_id": evidence_id, "candidate": record["candidate"]}
    if inaccessible:
        result["inaccessible"] = True
        result["fetched"] = False
    if truncated:
        result["truncated"] = True
    if codes:
        result["warnings"] = [warning(code) for code in codes]
    emit(result)


BLOCK_MARKER_RE = re.compile(r"<<<(?:END_)?UNTRUSTED_EVIDENCE[^>\n]*>>>")


def fence_field(value: object) -> str:
    text = value if isinstance(value, str) else ""
    text = text.replace("\r", "")
    text = BLOCK_MARKER_RE.sub(" ", text)
    text = text.replace("<<<END_UNTRUSTED_EVIDENCE", " ")
    text = text.replace("<<<UNTRUSTED_EVIDENCE", " ")
    return text


def cmd_evidence_render(client_id: str, opts: dict[str, list[str]]) -> None:
    gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    rows = load_evidence(path)
    blocks: list[str] = []
    for row in rows:
        if row.get("identity_status") != "confirmed":
            continue
        evidence_id = row.get("evidence_id") or ""
        if not isinstance(evidence_id, str) or not EVIDENCE_RE.fullmatch(evidence_id):
            continue
        blocks.append(
            f'<<<UNTRUSTED_EVIDENCE id="{evidence_id}">>>\n'
            f"title: {fence_field(row.get('title'))}\n"
            f"url: {fence_field(row.get('url'))}\n"
            f"excerpt: {fence_field(row.get('excerpt'))}\n"
            "<<<END_UNTRUSTED_EVIDENCE>>>"
        )
    emit({"ok": True, "count": len(blocks), "text": "\n\n".join(blocks)})


def stop_identity(path: Path, status: str, message: str) -> None:
    write_json(path / "candidates.json", {"candidates": [], "status": status})
    clear_pick_pending(path)
    emit({"ok": True, "status": status, "message": message, "candidates": []})


def clear_pick_pending(path: Path) -> None:
    """Drop this record's waiting list, and the pointer to it."""
    file_path = path / "pending.json"
    if file_path.is_file():
        file_path.unlink()
    pointer = data_root() / "pick-pending.json"
    if not pointer.is_file():
        return
    try:
        meta = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pointer.unlink()
        return
    if isinstance(meta, dict) and meta.get("client_id") == path.name:
        pointer.unlink()


def remember_pick_pending(client_id: str, path: Path, intake: dict, candidates: list[dict]) -> dict:
    """Save the choices the owner was just shown, on this record."""
    choices = []
    for index, candidate in enumerate(candidates, start=1):
        choices.append({
            "reply": index,
            "candidate": candidate["n"],
            "label": candidate["label"],
            "evidence_ids": candidate.get("evidence_ids") or [],
        })
    name = intake.get("name") or ""
    city = intake.get("city") or ""
    labels = " ".join(f"{item['reply']}) {item['label']}" for item in choices)
    if len(choices) == 1:
        reply_line = "Reply 1 or NONE."
    elif len(choices) == 2:
        reply_line = "Reply 1, 2 or NONE."
    else:
        earlier = ", ".join(str(item["reply"]) for item in choices[:-1])
        reply_line = f"Reply {earlier} or {choices[-1]['reply']}, or NONE."
    prompt = f"Found {len(choices)} {name} in {city}: {labels}. {reply_line}"
    saved_at = now_iso()
    doc = {
        "client_id": client_id,
        "name": name,
        "city": city,
        "choices": choices,
        "prompt": prompt,
        "awaiting": True,
        "saved_at": saved_at,
    }
    write_json(path / "pending.json", doc)
    write_json(data_root() / "pick-pending.json", {"client_id": client_id, "saved_at": saved_at})
    return doc


def active_pick_pending() -> tuple[str, Path, dict] | None:
    """The record whose candidate list the next text should answer."""
    pointer = data_root() / "pick-pending.json"
    if pointer.is_file():
        try:
            meta = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        client_id = meta.get("client_id") if isinstance(meta, dict) else ""
        path = client_path(client_id) if isinstance(client_id, str) else None
        if path is not None and (path / "pending.json").is_file():
            try:
                doc = json.loads((path / "pending.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = None
            if isinstance(doc, dict) and doc.get("choices") and not doc.get("closed"):
                return client_id, path, doc
    newest: tuple[str, str, Path, dict] | None = None
    for folder in profile_dirs():
        file_path = folder / "pending.json"
        if not file_path.is_file():
            continue
        try:
            doc = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or not doc.get("choices") or doc.get("closed"):
            continue
        saved = doc.get("saved_at") if isinstance(doc.get("saved_at"), str) else ""
        if newest is None or saved >= newest[0]:
            newest = (saved, folder.name, folder, doc)
    if newest is None:
        return None
    return newest[1], newest[2], newest[3]


def parse_pick_reply(positional: list[str], opts: dict[str, list[str]]) -> str:
    raw = flag(opts, "reply")
    if not raw and positional:
        raw = positional[0]
    token = (raw or "").strip()
    if not token or token == "true":
        fail("usage", "pick 1, or pick NONE")
    if token.casefold() == "none":
        return "NONE"
    match = re.fullmatch(r"(?:reply\s+)?(\d+)\.?", token, re.IGNORECASE)
    if not match:
        fail("bad_reply", "Reply with a number or NONE.")
    return match.group(1)


def selected_evidence_text(path: Path) -> str:
    rows = load_evidence(path)
    blocks: list[str] = []
    for row in rows:
        if row.get("identity_status") != "confirmed":
            continue
        evidence_id = row.get("evidence_id") or ""
        if not isinstance(evidence_id, str) or not EVIDENCE_RE.fullmatch(evidence_id):
            continue
        blocks.append(
            f'<<<UNTRUSTED_EVIDENCE id="{evidence_id}">>>\n'
            f"title: {fence_field(row.get('title'))}\n"
            f"url: {fence_field(row.get('url'))}\n"
            f"excerpt: {fence_field(row.get('excerpt'))}\n"
            "<<<END_UNTRUSTED_EVIDENCE>>>"
        )
    return "\n\n".join(blocks)


def run_confirm(client_id: str, opts: dict[str, list[str]]) -> tuple[dict, int]:
    """Run identity confirm and return its JSON instead of printing it."""
    global _emit_sink
    sink: list[tuple[dict, int]] = []
    previous = _emit_sink
    _emit_sink = sink
    try:
        cmd_confirm(client_id, opts)
    except SystemExit:
        pass
    finally:
        _emit_sink = previous
    if not sink:
        fail("internal", "The reply could not be resolved.")
    return sink[-1]


def cmd_pick(positional: list[str], opts: dict[str, list[str]]) -> None:
    """Resolve the owner's next text against the saved candidate list."""
    gate(actor_of(opts), mutate=True)
    reply = parse_pick_reply(positional, opts)
    found = active_pick_pending()
    if found is None:
        fail(
            "no_pending",
            "No profile is waiting for a reply. Start with the person's name and city.",
        )
    client_id, path, doc = found
    actor = actor_of(opts) or "owner"
    if reply == "NONE":
        payload, code = run_confirm(client_id, {"none": ["true"], "actor": [actor]})
        if code:
            emit(payload, code)
        doc["awaiting"] = False
        doc["closed"] = "none"
        doc["selected"] = None
        write_json(path / "pending.json", doc)
        emit({
            "ok": True,
            "client_id": client_id,
            "reply": "NONE",
            "next": "stop",
            "status": "none",
        })
    number = int(reply)
    choice = None
    for item in doc.get("choices") or []:
        if isinstance(item, dict) and int(item.get("reply") or 0) == number:
            choice = item
            break
    if choice is None:
        prompt = doc.get("prompt") or "Reply with a listed number or NONE."
        emit({"ok": False, "error": "unknown_reply", "message": prompt, "say": prompt}, 1)
    payload, code = run_confirm(
        client_id,
        {"candidate": [str(choice["candidate"])], "actor": [actor]},
    )
    if code:
        emit(payload, code)
    doc["awaiting"] = False
    doc["selected"] = number
    write_json(path / "pending.json", doc)
    emit({
        "ok": True,
        "client_id": client_id,
        "reply": number,
        "candidate": choice["candidate"],
        "next": "write",
        "evidence": selected_evidence_text(path),
    })


def cmd_candidates(client_id: str, opts: dict[str, list[str]]) -> None:
    gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    ensure_search(client_id, path, opts)
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    rows = load_evidence(path)
    usable = [row for row in rows if row.get("identity_status") != "inaccessible"]
    public = [row for row in usable if row.get("origin") == "web"]
    parts = split_name(intake.get("name") or "")
    # couldn't find is only after a real search kept 0 sources.
    # A missing search file is search_required, and only when Exa cannot run.
    # Owner notes do not count as a person.
    if not public:
        if search_needs_anchor(path):
            doc = load_search(path) or {}
            message = doc.get("message") or NEED_ANCHOR
            note = doc.get("excluded_note") or ""
            if isinstance(note, str) and note and note not in message:
                message = message + " " + note
            stop_identity(path, "need_anchor", message)
        doc = load_search(path) or {}
        if doc.get("status") == "unavailable":
            fail("search_unavailable", doc.get("message") or SEARCH_UNAVAILABLE)
        stop_identity(path, "couldnt_find", "couldn't find")
    if not parts:
        stop_identity(path, "couldnt_find", "couldn't find")
    first, last = parts
    manual = [row for row in usable if row.get("origin") == "manual"]
    if is_common_name(first, last) and not has_profile_url(intake, usable) and not manual:
        stop_identity(path, "need_profile_link", "This name is common. Send a profile link instead of a guess.")
    grouped: dict[int, list[dict]] = {}
    for row in usable:
        if is_common_name(first, last) and not has_profile_url(intake, usable) and row.get("origin") != "manual":
            continue
        if not row_name_match(row, first, last):
            continue
        grouped.setdefault(int(row["candidate"]), []).append(row)
    if not grouped:
        stop_identity(path, "couldnt_find", "couldn't find")
    candidates = []
    for number in sorted(grouped):
        group = grouped[number]
        labels = []
        for row in group:
            label, _ = redact(row.get("title") or "")
            if label:
                labels.append(label)
        text = " · ".join(labels) if labels else f"Candidate {number}"
        if len(text) > 180:
            text = text[:179].rstrip() + "…"
        candidates.append({
            "n": number,
            "label": text,
            "evidence_ids": [row["evidence_id"] for row in group],
        })
    write_json(path / "candidates.json", {"candidates": candidates, "status": "matches"})
    pending = remember_pick_pending(client_id, path, intake, candidates)
    # One person is a match. Select them here so the text path can render
    # without a pick op the current render_file plugin does not have.
    if len(candidates) == 1:
        number = int(candidates[0]["n"])
        actor = actor_of(opts) or "unspecified"
        payload, code = run_confirm(client_id, {"candidate": [str(number)], "actor": [actor]})
        if code:
            emit(payload, code)
        city = intake.get("city") or ""
        where = f" in {city}" if city else ""
        say = f"Matched {intake.get('name') or ''}{where}: {candidates[0]['label']}."
        pending["awaiting"] = False
        pending["closed"] = "auto"
        pending["selected"] = 1
        pending["prompt"] = say
        write_json(path / "pending.json", pending)
        emit({
            "ok": True,
            "status": "matches",
            "candidates": candidates,
            "client_id": client_id,
            "candidate": number,
            "next": "write",
            "say": say,
            "prompt": say,
            "evidence": selected_evidence_text(path),
            "pending_saved": True,
        })
    emit({
        "ok": True,
        "status": "matches",
        "candidates": candidates,
        "client_id": client_id,
        "prompt": pending["prompt"],
        "pending_saved": True,
        "next": "reply",
    })


def cmd_confirm(client_id: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
    ensure_search(client_id, path, opts)
    none = "none" in opts
    candidate_raw = flag(opts, "candidate")
    if none and candidate_raw:
        fail("bad_confirm", "Pass either --candidate or --none.")
    if not none and not candidate_raw:
        fail("bad_confirm", "Pass either --candidate or --none.")
    rows = load_evidence(path)
    if none:
        for row in rows:
            if row.get("identity_status") == "confirmed":
                row["identity_status"] = "unconfirmed"
        save_evidence(path, rows)
        write_json(path / "identity.json", {
            "status": "none",
            "confirmed_at": now_iso(),
            "evidence_ids": [],
            "intake_name": stored_name(path),
        })
        brief = path / "brief.json"
        if brief.exists():
            brief.unlink()
        audit("identity_confirm", client_id, {"confirmed": 0}, actor)
        emit({"ok": True, "status": "none"})
    if not candidate_raw or not re.fullmatch(r"[1-9]\d*", candidate_raw):
        fail("bad_candidate", "Candidate must be a positive integer.")
    number = int(candidate_raw)
    matched = [
        row for row in rows
        if int(row.get("candidate") or 0) == number and row.get("identity_status") != "inaccessible"
    ]
    if not matched:
        fail("unknown_candidate", "That candidate has no usable evidence.")
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    parts = split_name(intake.get("name") or "")
    if not parts:
        fail("couldnt_find", "couldn't find")
    first, last = parts
    if is_common_name(first, last) and not has_profile_url(intake, rows):
        if any(row.get("origin") != "manual" for row in matched):
            fail("need_profile_link", "This name is common. Send a profile link instead of a guess.")
    named = [row for row in matched if row_name_match(row, first, last)]
    if not named:
        fail("couldnt_find", "couldn't find")
    named_ids = {row["evidence_id"] for row in named}
    confirmed: list[str] = []
    for row in rows:
        if row.get("evidence_id") in named_ids:
            row["identity_status"] = "confirmed"
            confirmed.append(row["evidence_id"])
        elif row.get("identity_status") == "confirmed":
            row["identity_status"] = "unconfirmed"
    save_evidence(path, rows)
    write_json(path / "identity.json", {
        "status": "confirmed",
        "candidate": number,
        "evidence_ids": confirmed,
        "confirmed_at": now_iso(),
        "intake_name": stored_name(path),
    })
    audit("identity_confirm", client_id, {"confirmed": len(confirmed)}, actor)
    emit({"ok": True, "status": "confirmed", "candidate": number, "evidence_ids": confirmed})


def cmd_validate(client_id: str, brief_file: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
    ensure_search(client_id, path, opts)
    refuse_unnamed_reuse(path, opts)
    source = Path(brief_file)
    if not source.is_file():
        fail("brief_missing", "Brief JSON path does not exist.")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        fail("brief_json", "Brief file is not JSON.")
    if not isinstance(raw, dict):
        fail("brief_json", "Brief JSON must be an object.")
    result = evaluate_brief(path, raw)
    if not result["ok"]:
        emit({"ok": False, "errors": result["errors"], "warnings": result["warnings"]}, 1)
    write_json(path / "brief.json", result["brief"])
    write_json(path / "brief.validation.json", {
        "ok": True,
        "validated_at": now_iso(),
        "warnings": result["warnings"],
    })
    audit("brief_validate", client_id, {"briefs": 1}, actor)
    emit({"ok": True, "errors": [], "warnings": result["warnings"]})


def cmd_render(client_id: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
    ensure_search(client_id, path, opts)
    refuse_unnamed_reuse(path, opts)
    brief_path = path / "brief.json"
    if not brief_path.is_file():
        fail("not_validated", "No validated brief.json.")
    raw = json.loads(brief_path.read_text(encoding="utf-8"))
    result = evaluate_brief(path, raw)
    if not result["ok"]:
        fail("not_validated", "Stored brief failed validation.", {"errors": result["errors"]})
    write_json(brief_path, result["brief"])
    view = json.loads(json.dumps(result["brief"]))
    html_path = path / "brief.html"
    pdf_path = path / "brief.pdf"

    def paint(current: dict) -> tuple[str, int | None]:
        html_out = build_html(path, current)
        html_path.write_text(html_out, encoding="utf-8")
        if pdf_path.exists():
            pdf_path.unlink()
        return html_out, weasyprint_document_pages(html_path, pdf_path)

    html, document_pages = paint(view)
    # Tighten the layout in the template first. Cut a bullet only when the
    # rendered PDF is still longer than one page.
    guard = 0
    while document_pages is not None and document_pages > 1 and guard < 80 and trim_one_bullet(view):
        guard += 1
        html, document_pages = paint(view)
    wrote_pdf = pdf_path.is_file() and pdf_path.stat().st_size > 0
    if document_pages is not None and document_pages > 0:
        pages = document_pages
    else:
        pages = estimate_pages(html)
    audit("brief_render", client_id, {"html": 1, "pdf": 1 if wrote_pdf else 0, "pages": pages}, actor)
    payload: dict = {"ok": True, "html": True, "pdf": wrote_pdf, "pages": pages}
    if not wrote_pdf:
        payload["pdf_skipped"] = "weasyprint_unavailable"
    emit(payload)


def public_base() -> str:
    raw = os.environ.get("ARTIFACT_BASE_URL") or _cfg_value("artifact_base_url") or "https://artifacts.local"
    return raw.rstrip("/")


def cmd_deliver(client_id: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
    html_path = path / "brief.html"
    pdf_path = path / "brief.pdf"
    if pdf_path.is_file():
        source = pdf_path
        suffix = ".pdf"
    elif html_path.is_file():
        source = html_path
        suffix = ".html"
    else:
        fail("not_rendered", "Render the brief before delivery.")
    dest_dir = artifact_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = ""
    dest = dest_dir / "placeholder"
    for _ in range(5):
        filename = secrets.token_hex(16) + suffix
        dest = dest_dir / filename
        if not dest.exists():
            break
    shutil.copyfile(source, dest)
    delivered = datetime.now(timezone.utc)
    expires = delivered + timedelta(days=ARTIFACT_DAYS)
    url = public_base() + "/" + filename
    record = {
        "filename": filename,
        "url": url,
        "delivered_at": delivered.isoformat(),
        "expires_at": expires.isoformat(),
        "artifact_path": str(dest.resolve()),
    }
    write_json(path / "delivery.json", record)
    audit("deliver", client_id, {"artifacts": 1}, actor)
    emit({"ok": True, "url": url, "expires_at": record["expires_at"]})


def shrink(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


def cmd_sms(client_id: str, opts: dict[str, list[str]]) -> None:
    gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    brief_path = path / "brief.json"
    delivery_path = path / "delivery.json"
    if not brief_path.is_file() or not delivery_path.is_file():
        fail("not_delivered", "Deliver the brief before the SMS summary.")
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    url = delivery.get("url") or ""
    if not url.startswith("https://") and not url.startswith("http://"):
        fail("bad_url", "Delivery URL is not public.")
    if url.startswith("https://artifacts.local/"):
        fail("bad_url", "Delivery URL is a placeholder; ARTIFACT_BASE_URL is not set. Re-run install from the box shell.")
    level = show_level((brief.get("identity_match") or {}).get("level") or "low")
    disc = (brief.get("communication_style") or {}).get("disc_hypothesis") or ""
    leads = (brief.get("appointment_playbook") or {}).get("lead_points") or []
    first = redact(leads[0].get("text") if leads else "")[0]
    second = redact(leads[1].get("text") if len(leads) > 1 else "")[0]
    first = re.sub(r"https?://\S+", "", first).strip()
    second = re.sub(r"https?://\S+", "", second).strip()
    style = " Style: insufficient evidence."
    if disc.strip().lower() != "insufficient evidence":
        style = " Style: " + redact(disc)[0] + "."
    identity = f" Identity: {level}."
    banner = "Verify before use."

    def assemble(style_text: str, left: str, right: str) -> str:
        return f"{banner}{identity}{style_text} 1) {left} 2) {right} {url}".strip()

    # Keep the style hunch: cap it first, then trim the lead points evenly; drop style last.
    if len(style) > 72:
        style = shrink(style.rstrip("."), 71) + "."
    text = assemble(style, first, second)
    while len(text) > 300 and (len(first) > 40 or len(second) > 40 or style):
        if len(first) >= len(second) and len(first) > 40:
            first = shrink(first, max(40, len(first) - 10))
        elif len(second) > 40:
            second = shrink(second, max(40, len(second) - 10))
        else:
            style = ""
        text = assemble(style, first, second)
    if len(text) > 300:
        text = f"{banner}{identity} {url}"
    if len(text) > 300:
        text = f"{banner} {url}"
    if STREET_RE.search(text) or POBOX_RE.search(text):
        text = f"{banner}{identity} {url}"
    if len(text) > 300 or text.count(url) != 1:
        fail("sms_length", "Could not fit a safe summary in 300 characters.")
    emit({"ok": True, "text": text})


def artifact_to_delete(record: dict) -> Path | None:
    raw = record.get("artifact_path")
    if not raw:
        return None
    try:
        candidate = Path(raw).resolve()
        root = artifact_dir().resolve()
    except OSError:
        return None
    if candidate == root or root not in candidate.parents:
        return None
    return candidate


def delete_profile(path: Path) -> int:
    removed_artifact = 0
    delivery_path = path / "delivery.json"
    if delivery_path.is_file():
        record = json.loads(delivery_path.read_text(encoding="utf-8"))
        artifact = artifact_to_delete(record)
        if artifact and artifact.is_file():
            artifact.unlink()
            removed_artifact = 1
    shutil.rmtree(path)
    return removed_artifact


def cmd_wrong_identity(client_id: str, opts: dict[str, list[str]]) -> None:
    # Privacy delete stays available when the skill is off (uninstall keeps the data).
    actor = gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    removed_artifact = delete_profile(path)
    audit("wrong_identity", client_id, {"profiles": 1, "artifacts": removed_artifact}, actor)
    emit({"ok": True, "deleted": True})


def cmd_delete_client(client_id: str, opts: dict[str, list[str]], action: str) -> None:
    # Per-client delete stays available when the skill is off (uninstall keeps the data).
    actor = gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    removed_artifact = delete_profile(path)
    audit(action, client_id, {"profiles": 1, "artifacts": removed_artifact}, actor)
    emit({"ok": True, "deleted": True})


def profile_dirs() -> list[Path]:
    root = data_root()
    if not root.is_dir():
        return []
    found = []
    for child in root.iterdir():
        if child.is_dir() and (child / "intake.json").is_file() and CLIENT_RE.fullmatch(child.name):
            found.append(child)
    return found


def profile_age(path: Path) -> tuple[float | None, int]:
    newest = None
    count = 0
    for dirpath, _, files in os.walk(path):
        for name in files:
            if name.endswith(".tmp"):
                continue
            count += 1
            mtime = (Path(dirpath) / name).stat().st_mtime
            newest = mtime if newest is None else max(newest, mtime)
    if newest is None:
        return None, count
    age_days = (datetime.now(timezone.utc).timestamp() - newest) / 86400
    return age_days, count


def stale_profiles() -> list[dict]:
    stale = []
    for path in profile_dirs():
        age_days, count = profile_age(path)
        if age_days is None or age_days <= PURGE_DAYS:
            continue
        newest = None
        for dirpath, _, files in os.walk(path):
            for name in files:
                if name.endswith(".tmp"):
                    continue
                mtime = (Path(dirpath) / name).stat().st_mtime
                newest = mtime if newest is None else max(newest, mtime)
        newest_iso = datetime.fromtimestamp(newest or 0, timezone.utc).isoformat()
        stale.append({
            "client_id": path.name,
            "newest": newest_iso,
            "age_days": int(age_days),
            "file_count": count,
        })
    return stale


def cmd_purge(opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=False)
    dry = "dry-run" in opts
    token = flag(opts, "confirm")
    if dry and token:
        fail("bad_purge", "Pass either --dry-run or --confirm.")
    if not dry and not token:
        fail("bad_purge", "Pass --dry-run or --confirm <token>.")
    if dry:
        profiles = stale_profiles()
        pending_token = secrets.token_hex(16)
        write_json(data_root() / "purge-pending.json", {
            "token": pending_token,
            "client_ids": [row["client_id"] for row in profiles],
            "created_at": now_iso(),
        })
        emit({
            "ok": True,
            "dry_run": True,
            "deleted": False,
            "token": pending_token,
            "profiles": profiles,
            "count": len(profiles),
        })
    pending_path = data_root() / "purge-pending.json"
    if not pending_path.is_file():
        fail("bad_token", "No purge token is pending.", {"deleted": False})
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    expected = str(pending.get("token") or "")
    if not token or len(token) != len(expected) or not hmac.compare_digest(expected, token):
        fail("bad_token", "Purge token did not match. Nothing was deleted.", {"deleted": False})
    ids = [cid for cid in pending.get("client_ids") or [] if CLIENT_RE.fullmatch(cid)]
    profiles_deleted = 0
    artifacts_deleted = 0
    files_deleted = 0
    for cid in ids:
        path = data_root() / cid
        if not path.is_dir():
            continue
        delivery_path = path / "delivery.json"
        if delivery_path.is_file():
            record = json.loads(delivery_path.read_text(encoding="utf-8"))
            artifact = artifact_to_delete(record)
            if artifact and artifact.is_file():
                artifact.unlink()
                artifacts_deleted += 1
        for dirpath, _, files in os.walk(path):
            files_deleted += len(files)
        shutil.rmtree(path)
        profiles_deleted += 1
    pending_path.unlink(missing_ok=True)
    counts = {"profiles": profiles_deleted, "artifacts": artifacts_deleted, "files": files_deleted}
    audit("purge", None, counts, actor)
    emit({"ok": True, "deleted": True, "counts": counts})


def redact_export(obj: object, key: str | None = None) -> object:
    if isinstance(obj, str):
        if key in {"url", "filename"}:
            return obj
        cleaned, _ = redact(obj)
        return cleaned
    if isinstance(obj, list):
        return [redact_export(item, key) for item in obj]
    if isinstance(obj, dict):
        return {item_key: redact_export(value, item_key) for item_key, value in obj.items()}
    return obj


def cmd_export(client_id: str, opts: dict[str, list[str]]) -> None:
    gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    payload = {
        "ok": True,
        "client_id": client_id,
        "intake": json.loads((path / "intake.json").read_text(encoding="utf-8")),
        "identity": load_identity(path),
        "evidence": load_evidence(path),
    }
    if (path / "brief.json").is_file():
        payload["brief"] = json.loads((path / "brief.json").read_text(encoding="utf-8"))
    if (path / "delivery.json").is_file():
        delivery = json.loads((path / "delivery.json").read_text(encoding="utf-8"))
        payload["delivery"] = {
            "filename": delivery.get("filename"),
            "url": delivery.get("url"),
            "delivered_at": delivery.get("delivered_at"),
            "expires_at": delivery.get("expires_at"),
        }
    emit(redact_export(payload))


def main(argv: list[str]) -> None:
    reject_address_flag(argv)
    if len(argv) < 2:
        fail("usage", "Missing command.")
    command = argv[1]
    rest = argv[2:]
    if command in {"hd", "birthday", "birth", "people-data"}:
        fail("not_in_scope", "Human Design, birth-date lookup, and people-data vendors are refused.")
    if command == "selftest":
        cmd_selftest()
    if command == "status":
        cmd_status()
    if command == "intake":
        _, opts = parse_flags(rest)
        cmd_intake(opts)
    if command == "queries":
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "queries <client_id>")
        cmd_queries(positional[0], opts)
    if command == "search":
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "search <client_id>")
        cmd_search(positional[0], opts)
    if command == "evidence":
        if not rest or rest[0] not in {"add", "block", "render"}:
            fail("usage", "evidence add|render|block <client_id>")
        positional, opts = parse_flags(rest[1:])
        if len(positional) != 1:
            fail("usage", "evidence add|render|block <client_id>")
        if rest[0] in {"block", "render"}:
            cmd_evidence_render(positional[0], opts)
        cmd_evidence_add(positional[0], opts)
    if command == "identity":
        if not rest or rest[0] not in {"candidates", "confirm"}:
            fail("usage", "identity candidates|confirm <client_id>")
        positional, opts = parse_flags(rest[1:])
        if len(positional) != 1:
            fail("usage", "identity requires a client id")
        if rest[0] == "candidates":
            cmd_candidates(positional[0], opts)
        cmd_confirm(positional[0], opts)
    if command == "pick":
        positional, opts = parse_flags(rest)
        cmd_pick(positional, opts)
    if command == "brief":
        if not rest or rest[0] not in {"validate", "render"}:
            fail("usage", "brief validate|render")
        if rest[0] == "validate":
            positional, opts = parse_flags(rest[1:])
            if len(positional) != 2:
                fail("usage", "brief validate <client_id> <path>")
            cmd_validate(positional[0], positional[1], opts)
        positional, opts = parse_flags(rest[1:])
        if len(positional) != 1:
            fail("usage", "brief render <client_id>")
        cmd_render(positional[0], opts)
    if command == "deliver":
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "deliver <client_id>")
        cmd_deliver(positional[0], opts)
    if command == "sms-summary":
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "sms-summary <client_id>")
        cmd_sms(positional[0], opts)
    if command == "wrong-identity":
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "wrong-identity <client_id>")
        cmd_wrong_identity(positional[0], opts)
    if command == "purge":
        _, opts = parse_flags(rest)
        cmd_purge(opts)
    if command == "export":
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "export <client_id>")
        cmd_export(positional[0], opts)
    if command in {"delete", "forget"}:
        positional, opts = parse_flags(rest)
        if len(positional) != 1:
            fail("usage", "delete <client_id>")
        cmd_delete_client(positional[0], opts, "delete")
    if command == "consent":
        if not rest or rest[0] != "revoke":
            fail("usage", "delete <client_id> removes this client. consent revoke is the same delete.")
        positional, opts = parse_flags(rest[1:])
        if len(positional) != 1:
            fail("usage", "consent revoke <client_id>")
        cmd_delete_client(positional[0], opts, "consent_revoke")
    fail("usage", "Unknown command.")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except SystemExit:
        raise
    except Exception as exc:
        fail("internal", type(exc).__name__)
