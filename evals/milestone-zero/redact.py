#!/usr/bin/env python3
"""Redact health, SSN, and account numbers before log text becomes an eval case."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SSN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
ACCOUNT = re.compile(r"\b(?:acct|account)\s*#?\s*(\d{8,17})\b", re.IGNORECASE)
DIGITS_LONG = re.compile(r"\b\d{9,17}\b")
HEALTH = re.compile(
    r"\b(?:diagnosed with|treatment for|patient has|hip replacement|chemotherapy|"
    r"bipolar disorder|diabetes type)\b[^.\n]{0,80}",
    re.IGNORECASE,
)
PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

SENSITIVE_RESIDUE = [
    (SSN, "ssn"),
    (ACCOUNT, "account"),
    (HEALTH, "health"),
]


def redact(text: str) -> tuple[str, list[str]]:
    codes: list[str] = []
    out = text
    if SSN.search(out):
        codes.append("ssn")
        out = SSN.sub("[REDACTED_SSN]", out)
    if ACCOUNT.search(out):
        codes.append("account")
        out = ACCOUNT.sub("[REDACTED_ACCOUNT]", out)
    if DIGITS_LONG.search(out):
        codes.append("long_digits")
        out = DIGITS_LONG.sub("[REDACTED_DIGITS]", out)
    if HEALTH.search(out):
        codes.append("health")
        out = HEALTH.sub("[REDACTED_HEALTH]", out)
    if PHONE.search(out):
        codes.append("phone")
        out = PHONE.sub("[REDACTED_PHONE]", out)
    return out, codes


def redact_fail_closed(text: str) -> tuple[str, list[str], bool, list[str]]:
    """Return (cleaned, codes_applied, ok, residue_kinds). ok is false if sensitive patterns remain."""
    cleaned, codes = redact(text)
    residue: list[str] = []
    for pattern, kind in SENSITIVE_RESIDUE:
        if pattern.search(cleaned):
            residue.append(kind)
    ok = len(residue) == 0
    return cleaned, codes, ok, residue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redact sensitive spans from session text.")
    parser.add_argument("--in", dest="inp", type=Path, required=True)
    parser.add_argument("--out", dest="out", type=Path, required=True)
    parser.add_argument(
        "--fail-closed",
        action="store_true",
        help="Exit 1 if any sensitive pattern remains after redaction",
    )
    args = parser.parse_args(argv)
    raw = args.inp.read_text(encoding="utf-8")
    cleaned, codes, ok, residue = redact_fail_closed(raw)
    args.out.write_text(cleaned, encoding="utf-8")
    if codes:
        print(f"redacted: {','.join(codes)}", file=sys.stderr)
    if args.fail_closed and not ok:
        print(f"redaction_failed: residue={','.join(residue)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
