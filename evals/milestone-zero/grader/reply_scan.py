#!/usr/bin/env python3
"""Scan ARIN's raw replies before they are written anywhere for a person to read (Vault, PR #57).

Uses the exporter's own redaction (redact.redact_text + the cross-turn name map, with the
known-names file when given) and its credential patterns, plus common API-key shapes.

  * credential: any hit BLOCKS the reply. run_mvq never grades it (status "blocked_credential",
    never PASS) and never writes it to --replies-out; pick_agreement writes no sheet at all.
  * phone / email / health / name: counted and flagged for David (counts only, never values).
  * redacted: the reply text after the exporter's redaction, used on the blind rating sheet.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import redact as _redact  # noqa: E402  (the exporter's redaction module)

# Common key/token shapes not already in the exporter's value patterns (value-shaped only, so a
# reply that merely says "your API key" is not a hit).
_EXTRA_KEY_PATTERNS = [
    re.compile(p)
    for p in (
        r"\bsk-(?:proj-|ant-|or-)?[A-Za-z0-9_\-]{16,}",
        r"\b(?:rk|pk|sk)_(?:live|test)_[A-Za-z0-9]{6,}",
        r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\bAIza[0-9A-Za-z_\-]{30,}",
        r"\bAKIA[0-9A-Z]{12,}",
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\bKEY[0-9A-F]{20,}",
    )
]
# Flag-only health words beyond the exporter's drop lexicon (a reply is graded, not dropped).
_EXTRA_HEALTH = re.compile(
    r"\b(?:dialysis|kidney|cardiac|stroke|seizure|oncolog\w*|psychiatr\w*|hospice|insulin|HIV|"
    r"miscarriage|surgery|disease|mental health)\b",
    re.I,
)


def _name_map_pass(text: str, name_map: dict[str, str]) -> str:
    if not name_map:
        return text
    names = sorted(name_map, key=len, reverse=True)
    pat = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    return pat.sub(lambda m: name_map[m.group(1).lower()], text)


def load_known(path: Path | None) -> list[str]:
    """Known names via the exporter's loader (the file must be 0600, like the export run)."""
    return _redact.load_known_names(path) if path is not None else []


def has_credential(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in (*_redact._CRED_PATTERNS, *_EXTRA_KEY_PATTERNS))


def scan_reply(text: str, known_names: list[str] | None = None, owner_name: str = "") -> dict[str, Any]:
    """Return {"credential": bool, "counts": {phone,email,health,name,credential}, "redacted": str}."""
    text = text or ""
    ctx = _redact.RedactionContext(known_names=list(known_names or []), owner_name=owner_name)
    redacted, _codes = _redact.redact_text(text, ctx)
    redacted = _name_map_pass(redacted, ctx._name_map)
    cc = ctx.class_counts
    health = len(_redact._HEALTH_DROP.findall(text)) + len(_EXTRA_HEALTH.findall(text))
    cred_hits = sum(len(p.findall(text)) for p in (*_redact._CRED_PATTERNS, *_EXTRA_KEY_PATTERNS))
    credential = cred_hits > 0 or cc.get("credential", 0) > 0 or has_credential(redacted)
    counts = {
        "credential": max(cred_hits, cc.get("credential", 0)),
        "phone": cc.get("phone", 0),
        "email": cc.get("email", 0),
        "health": health,
        "name": cc.get("name", 0),
    }
    return {"credential": credential, "counts": counts, "redacted": redacted}


def flag_summary(counts: dict[str, int]) -> list[str]:
    """Which kinds David should look at for this reply (kinds only)."""
    return [k for k in ("phone", "email", "health") if counts.get(k)]
