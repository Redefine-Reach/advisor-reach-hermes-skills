#!/usr/bin/env python3
"""
Box-local: turn one Hermes session export into a redacted eval case line.

Nothing leaves the box until an operator copies the redacted JSONL line manually.
Redaction fails closed: exit 1 on residue, detector errors, or unknown field types.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

from redact import (
    REDACTION_VERSION,
    ExclusionRules,
    RedactionContext,
    RedactionError,
    UnsupportedFieldType,
    collect_session_text,
    load_forgotten,
    load_known_names,
    log_counts,
    redact_object,
    scan_residue_secondary,
    secure_mkdir,
    secure_write_text,
    session_should_exclude,
    write_manifest,
)

ROOT = Path(__file__).resolve().parent


def derive_session_index(case_id: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    digest = secrets.token_hex(4)
    return f"{case_id}-{digest}"


def build_case(
    *,
    case_id: str,
    suite: str,
    category: str,
    box: str,
    redacted: object,
    session_index: str,
    counts: dict[str, int],
) -> dict[str, object]:
    owner_text = ""
    if isinstance(redacted, dict):
        owner_text = (
            redacted.get("owner_text")
            or redacted.get("input")
            or (redacted.get("messages") or [{}])[0].get("content")
            or ""
        )
    if isinstance(owner_text, dict):
        owner_text = owner_text.get("owner_text") or ""

    assistant_text = ""
    if isinstance(redacted, dict):
        assistant_text = redacted.get("assistant_text") or redacted.get("final_reply") or ""

    return {
        "id": case_id,
        "suite": suite,
        "category": category,
        "box": box,
        "input": {"channel": "sms", "owner_text": str(owner_text)},
        "fixture": {
            "assistant_text": str(assistant_text),
            "tool_calls": redacted.get("tool_calls") if isinstance(redacted, dict) else [],
        },
        "expect": redacted.get("expect") if isinstance(redacted, dict) else {},
        "export_meta": {
            "session_index": session_index,
            "redaction_version": REDACTION_VERSION,
            "redaction_counts": counts,
            "ok": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export redacted session → eval case JSONL (no stdout payload).")
    parser.add_argument("--session", type=Path, required=True, help="Path to session JSON on the box")
    parser.add_argument("--id", required=True, help="Case id, e.g. mz-021")
    parser.add_argument("--suite", choices=["regression", "capability"], default="regression")
    parser.add_argument("--category", required=True, help="no_answer | send_draft | memory_save")
    parser.add_argument(
        "--out",
        type=Path,
        help="Append redacted case to this JSONL (default: cases-export.local.jsonl beside harness)",
    )
    parser.add_argument("--manifest", type=Path, help="Content-free manifest path (default: beside --out)")
    parser.add_argument("--box", default="e23fjkv6")
    parser.add_argument(
        "--known-names",
        type=Path,
        help="Per-box known names file (mode 0600, never commit)",
    )
    parser.add_argument("--rules", type=Path, help="do-not-keep rules.json path")
    parser.add_argument("--forgotten", type=Path, help="Forgotten phrases file (mode 0600)")
    parser.add_argument(
        "--session-index",
        help="Opaque session index for export_meta (default: derived from --id)",
    )
    args = parser.parse_args()

    dest = args.out or (ROOT / "cases-export.local.jsonl")
    manifest_path = args.manifest or dest.with_suffix(".manifest.json")

    try:
        raw_text = args.session.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
    except UnicodeDecodeError:
        print("export_blocked: decode_error", file=sys.stderr)
        return 1
    except json.JSONDecodeError:
        print("export_blocked: json_decode_error", file=sys.stderr)
        return 1

    try:
        rules = ExclusionRules.load(args.rules)
        forgotten = load_forgotten(args.forgotten)
        known = load_known_names(args.known_names)
    except (RedactionError, OSError, json.JSONDecodeError) as exc:
        print(f"export_blocked: config_error", file=sys.stderr)
        return 1

    exclude_reason = session_should_exclude(raw, rules, forgotten)
    if exclude_reason:
        print(f"excluded_sessions: 1 ({exclude_reason})", file=sys.stderr)
        return 0

    ctx = RedactionContext(known_names=known)
    try:
        redacted, _codes, ok, residue = redact_object(raw, ctx)
    except UnsupportedFieldType:
        print("export_blocked: unsupported_field_type", file=sys.stderr)
        return 1
    except RedactionError:
        print("export_blocked: redaction_error", file=sys.stderr)
        return 1

    blob = collect_session_text(redacted)
    residue2 = scan_residue_secondary(blob)
    if residue2:
        residue = list(dict.fromkeys([*residue, *residue2]))
        ok = False

    if not ok:
        log_counts(ctx.class_counts)
        print(f"export_blocked: residue={','.join(residue)}", file=sys.stderr)
        return 1

    session_index = derive_session_index(args.id, args.session_index)
    case = build_case(
        case_id=args.id,
        suite=args.suite,
        category=args.category,
        box=args.box,
        redacted=redacted,
        session_index=session_index,
        counts=dict(ctx.class_counts),
    )
    case["export_meta"]["ok"] = True

    line = json.dumps(case, ensure_ascii=False) + "\n"

    tmp_base = Path(tempfile.mkdtemp(prefix="mz-export-", dir=dest.parent))
    try:
        os.chmod(tmp_base, 0o700)
        tmp_case = tmp_base / "case.jsonl"
        secure_write_text(tmp_case, line)
        secure_mkdir(dest.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(dest, flags, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line)
        write_manifest(manifest_path, ctx.class_counts)
    finally:
        for child in tmp_base.iterdir():
            child.unlink(missing_ok=True)
        tmp_base.rmdir()

    log_counts(ctx.class_counts)
    print(f"exported: session_index={session_index} bytes={len(line.encode('utf-8'))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
