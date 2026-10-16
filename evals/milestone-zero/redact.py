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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redact sensitive spans from session text.")
    parser.add_argument("--in", dest="inp", type=Path, required=True)
    parser.add_argument("--out", dest="out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.inp.read_text(encoding="utf-8")
    cleaned, codes = redact(raw)
    args.out.write_text(cleaned, encoding="utf-8")
    if codes:
        print(f"redacted: {','.join(codes)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
