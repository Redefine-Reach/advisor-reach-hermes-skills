#!/usr/bin/env python3
"""CI check for rules/states/*.yaml (AX-3.13).

FAIL (exit 1):
  - a rule without last_verified, or last_verified not YYYY-MM-DD
  - a stale rule: today minus last_verified > 120 days, where "today" is the
    calendar date in America/Phoenix (no DST, UTC-7 all year), never UTC
  - fewer than 2 sources, except source_type == "standard_contract_form",
    which needs at least 1 source and a non-empty `caveat` telling the owner
    to check their signed contract
WARN (exit 0): effective_date is null/missing.
Usage: check_state_rules.py [--today YYYY-MM-DD] [FILE ...]  (default rules/states/*.yaml)
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import sys
from zoneinfo import ZoneInfo

import yaml

MAX_AGE_DAYS = 120
TZ = ZoneInfo("America/Phoenix")
CONTRACT = "standard_contract_form"


def phoenix_today(now: dt.datetime | None = None) -> dt.date:
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(TZ).date()


def _date(v):
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    if isinstance(v, str):
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            return None
    return None


def check_doc(doc, today: dt.date, label: str = ""):
    errors, warnings = [], []
    rules = (doc or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        return [f"{label}: no rules list"], warnings
    for r in rules:
        rid = f"{label}:{(r or {}).get('id', '?')}"
        lv = _date(r.get("last_verified"))
        if lv is None:
            errors.append(f"{rid}: last_verified missing or not YYYY-MM-DD")
        else:
            age = (today - lv).days
            if age > MAX_AGE_DAYS:
                errors.append(f"{rid}: stale, last_verified {lv} is {age} days old (limit {MAX_AGE_DAYS}, America/Phoenix)")
        sources = r.get("sources") or []
        if r.get("source_type") == CONTRACT:
            if len(sources) < 1:
                errors.append(f"{rid}: standard_contract_form rule needs 1 source")
            if not str(r.get("caveat") or "").strip():
                errors.append(f"{rid}: standard_contract_form rule needs a caveat (check your signed contract)")
        elif len(sources) < 2:
            errors.append(f"{rid}: needs 2 sources, has {len(sources)}")
        if r.get("effective_date") in (None, ""):
            warnings.append(f"{rid}: effective_date is null")
    return errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else phoenix_today()
    files = a.files or sorted(glob.glob("rules/states/*.yaml"))
    errs, warns = [], []
    for f in files:
        with open(f) as fh:
            e, w = check_doc(yaml.safe_load(fh), today, f)
        errs += e
        warns += w
    for w in warns:
        print(f"::warning::{w}")
    for e in errs:
        print(f"::error::{e}")
    print(f"checked {len(files)} file(s) as of {today} America/Phoenix: {len(errs)} error(s), {len(warns)} warning(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
