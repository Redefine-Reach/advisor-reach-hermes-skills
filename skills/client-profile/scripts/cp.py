#!/usr/bin/env python3
"""Client-profile rules tool. One JSON object on stdout. Stdlib only.

Data root: $CLIENT_PROFILE_ROOT or /opt/data/client-profile.
Config:    $CLIENT_PROFILE_ROOT/config.json  {"enabled": true|false, ...}
Audit:     <root>/../audit/client-profile.jsonl

No network, no CRM write, no Human Design, no street-address field.
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

QUERY_CAP = 6
EXCERPT_CAP = 1200
PURGE_DAYS = 90
ARTIFACT_DAYS = 7


def emit(obj: dict, code: int = 0) -> None:
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


def artifact_dir() -> Path:
    raw = os.environ.get("ARTIFACT_DIR")
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


def is_enabled() -> bool:
    cfg = load_config()
    return bool(cfg and cfg.get("enabled") is True)


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
    identity = load_identity(path)
    if not identity or identity.get("status") != "confirmed":
        return {
            "ok": False,
            "errors": [{"code": "identity_not_confirmed", "message": "No brief without a confirmed identity."}],
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
    if brief["identity_match"]["level"] != "confirmed":
        errors.append({"code": "identity_level", "path": "/identity_match/level"})
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
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
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
        pricing_html = f"<p>{html_escape(pricing.get('text') or '')}</p>"
    elif intake.get("type") == "listing":
        pricing_html = "<p>Missing.</p>"
    else:
        pricing_html = "<p>Not required for this appointment type.</p>"
    mapping = {
        "{{NAME}}": html_escape(intake.get("name") or ""),
        "{{CITY}}": html_escape(intake.get("city") or ""),
        "{{APPT_TYPE}}": html_escape(intake.get("type") or ""),
        "{{APPT_AT}}": appt_html,
        "{{GUARDRAIL}}": html_escape(brief.get("guardrail_notice") or ""),
        "{{SNAPSHOT}}": html_escape(brief.get("snapshot") or ""),
        "{{IDENTITY_LEVEL}}": html_escape((brief.get("identity_match") or {}).get("level") or ""),
        "{{IDENTITY_BASIS}}": html_escape((brief.get("identity_match") or {}).get("basis") or ""),
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
        "{{SOURCES}}": render_sources((brief.get("appendix") or {}).get("sources") or []),
    }
    return fill_template(TEMPLATE_PATH.read_text(encoding="utf-8"), mapping)


def render_sources(sources: list) -> str:
    if not sources:
        return "<p>None recorded.</p>"
    parts = ["<ul>"]
    for source in sources:
        title = html_escape(source.get("title") or "")
        url = html_escape(source.get("url") or "")
        evidence_id = html_escape(source.get("evidence_id") or "")
        parts.append(f"<li>{title} <span class=\"cite\">{evidence_id}</span> {url}</li>")
    parts.append("</ul>")
    return "".join(parts)


def try_weasyprint(html_path: Path, pdf_path: Path) -> bool:
    binary = "/usr/bin/weasyprint"
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        return False
    proc = subprocess.run(
        [binary, str(html_path), str(pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and pdf_path.is_file()


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


def build_queries(name: str, city: str, urls: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    codes: list[str] = []
    clean_name, name_codes = redact(name)
    clean_city, city_codes = redact(city)
    codes.extend(name_codes)
    codes.extend(city_codes)
    if contains_blocked_token(clean_name) or contains_blocked_token(clean_city):
        fail("address_token_in_query", "A query would have contained a blocked token.")
    queries: list[dict] = []
    quoted_name = escape_quotes(clean_name)
    quoted_city = escape_quotes(clean_city)
    if clean_name and clean_city:
        queries.append(f'"{quoted_name}" "{quoted_city}" professional profile company')
        queries.append(f'"{quoted_name}" "{quoted_city}" interview news community')
    elif clean_name:
        queries.append(f'"{quoted_name}" professional profile company')
        queries.append(f'"{quoted_name}" interview news community')
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
        queries.append(f'"{quoted_name}" {url}')
    safe = []
    for text in queries[:QUERY_CAP]:
        url_part = text.split(" ", 1)[-1] if text.count(" ") else ""
        body = text
        if url_part.startswith("http://") or url_part.startswith("https://"):
            body = text[: text.rfind(url_part)]
        if contains_blocked_token(body):
            fail("address_token_in_query", "A query would have contained a blocked token.")
        safe.append(text)
    listed = [{"id": f"q{i + 1}", "q": text} for i, text in enumerate(safe)]
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
        "config": cfg,
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
    clean_name, name_codes = redact(name)
    clean_city, city_codes = redact(city)
    codes = unique(name_codes + city_codes)
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
    queries, inaccessible, codes = build_queries(intake.get("name") or "", intake.get("city") or "", urls)
    if not queries:
        fail("no_queries", "No safe name-and-city query could be built.")
    result: dict = {"ok": True, "queries": queries}
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
    rows.append(record)
    save_evidence(path, rows)
    audit("evidence_add", client_id, {"evidence": 1}, actor)
    result: dict = {"ok": True, "evidence_id": evidence_id}
    if inaccessible:
        result["inaccessible"] = True
        result["fetched"] = False
    if truncated:
        result["truncated"] = True
    if codes:
        result["warnings"] = [warning(code) for code in codes]
    emit(result)


def cmd_candidates(client_id: str, opts: dict[str, list[str]]) -> None:
    gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    grouped: dict[int, list[dict]] = {}
    for row in load_evidence(path):
        if row.get("identity_status") == "inaccessible":
            continue
        grouped.setdefault(int(row["candidate"]), []).append(row)
    candidates = []
    for number in sorted(grouped):
        rows = grouped[number]
        labels = []
        for row in rows:
            label, _ = redact(row.get("title") or "")
            if label:
                labels.append(label)
        text = " · ".join(labels) if labels else f"Candidate {number}"
        if len(text) > 180:
            text = text[:179].rstrip() + "…"
        candidates.append({
            "n": number,
            "label": text,
            "evidence_ids": [row["evidence_id"] for row in rows],
        })
    write_json(path / "candidates.json", {"candidates": candidates})
    emit({"ok": True, "candidates": candidates})


def cmd_confirm(client_id: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
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
        write_json(path / "identity.json", {"status": "none", "confirmed_at": now_iso(), "evidence_ids": []})
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
    confirmed: list[str] = []
    for row in rows:
        if int(row.get("candidate") or 0) == number and row.get("identity_status") != "inaccessible":
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
    })
    audit("identity_confirm", client_id, {"confirmed": len(confirmed)}, actor)
    emit({"ok": True, "status": "confirmed", "candidate": number, "evidence_ids": confirmed})


def cmd_validate(client_id: str, brief_file: str, opts: dict[str, list[str]]) -> None:
    actor = gate(actor_of(opts), mutate=True)
    path = require_client(client_id)
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
    brief_path = path / "brief.json"
    if not brief_path.is_file():
        fail("not_validated", "No validated brief.json.")
    raw = json.loads(brief_path.read_text(encoding="utf-8"))
    result = evaluate_brief(path, raw)
    if not result["ok"]:
        fail("not_validated", "Stored brief failed validation.", {"errors": result["errors"]})
    write_json(brief_path, result["brief"])
    html = build_html(path, result["brief"])
    html_path = path / "brief.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = path / "brief.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
    wrote_pdf = try_weasyprint(html_path, pdf_path)
    audit("brief_render", client_id, {"html": 1, "pdf": 1 if wrote_pdf else 0}, actor)
    payload: dict = {"ok": True, "html": True, "pdf": wrote_pdf}
    if not wrote_pdf:
        payload["pdf_skipped"] = "weasyprint_unavailable"
    emit(payload)


def public_base() -> str:
    raw = os.environ.get("ARTIFACT_BASE_URL") or "https://artifacts.local"
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
    level = (brief.get("identity_match") or {}).get("level") or "confirmed"
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

    text = assemble(style, first, second)
    while len(text) > 300 and (len(first) > 24 or len(second) > 24 or style):
        if len(first) > 24:
            first = shrink(first, max(24, len(first) - 30))
        elif len(second) > 24:
            second = shrink(second, max(24, len(second) - 30))
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


def cmd_wrong_identity(client_id: str, opts: dict[str, list[str]]) -> None:
    # Privacy delete stays available when the skill is off (uninstall keeps the data).
    actor = gate(actor_of(opts), mutate=False)
    path = require_client(client_id)
    removed_artifact = 0
    delivery_path = path / "delivery.json"
    if delivery_path.is_file():
        record = json.loads(delivery_path.read_text(encoding="utf-8"))
        artifact = artifact_to_delete(record)
        if artifact and artifact.is_file():
            artifact.unlink()
            removed_artifact = 1
    shutil.rmtree(path)
    audit("wrong_identity", client_id, {"profiles": 1, "artifacts": removed_artifact}, actor)
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
    if command == "evidence":
        if not rest or rest[0] != "add":
            fail("usage", "evidence add <client_id>")
        positional, opts = parse_flags(rest[1:])
        if len(positional) != 1:
            fail("usage", "evidence add <client_id>")
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
    fail("usage", "Unknown command.")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except SystemExit:
        raise
    except Exception as exc:
        fail("internal", type(exc).__name__)
