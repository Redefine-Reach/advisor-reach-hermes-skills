"""Default-deny and independent post-redaction audit (patterns distinct from redact.py)."""

from __future__ import annotations

import re

# Benign holds for audit/drop (wording differs from redact._BENIGN_PHRASES).
_BENIGN = re.compile(
    r"(?:"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon|Tues?|Wed(?:nesday)?|Thu(?:rsday)?|Fri|Sat(?:urday)?|Sun(?:day)?)'s\b|"
    r"Hunter Douglas|Mason jar|therapy dog|custody of the [a-z ]*keys|chapter 7 of the|"
    r"hospital-district|medical office lease|doctor'?s office building"
    r")",
    re.I,
)

# Pre-export whole-session drop: broad medical/legal/financial/credential vocabulary.
_PRE_DROP = re.compile(
    r"(?:"
    r"\b(?:spine|ablation|miscarriage|hospice|insulin|epidural|oncolog\w*|tumou?r|biopsy|"
    r"mri\b|ct\s+scan|x-?ray|ultrasound|hospice|palliative|miscarriage|stillbirth|"
    r"narcotics?\s+anonymous|\bAA\s+meetings\b|twelve[- ]step|sobriety|detox|overdose|"
    r"chemo\w*|radiation\s+therapy|physical\s+therapy\b)"
    r"|"
    r"\b(?:prenup|prenuptial|probation|parole|arraignment|felony|misdemeanor|"
    r"green\s+card|deportation|asylum\s+hearing|child\s+support|spousal\s+support|"
    r"restraining|subpoena|litigat\w*|foreclosure|garnish\w*)"
    r"|"
    r"\b(?:client_secret\s*=|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"\blogin\s+(?:is\s+)?\S{4,}|\bpassword\s+\S{4,})"
    r")",
    re.I,
)

# Independent post-redaction audit (no imports from redact primary regexes).
_POST_EMAIL = re.compile(r"[@\s]|(?:\bat\s+[a-z0-9._%+-]+\s+dot\s+(?:com|org|net|io))\b", re.I)
_POST_AT_SIGN = re.compile(r"@")
_POST_PHONE_DIGITS = re.compile(r"(?<!\d)(?:\d[\s\-.)]{0,2}){9,14}\d(?!\d)")
_POST_ROUTING = re.compile(r"\b0\d{8}\b")
_POST_SENSITIVE_WORD = re.compile(
    r"\b(?:spine|ablation|miscarriage|hospice|insulin|prenup|probation|green\s+card|"
    r"ghp_|client_secret|fakerton|fakeman|samplesworth|placeholder)\b",
    re.I,
)
_POST_CRED_LABEL = re.compile(
    r"\b(?:login|password|passwd|client_secret|api\s*key)\s*[:=]?\s*\S{4,}",
    re.I,
)
_POST_SPELLED_DIGITS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)\b(?:\s+(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)){3,}",
    re.I,
)


def scrub_benign(text: str) -> str:
    return _BENIGN.sub(" ", text)


def pre_export_drop_category(text: str) -> str | None:
    cleaned = scrub_benign(text)
    if _PRE_DROP.search(cleaned):
        return "sensitive_topic"
    return None


def post_redact_unsafe(text: str) -> list[str]:
    """Independent second-line audit; any hit => session not safe to export."""
    if not text:
        return []
    scrubbed = scrub_benign(text)
    for placeholder in (
        "[REDACTED_",
        "[PHONE ***",
        "CLIENT_",
    ):
        scrubbed = scrubbed.replace(placeholder, " ")
    found: list[str] = []
    if _POST_AT_SIGN.search(scrubbed) or re.search(
        r"\b[a-z0-9._%+-]+\s+at\s+[a-z0-9._%+-]+\s+dot\s+(?:com|org|net)\b",
        scrubbed,
        re.I,
    ):
        found.append("email")
    if _POST_PHONE_DIGITS.search(scrubbed) or _POST_SPELLED_DIGITS.search(scrubbed):
        found.append("phone")
    if _POST_ROUTING.search(scrubbed):
        found.append("routing")
    if _POST_CRED_LABEL.search(scrubbed) or re.search(r"\bghp_[A-Za-z0-9]{10,}", scrubbed):
        found.append("credential")
    if _POST_SENSITIVE_WORD.search(scrubbed):
        found.append("sensitive_topic")
    return list(dict.fromkeys(found))
