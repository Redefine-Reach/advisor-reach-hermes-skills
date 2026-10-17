#!/usr/bin/env python3
"""
Box-local: turn one Hermes session export into a redacted eval case line.

This is the only supported redaction entrypoint (no redact.py CLI).
Exit codes: 0 exported; 1 blocked (residue/decode/unsupported); 2 excluded (drop rules).
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
    EXIT_BLOCKED,
    EXIT_EXCLUDED,
    EXIT_OK,
    REDACTION_VERSION,
    ExclusionRules,
    RedactionContext,
    RedactionError,
    UnsupportedFieldType,
    collect_session_text,
    load_forgotten,
    load_known_names,
    load_session_payload,
    log_counts,
    log_excluded,
    redact_object,
    scan_residue_secondary,
    own_residue,
    secure_mkdir,
    secure_write_text,
    session_drop_reason,
    write_manifest,
)

ROOT = Path(__file__).resolve().parent


def redacted_transcript(redacted: object) -> str:
    if isinstance(redacted, dict):
        owner = redacted.get("owner_text")
        if isinstance(owner, str) and owner.strip():
            return owner
        lines: list[str] = []
        for msg in redacted.get("messages") or []:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    lines.append(content)
        if lines:
            return "\n".join(lines)
    return collect_session_text(redacted)


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
    parser.add_argument("--session", type=Path, required=True, help="Session JSON or transcript .txt on the box")
    parser.add_argument("--id", help="Case id, e.g. mz-021 (required when appending JSONL)")
    parser.add_argument("--suite", choices=["regression", "capability"], default="regression")
    parser.add_argument("--category", help="no_answer | send_draft | memory_save (required when appending JSONL)")
    parser.add_argument(
        "--out",
        type=Path,
        help="Append redacted case to this JSONL (default: cases-export.local.jsonl beside harness)",
    )
    parser.add_argument(
        "--redacted-text-out",
        type=Path,
        help="Write redacted transcript text here (used by check_leaks; no JSONL unless --out is set)",
    )
    parser.add_argument("--manifest", type=Path, help="Content-free manifest path (default: beside --out)")
    parser.add_argument("--box", default="e23fjkv6")
    parser.add_argument("--known-names", type=Path, help="Per-box known names file (mode 0600, never commit)")
    parser.add_argument("--rules", type=Path, help="do-not-keep rules.json path")
    parser.add_argument("--forgotten", type=Path, help="Forgotten phrases file (mode 0600)")
    parser.add_argument("--session-index", help="Opaque session index for export_meta")
    parser.add_argument("--owner-name", default="Alex", help="Owner first name kept during name redaction")
    args = parser.parse_args()

    append_jsonl = args.out is not None or args.redacted_text_out is None
    if append_jsonl and (not args.id or not args.category):
        print("export_blocked: missing_id_or_category", file=sys.stderr)
        return EXIT_BLOCKED

    dest = args.out or (ROOT / "cases-export.local.jsonl")
    if args.manifest:
        manifest_path = args.manifest
    elif args.redacted_text_out and not append_jsonl:
        manifest_path = args.redacted_text_out.with_suffix(".manifest.json")
    else:
        manifest_path = dest.with_suffix(".manifest.json")

    try:
        raw = load_session_payload(args.session)
    except UnicodeDecodeError:
        print("export_blocked: decode_error", file=sys.stderr)
        return EXIT_BLOCKED
    except (json.JSONDecodeError, ValueError):
        print("export_blocked: json_decode_error", file=sys.stderr)
        return EXIT_BLOCKED

    try:
        rules = ExclusionRules.load(args.rules)
        forgotten = load_forgotten(args.forgotten)
        known = load_known_names(args.known_names)
    except (RedactionError, OSError, json.JSONDecodeError):
        print("export_blocked: config_error", file=sys.stderr)
        return EXIT_BLOCKED

    drop = session_drop_reason(raw, rules, forgotten)
    if drop:
        log_excluded(drop)
        return EXIT_EXCLUDED

    ctx = RedactionContext(known_names=known, owner_name=args.owner_name)
    try:
        redacted, _codes, ok, residue = redact_object(raw, ctx)
    except UnsupportedFieldType:
        print("export_blocked: unsupported_field_type", file=sys.stderr)
        return EXIT_BLOCKED
    except RedactionError:
        print("export_blocked: redaction_error", file=sys.stderr)
        return EXIT_BLOCKED

    blob = redacted_transcript(redacted)
    residue2 = scan_residue_secondary(blob) + own_residue(blob)
    residue2 = [r for r in dict.fromkeys([*residue, *residue2]) if r not in ("phone", "name")]
    if residue2 or not ok:
        log_counts(ctx.class_counts)
        print(f"export_blocked: residue={','.join(residue2 or residue)}", file=sys.stderr)
        return EXIT_BLOCKED

    transcript = blob

    scratch_parent = (
        dest.parent
        if append_jsonl
        else (args.redacted_text_out.parent if args.redacted_text_out else ROOT)
    )
    tmp_base = Path(tempfile.mkdtemp(prefix="mz-export-", dir=scratch_parent))
    try:
        os.chmod(tmp_base, 0o700)
        if args.redacted_text_out:
            secure_write_text(args.redacted_text_out, transcript + ("\n" if not transcript.endswith("\n") else ""))
        if append_jsonl:
            session_index = derive_session_index(args.id or "mz", args.session_index)
            case = build_case(
                case_id=args.id or "mz",
                suite=args.suite,
                category=args.category or "no_answer",
                box=args.box,
                redacted=redacted,
                session_index=session_index,
                counts=dict(ctx.class_counts),
            )
            line = json.dumps(case, ensure_ascii=False) + "\n"
            secure_mkdir(dest.parent)
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            fd = os.open(dest, flags, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line)
            write_manifest(manifest_path, ctx.class_counts)
            log_counts(ctx.class_counts)
            print(
                f"exported: session_index={session_index} bytes={len(line.encode('utf-8'))}",
                file=sys.stderr,
            )
        else:
            write_manifest(manifest_path, ctx.class_counts)
            log_counts(ctx.class_counts)
            print("exported: redacted_text_only", file=sys.stderr)
    finally:
        for child in tmp_base.iterdir():
            child.unlink(missing_ok=True)
        tmp_base.rmdir()

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
