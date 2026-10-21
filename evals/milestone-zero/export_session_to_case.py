#!/usr/bin/env python3
"""
Box-local: turn one Hermes session export into a redacted eval case line.

Nothing leaves the box until an operator copies the redacted JSONL line manually.
Redaction fails closed: exit 1 if sensitive residue remains.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from redact import redact_fail_closed

ROOT = Path(__file__).resolve().parent


def walk_strings(obj: object, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(obj, str):
        found.append((path, obj))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(walk_strings(value, f"{path}/{key}" if path else key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(walk_strings(value, f"{path}/{index}"))
    return found


def redact_object(obj: object) -> tuple[object, list[str], bool]:
    residue_all: list[str] = []
    if isinstance(obj, str):
        cleaned, codes, ok, residue = redact_fail_closed(obj)
        residue_all.extend(residue)
        return cleaned, codes, ok
    if isinstance(obj, dict):
        out = {}
        ok_all = True
        codes_all: list[str] = []
        for key, value in obj.items():
            new_val, codes, ok = redact_object(value)
            out[key] = new_val
            codes_all.extend(codes)
            ok_all = ok_all and ok
        return out, codes_all, ok_all
    if isinstance(obj, list):
        out_list = []
        ok_all = True
        codes_all: list[str] = []
        for item in obj:
            new_val, codes, ok = redact_object(item)
            out_list.append(new_val)
            codes_all.extend(codes)
            ok_all = ok_all and ok
        return out_list, codes_all, ok_all
    return obj, [], True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export redacted session → eval case JSONL (stdout).")
    parser.add_argument("--session", type=Path, required=True, help="Path to session JSON on the box")
    parser.add_argument("--id", required=True, help="Case id, e.g. mz-021")
    parser.add_argument("--suite", choices=["regression", "capability"], default="regression")
    parser.add_argument("--category", required=True, help="no_answer | send_draft | memory_save")
    parser.add_argument(
        "--out",
        type=Path,
        help="Append redacted case to this JSONL (default: cases-export.local.jsonl beside harness)",
    )
    parser.add_argument("--box", default="e23fjkv6")
    args = parser.parse_args()

    raw = json.loads(args.session.read_text(encoding="utf-8"))
    redacted, codes, ok = redact_object(raw)
    if not ok:
        print("export_blocked: redaction residue remains; case not written", file=sys.stderr)
        return 1

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

    case = {
        "id": args.id,
        "suite": args.suite,
        "category": args.category,
        "box": args.box,
        "input": {"channel": "sms", "owner_text": str(owner_text)},
        "fixture": {
            "assistant_text": str(assistant_text),
            "tool_calls": redacted.get("tool_calls") if isinstance(redacted, dict) else [],
        },
        "expect": redacted.get("expect") if isinstance(redacted, dict) else {},
        "export_meta": {"redaction_codes": list(dict.fromkeys(codes)), "source": str(args.session)},
    }

    line = json.dumps(case, ensure_ascii=False) + "\n"
    dest = args.out or (ROOT / "cases-export.local.jsonl")
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(line)
    print(f"wrote {args.id} -> {dest}", file=sys.stderr)
    sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
