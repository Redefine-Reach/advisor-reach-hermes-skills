#!/usr/bin/env python3
"""CI check for rules/states/*.yaml (AX-3.13).

FAIL (exit 1):
  - a rule without last_verified, or last_verified not YYYY-MM-DD
  - a stale rule: today minus last_verified > 120 days, where "today" is the
    calendar date in America/Phoenix (no DST, UTC-7 all year), never UTC
  - a missing or unknown category
  - category "contract terms" may pass with one source only when that source
    is the AZ REALTORS contract form labeled "standard contract form, Feb 2026"
    and reminder_text includes "check your signed contract"
  - statute, ADRE, and every other known category need 2 or more independent
    sources (different URLs or publishers)
Each failure prints the rule id, the category, the number of sources found,
and the reason.
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
CONTRACT_TERMS = "contract terms"
FORM_LABEL = "standard contract form, Feb 2026"
CAVEAT = "check your signed contract"
TWO_SOURCE_REASON = "needs 2 sources (independent: different URLs or publishers)"
# Reminder kinds already used in rules/states, plus the source-policy names.
KNOWN_CATEGORIES = frozenset({
    CONTRACT_TERMS,
    "statute",
    "ADRE",
    "license_renewal",
    "continuing_ed",
    "contract_deadline",
    "disclosure",
    "other",
    "contingency",
    "checklist",
})


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


def _sources(rule):
    sources = (rule or {}).get("sources")
    return sources if isinstance(sources, list) else []


def _category_label(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "missing"


def _fail(rid, category, n_sources, reason):
    return f"{rid}: category={category}: sources={n_sources}: {reason}"


def _is_az_realtors(publisher):
    text = " ".join(str(publisher or "").casefold().replace(".", " ").split())
    if "realtors" not in text:
        return False
    return "arizona" in text or "az" in set(text.split())


def _is_feb2026_form(source, rule):
    """True when the source is the AZ REALTORS form labeled FORM_LABEL.

    An explicit source label must match that string. AZ.yaml records the same
    edition as source_edition Feb 2026 plus source_type standard_contract_form.
    """
    if not isinstance(source, dict) or not _is_az_realtors(source.get("publisher")):
        return False
    label = source.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip() == FORM_LABEL
    edition = str(rule.get("source_edition") or source.get("edition") or "").strip()
    source_type = str(rule.get("source_type") or "").casefold()
    edition_ok = edition in {"Feb 2026", "February 2026"}
    type_ok = "standard_contract_form" in source_type or "standard contract form" in source_type
    return edition_ok and type_ok


def _independent_count(sources):
    seen = set()
    for src in sources:
        if isinstance(src, dict):
            url = str(src.get("url") or "").strip()
            publisher = str(src.get("publisher") or "").strip()
        else:
            url, publisher = "", ""
        seen.add((url, publisher))
    return len(seen)


def _source_errors(rule, rid):
    sources = _sources(rule)
    n = len(sources)
    raw = rule.get("category")
    label = _category_label(raw)
    if label == "missing" or label not in KNOWN_CATEGORIES:
        return [_fail(rid, label, n, "missing or unknown category")]
    if label == CONTRACT_TERMS:
        indep = _independent_count(sources)
        if indep >= 2:
            return []
        dicts = [s for s in sources if isinstance(s, dict)]
        if indep == 1 and dicts:
            if not _is_feb2026_form(dicts[0], rule):
                return [_fail(
                    rid, label, n,
                    f"single source is not the AZ REALTORS contract form labeled '{FORM_LABEL}'",
                )]
            reminder = str(rule.get("reminder_text") or "")
            if CAVEAT not in reminder.casefold():
                return [_fail(
                    rid, label, n,
                    f"reminder text must include the caveat '{CAVEAT}'",
                )]
            return []
        return [_fail(
            rid, label, n,
            f"contract terms need the AZ REALTORS contract form labeled '{FORM_LABEL}' or 2 independent sources",
        )]
    if _independent_count(sources) < 2:
        return [_fail(rid, label, n, TWO_SOURCE_REASON)]
    return []


def check_doc(doc, today: dt.date, label: str = ""):
    errors, warnings = [], []
    rules = (doc or {}).get("rules")
    if not isinstance(rules, list) or not rules:
        return [f"{label}: no rules list"], warnings, 0
    passed = 0
    for r in rules:
        r = r or {}
        rid = f"{label}:{r.get('id', '?')}"
        n = len(_sources(r))
        cat = _category_label(r.get("category"))
        before = len(errors)
        lv = _date(r.get("last_verified"))
        if lv is None:
            errors.append(_fail(rid, cat, n, "last_verified missing or not YYYY-MM-DD"))
        else:
            age = (today - lv).days
            if age > MAX_AGE_DAYS:
                errors.append(_fail(
                    rid, cat, n,
                    f"stale, last_verified {lv} is {age} days old (limit {MAX_AGE_DAYS}, America/Phoenix)",
                ))
        errors.extend(_source_errors(r, rid))
        if r.get("effective_date") in (None, ""):
            warnings.append(f"{rid}: effective_date is null")
        if len(errors) == before:
            passed += 1
    return errors, warnings, passed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else phoenix_today()
    files = a.files or sorted(glob.glob("rules/states/*.yaml"))
    errs, warns, passed = [], [], 0
    for f in files:
        with open(f) as fh:
            e, w, p = check_doc(yaml.safe_load(fh), today, f)
        errs += e
        warns += w
        passed += p
    for w in warns:
        print(f"::warning::{w}")
    for e in errs:
        print(f"::error::{e}")
    print(
        f"checked {len(files)} file(s) as of {today} America/Phoenix: "
        f"{passed} rule(s) passed, {len(errs)} error(s), {len(warns)} warning(s)"
    )
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
