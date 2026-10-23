#!/usr/bin/env python3
"""RED-596 draft outcome log: one JSON line per final SMS draft outcome."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

OUTCOME_KIND = "sms"
OUTCOME_NAMES = frozenset({"sent_as_is", "sent_after_edit", "cancelled", "ignored", "refused"})
REFUSE_REASON_RE = re.compile(r"^[a-z][a-z_]{0,31}$")
RESTAGEABLE_REFUSE_REASONS = frozenset({"unfilled_placeholder", "opted_out", "over_length"})
PROVIDER_REFUSE_REASONS = frozenset({"provider_error", "provider_no_id"})
OUTCOME_LINE_KEYS = frozenset(
    {
        "ts",
        "draft_id",
        "kind",
        "outcome",
        "edit_rounds",
        "replaces_chain",
        "body_hash_first",
        "body_hash_final",
        "edit_distance",
        "len_first",
        "len_final",
        "hours_to_decision",
        "box_slug",
        "refuse_reason",
    }
)
EXPORT_ROW_KEYS = frozenset({"day", "box", "kind", "outcome", "count"})
DRAFT_ID_RE = re.compile(r"^[0-9a-f]{16}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://|www\.", re.I)
PHONEISH_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
DIGIT_RUN_RE = re.compile(r"\d{9,}")
SSN_RE = re.compile(r"\d{3}-\d{2}-\d{4}")


def utc_now() -> datetime:
    if os.environ.get("SMS_SEND_CONFIRMED_TEST") == "1":
        raw = str(os.environ.get("SMS_NOW", "")).strip()
        if raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
    raw = os.environ.get("DRAFT_OUTCOME_NOW")
    if raw:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def outcomes_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("DRAFT_OUTCOMES_PATH", "/opt/data/audit/draft-outcomes.jsonl"))


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            row.append(min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = row
    return prev[-1]


def hours_between(start: str, end: datetime) -> float:
    try:
        created = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = end - created.astimezone(timezone.utc)
    return round(max(0.0, delta.total_seconds()) / 3600.0, 4)


def build_replaces_chain(drafts_dir: Path, draft: dict) -> list[str]:
    chain: list[str] = []
    current = draft
    seen: set[str] = set()
    while True:
        prev_id = str(current.get("replaces") or "").strip()
        if not prev_id or prev_id in seen:
            break
        if not DRAFT_ID_RE.fullmatch(prev_id):
            break
        seen.add(prev_id)
        chain.insert(0, prev_id)
        path = drafts_dir / f"{prev_id}.json"
        if not path.is_file():
            break
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            break
        if not isinstance(current, dict):
            break
    return chain


def chain_anchor(draft: dict) -> str:
    return str(draft.get("chain_created_at") or draft.get("created_at") or "")


def never_contains_violations(line: dict) -> list[str]:
    hits: list[str] = []
    for key in ("body", "dest", "approver", "why", "why_line", "note"):
        if key in line:
            hits.append(f"field:{key}")
    chain = line.get("replaces_chain")
    if isinstance(chain, list):
        for item in chain:
            token = str(item or "")
            if not DRAFT_ID_RE.fullmatch(token):
                hits.append("bad_chain_id")
    for key, value in line.items():
        if key == "replaces_chain":
            continue
        if key in {"body_hash_first", "body_hash_final", "draft_id", "refuse_reason"}:
            continue
        text = json.dumps(value, ensure_ascii=True)
        if EMAIL_RE.search(text):
            hits.append("email")
        if URL_RE.search(text):
            hits.append("url")
        if PHONEISH_RE.search(text):
            hits.append("phone")
        if DIGIT_RUN_RE.search(text):
            hits.append("digit_run")
        if SSN_RE.search(text):
            hits.append("ssn_shape")
    return hits


def validate_outcome_line(line: dict) -> None:
    if set(line.keys()) - OUTCOME_LINE_KEYS:
        extra = set(line.keys()) - OUTCOME_LINE_KEYS
        raise ValueError(f"unexpected outcome fields: {sorted(extra)}")
    outcome_name = str(line.get("outcome") or "")
    required = OUTCOME_LINE_KEYS - {"box_slug", "refuse_reason"}
    if outcome_name == "refused":
        required = required | {"refuse_reason"}
    for key in required:
        if key not in line:
            raise ValueError(f"missing outcome field: {key}")
    if outcome_name != "refused" and "refuse_reason" in line:
        raise ValueError("refuse_reason only allowed when outcome is refused")
    if line.get("kind") != OUTCOME_KIND:
        raise ValueError("kind must be sms")
    if outcome_name not in OUTCOME_NAMES:
        raise ValueError("invalid outcome name")
    if outcome_name == "refused":
        reason = str(line.get("refuse_reason") or "")
        if not REFUSE_REASON_RE.fullmatch(reason):
            raise ValueError("invalid refuse_reason code")
        if DIGIT_RUN_RE.search(reason):
            raise ValueError("refuse_reason must not contain digits")
    if not DRAFT_ID_RE.fullmatch(str(line.get("draft_id") or "")):
        raise ValueError("draft_id must be 16 hex chars")
    if not isinstance(line.get("replaces_chain"), list):
        raise ValueError("replaces_chain must be a list")
    violations = never_contains_violations(line)
    if violations:
        raise ValueError(f"never-contains guard: {violations}")


def draft_has_final_line(path: Path, draft_id: str) -> bool:
    if not path.is_file() or not draft_id:
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("draft_id") == draft_id:
            return True
    return False


def scan_export_rows(rows: list[dict]) -> list[str]:
    hits: list[str] = []
    blob = json.dumps(rows, ensure_ascii=True)
    if EMAIL_RE.search(blob):
        hits.append("email")
    if URL_RE.search(blob):
        hits.append("url")
    if PHONEISH_RE.search(blob):
        hits.append("phone")
    if SSN_RE.search(blob):
        hits.append("ssn_shape")
    if "body" in blob or "note" in blob:
        hits.append("body_or_note")
    return hits


def append_outcome(path: Path, line: dict) -> None:
    validate_outcome_line(line)
    payload = json.dumps(line, separators=(",", ":"), ensure_ascii=True, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def classify_sent(edit_rounds: int) -> str:
    return "sent_after_edit" if edit_rounds > 0 else "sent_as_is"


def outcome_from_draft(
    draft: dict,
    *,
    outcome: str,
    drafts_dir: Path,
    box_slug: str | None,
    decided_at: datetime | None = None,
    refuse_reason: str | None = None,
) -> dict:
    if outcome not in OUTCOME_NAMES and outcome != "sent":
        raise ValueError(outcome)
    if outcome == "refused" and not refuse_reason:
        raise ValueError("refuse_reason required for refused outcomes")
    if outcome != "refused" and refuse_reason:
        raise ValueError("refuse_reason only for refused outcomes")
    body = str(draft.get("body") or "")
    body_hash_final = str(draft.get("body_hash") or "")
    if body and not body_hash_final:
        raise ValueError("draft missing body_hash")
    if not body_hash_final and draft.get("body_hash_final"):
        body_hash_final = str(draft.get("body_hash_final"))
    len_final = int(draft.get("len_final") or len(body) or draft.get("body_len") or 0)
    body_hash_first = str(draft.get("body_hash_first") or body_hash_final or "")
    len_first = int(draft.get("len_first") or len_final)
    replaces_chain = build_replaces_chain(drafts_dir, draft)
    edit_rounds = len(replaces_chain)
    when = decided_at or utc_now()
    dist = int(draft.get("edit_distance") or 0)
    resolved = outcome
    if outcome == "sent":
        resolved = classify_sent(edit_rounds)
    line = {
        "ts": iso(when),
        "draft_id": str(draft.get("draft_id") or ""),
        "kind": OUTCOME_KIND,
        "outcome": resolved,
        "edit_rounds": edit_rounds,
        "replaces_chain": replaces_chain,
        "body_hash_first": body_hash_first,
        "body_hash_final": body_hash_final,
        "edit_distance": dist,
        "len_first": len_first,
        "len_final": len_final,
        "hours_to_decision": hours_between(chain_anchor(draft), when),
    }
    if box_slug:
        line["box_slug"] = box_slug
    if outcome == "refused":
        line["refuse_reason"] = str(refuse_reason or "")
    return line


def record_outcome(
    store_paths: dict[str, Path],
    draft: dict,
    *,
    outcome: str,
    box_slug: str | None = None,
    decided_at: datetime | None = None,
    refuse_reason: str | None = None,
) -> dict:
    line = outcome_from_draft(
        draft,
        outcome=outcome,
        drafts_dir=store_paths["drafts"],
        box_slug=box_slug,
        decided_at=decided_at,
        refuse_reason=refuse_reason,
    )
    out_path = store_paths.get("draft_outcomes") or outcomes_path()
    if draft_has_final_line(out_path, str(draft.get("draft_id") or "")):
        raise ValueError("duplicate_final")
    append_outcome(out_path, line)
    return line


def seed_chain_fields(record: dict, body: str, body_hash: str, created_at: str) -> None:
    record.setdefault("body_hash_first", body_hash)
    record.setdefault("len_first", len(body))
    record.setdefault("chain_created_at", created_at)
    record["chain_body_first"] = body
    record["edit_distance"] = 0


def inherit_chain_fields(record: dict, previous: dict, body: str, body_hash: str) -> None:
    record["replaces"] = str(previous.get("draft_id") or "")
    record["body_hash_first"] = str(previous.get("body_hash_first") or previous.get("body_hash") or body_hash)
    record["len_first"] = int(previous.get("len_first") or len(str(previous.get("body") or "")) or len(body))
    record["chain_created_at"] = str(previous.get("chain_created_at") or previous.get("created_at") or "")
    first_body = str(previous.get("chain_body_first") or previous.get("body") or body)
    record["chain_body_first"] = first_body
    record["edit_distance"] = edit_distance(first_body, body)


def refresh_edit_distance_from_first(draft: dict, body: str) -> None:
    first = str(draft.get("chain_body_first") or "")
    if first:
        draft["edit_distance"] = edit_distance(first, body)


def strip_plaintext_fields(data: dict, *, keep_chain_baseline: bool = False) -> None:
    """Drop staged message body from disk; keep why_line for RED-585 reuse guards."""
    data["body"] = ""
    if not keep_chain_baseline:
        data.pop("chain_body_first", None)


def mark_superseded(path: Path, data: dict) -> None:
    data["status"] = "superseded"
    strip_plaintext_fields(data)
    data["superseded_at"] = iso(utc_now())
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def parse_expiry(draft: dict) -> datetime:
    raw = str(draft.get("expires_at") or "")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sweep_one_expired(
    store_paths: dict[str, Path],
    path: Path,
    *,
    when: datetime,
    box_slug: str | None,
) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("status") != "pending":
        return None
    try:
        if when < parse_expiry(data):
            return None
    except ValueError:
        return None
    body = str(data.get("body") or "")
    data["body_hash_final"] = str(data.get("body_hash") or "")
    data["len_final"] = len(body)
    line = record_outcome(store_paths, data, outcome="ignored", box_slug=box_slug, decided_at=when)
    data["status"] = "ignored"
    data["cancelled_reason"] = "expired"
    strip_plaintext_fields(data)
    data["ignored_at"] = iso(when)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return line


def sweep_expired(
    store_paths: dict[str, Path],
    *,
    now: datetime | None = None,
    box_slug: str | None = None,
) -> list[dict]:
    when = now or utc_now()
    drafts_dir = store_paths["drafts"]
    written: list[dict] = []
    if not drafts_dir.exists():
        return written
    for path in sorted(drafts_dir.glob("*.json")):
        if path.name.startswith("."):
            continue
        line = _sweep_one_expired(store_paths, path, when=when, box_slug=box_slug)
        if line is not None:
            written.append(line)
    return written


def export_counts(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    buckets: dict[tuple[str, str, str, str], int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        day = str(row.get("ts") or "")[:10]
        box = str(row.get("box_slug") or "unknown")
        kind = str(row.get("kind") or OUTCOME_KIND)
        outcome = str(row.get("outcome") or "")
        key = (day, box, kind, outcome)
        buckets[key] = buckets.get(key, 0) + 1
    out = [
        {"day": day, "box": box, "kind": kind, "outcome": outcome, "count": count}
        for (day, box, kind, outcome), count in sorted(buckets.items())
    ]
    for row in out:
        if set(row.keys()) != EXPORT_ROW_KEYS:
            raise ValueError("exporter emitted extra fields")
    return out


def emit(obj: dict, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=True, sort_keys=True))
    return code


def cmd_sweep(_args: argparse.Namespace) -> int:
    drafts = Path(os.environ.get("SMS_DRAFT_DIR", "/opt/data/audit/sms-drafts"))
    store = {"drafts": drafts, "draft_outcomes": outcomes_path()}
    box_slug = str(os.environ.get("SMS_BOX_ID", "")).strip().lower() or None
    lines = sweep_expired(store, box_slug=box_slug)
    return emit({"ok": True, "ignored": len(lines), "outcomes": [row["draft_id"] for row in lines]})


def cmd_export(_args: argparse.Namespace) -> int:
    rows = export_counts(outcomes_path())
    return emit({"ok": True, "rows": rows})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="draft_outcome_log.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sweep", help="Expire pending drafts past TTL as ignored.").set_defaults(func=cmd_sweep)
    sub.add_parser("export", help="Emit day/box/kind/outcome counts only.").set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
