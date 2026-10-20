#!/usr/bin/env python3
"""
Box-local: turn one Hermes session export into a redacted eval case line.

This is the only supported redaction entrypoint (no redact.py CLI).
Exit codes: 0 exported; 1 blocked (residue/decode/unsupported, or a case with an empty owner
message or empty ARIN reply); 2 excluded (drop rules).
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    post_export_safety_flags,
    scan_residue_secondary,
    secure_mkdir,
    secure_write_text,
    session_drop_reason,
    is_structural_value,
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
                if str(msg.get("role") or "").lower() in NON_TEXT_ROLES:
                    continue  # tool/system turn text never goes into the transcript (Vault G1)
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


NON_TEXT_ROLES = frozenset({"tool", "system", "function", "developer"})
OWNER_ROLES = frozenset({"user", "owner", "human"})
ARIN_ROLES = frozenset({"assistant", "arin", "agent"})
DEFAULT_CONTEXT_TURNS = 10


def _turns(redacted: object) -> tuple[list[dict[str, str]], int]:
    """Owner/ARIN string turns from a redacted session, in order; count of other turns skipped."""
    out: list[dict[str, str]] = []
    skipped = 0
    msgs = redacted.get("messages") if isinstance(redacted, dict) else None
    for msg in msgs or []:
        if not isinstance(msg, dict):
            skipped += 1
            continue
        role = str(msg.get("role") or "").strip().lower()
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            skipped += 1
            continue
        if role in OWNER_ROLES:
            out.append({"role": "owner", "content": content})
        elif role in ARIN_ROLES:
            out.append({"role": "arin", "content": content})
        else:
            skipped += 1  # tool/system turns are not kept
    return out, skipped


def split_turns(
    turns: list[dict[str, str]], context_turns: int
) -> tuple[list[dict[str, str]], str, str, bool]:
    """Return (context, last_owner_text, recorded_reply, reply_present).

    The last owner message is the last owner turn in the section. The recorded
    reply is every ARIN turn after it joined in order ("" when the section ends
    on the owner, i.e. a text that got no answer). Context is up to
    `context_turns` turns before the last owner message.
    """
    last_owner = None
    for i in range(len(turns) - 1, -1, -1):
        if turns[i]["role"] == "owner":
            last_owner = i
            break
    if last_owner is None:
        return [], "", "", False
    after = [t["content"] for t in turns[last_owner + 1 :] if t["role"] == "arin"]
    before = turns[:last_owner]
    if context_turns >= 0:
        before = before[-context_turns:] if context_turns else []
    return before, turns[last_owner]["content"], "\n".join(after), bool(after)


def build_case(
    *,
    case_id: str,
    suite: str,
    category: str,
    box: str,
    redacted: object,
    session_index: str,
    counts: dict[str, int],
    context_turns: int = DEFAULT_CONTEXT_TURNS,
    source: str = "",
) -> dict[str, object]:
    """Build a case from ALREADY-REDACTED session data (never call with raw input)."""
    turns, skipped = _turns(redacted)
    legacy_owner = redacted.get("owner_text") if isinstance(redacted, dict) else None
    if turns:
        context, owner_text, reply, reply_present = split_turns(turns, context_turns)
    else:
        context, owner_text, reply, reply_present = [], str(legacy_owner or ""), "", False
    if isinstance(redacted, dict) and not reply and isinstance(redacted.get("assistant_text"), str):
        reply = redacted["assistant_text"]
        reply_present = bool(reply.strip())

    context_text = "\n".join(f"{t['role']}: {t['content']}" for t in context)
    return {
        "id": case_id,
        "suite": suite,
        "category": category,
        "box": box,
        "synthetic": False,
        "draft_expected": None,  # set by the case labeller (Jerry), not derived from content
        "input": {
            "channel": "sms",
            "owner_text": str(owner_text),
            "context_turns": context,
            "context_available": context_text,
        },
        "fixture": {
            "assistant_text": str(reply),
            "tool_calls": [],  # top-level session tool_calls are dropped (Vault T1), counted in export_meta
        },
        "expect": redacted.get("expect") if isinstance(redacted, dict) and isinstance(redacted.get("expect"), dict) else {},
        "export_meta": {
            "session_index": session_index,
            "redaction_version": REDACTION_VERSION,
            "redaction_counts": counts,
            "context_turns_kept": len(context),
            "context_turn_limit": context_turns,
            "turns_skipped_non_text": skipped,
            "tool_calls_dropped": len(redacted.get("tool_calls") or []) if isinstance(redacted, dict) and isinstance(redacted.get("tool_calls"), list) else 0,
            "recorded_reply_present": reply_present,
            "source": source,
            "ok": True,
        },
    }


def case_text_blob(case: dict[str, object]) -> str:
    """Every string a case keeps (for the residue re-scan before writing)."""
    inp = case.get("input") or {}
    fx = case.get("fixture") or {}
    parts = [str(inp.get("owner_text") or ""), str(fx.get("assistant_text") or "")]
    parts += [t["content"] for t in inp.get("context_turns") or []]
    return "\n".join(p for p in parts if p)


def structure_signature(obj: object) -> object:
    """Shape of a session with all text removed: dict keys, list lengths, value types and role
    values (role, not text). Redaction may change text only, so this must be identical before and after."""
    if isinstance(obj, dict):
        return {
            "d": [
                (k, v if is_structural_value(k, v) or (isinstance(k, str) and k.strip().lower() == "role") else structure_signature(v))
                for k, v in obj.items()
            ]
        }
    if isinstance(obj, list):
        return {"l": [structure_signature(x) for x in obj]}
    return "scalar"  # text and numbers may be redacted (a sensitive-key value becomes a placeholder)


def empty_case_parts(case: dict[str, object]) -> list[str]:
    """Which required parts of a case are empty: 'owner' (last owner message) and/or 'reply' (ARIN reply)."""
    inp = case.get("input") or {}
    fx = case.get("fixture") or {}
    missing = []
    if not str(inp.get("owner_text") or "").strip():
        missing.append("owner")
    if not str(fx.get("assistant_text") or "").strip():
        missing.append("reply")
    return missing


def verify_cases(path: Path) -> dict[str, object]:
    """Counts and ids only: cases in an exported JSONL with an empty owner message or ARIN reply."""
    total = 0
    owner_ids: list[str] = []
    reply_ids: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for n, line in enumerate(handle, 1):
            if not line.strip():
                continue
            total += 1
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                owner_ids.append(f"line{n}")
                reply_ids.append(f"line{n}")
                continue
            cid = str(case.get("id") or f"line{n}") if isinstance(case, dict) else f"line{n}"
            parts = empty_case_parts(case) if isinstance(case, dict) else ["owner", "reply"]
            if "owner" in parts:
                owner_ids.append(cid)
            if "reply" in parts:
                reply_ids.append(cid)
    return {"cases": total, "empty_owner": len(owner_ids), "empty_reply": len(reply_ids),
            "empty_owner_ids": owner_ids, "empty_reply_ids": reply_ids}


ALLOWED_SOURCES = frozenset({"telnyx_sms", "cli", "api_server"})  # David's text, CLI, API (never cron)


FIXTURE_ROOTS = (ROOT / "fixtures", ROOT.parent.parent / "tests" / "fixtures")


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    rp = path.resolve()
    return any(rp == r.resolve() or r.resolve() in rp.parents for r in roots)


def _loose_targets(paths: list[tuple[Path, int]]) -> list[Path]:
    return [p for p, want in paths if p.exists() and loose_mode(p, want)]


def apply_name_map(obj: object, name_map: dict[str, str]) -> object:
    """Second pass: replace every name detected anywhere in the session in EVERY string.

    The first pass only replaces a name where a pattern fires (e.g. "text Dana"); the same
    name later in a reply or context turn ("Why: Dana is waiting") would otherwise survive.
    """
    if not name_map:
        return obj
    names = sorted(name_map, key=len, reverse=True)
    pat = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)

    def sub(text: str) -> str:
        return pat.sub(lambda m: name_map[m.group(1).lower()], text)

    if isinstance(obj, str):
        return sub(obj)
    if isinstance(obj, list):
        return [apply_name_map(x, name_map) for x in obj]
    if isinstance(obj, dict):
        # Keys and role values are structure, never text (Vault, Oct 19).
        return {k: (v if is_structural_value(k, v) else apply_name_map(v, name_map)) for k, v in obj.items()}
    return obj


def loose_mode(path: Path, want: int) -> bool:
    """True when path grants more than `want` (setgid/sticky bits ignored)."""
    mode = path.stat().st_mode & 0o777
    return bool(mode & ~want)


def check_perms(root: Path) -> list[str]:
    """Paths under root looser than 0600 (files) / 0700 (dirs). Paths only, no content."""
    bad: list[str] = []
    if loose_mode(root, 0o700):
        bad.append(str(root))
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            if loose_mode(Path(dirpath) / d, 0o700):
                bad.append(str(Path(dirpath) / d))
        for f in filenames:
            if loose_mode(Path(dirpath) / f, 0o600):
                bad.append(str(Path(dirpath) / f))
    return bad


def summarize(path: Path) -> list[dict[str, object]]:
    """Ids and counts only for an exported JSONL (never text)."""
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            c = json.loads(line)
            meta = c.get("export_meta") or {}
            rows.append({
                "id": c.get("id"),
                "category": c.get("category"),
                "source": meta.get("source"),
                "context_turns_kept": meta.get("context_turns_kept"),
                "recorded_reply_present": meta.get("recorded_reply_present"),
                "redaction_counts": meta.get("redaction_counts"),
            })
    return rows


def inside_git_worktree(path: Path) -> bool:
    p = path.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Export redacted session → eval case JSONL (no stdout payload).")
    parser.add_argument("--session", type=Path, help="Session JSON or transcript .txt on the box")
    parser.add_argument(
        "--source",
        help="Session source from state.db metadata: telnyx_sms | cli | api_server (required for real exports; anything else, e.g. cron, is excluded)",
    )
    parser.add_argument("--check-perms", type=Path, help="Exit 1 if any file under DIR is looser than 0600 or dir looser than 0700 (paths only)")
    parser.add_argument("--summarize", type=Path, help="Print ids and counts only for an exported JSONL")
    parser.add_argument(
        "--verify-cases",
        type=Path,
        help="Exit 1 if any case in an exported JSONL has an empty owner message or ARIN reply (counts and ids only)",
    )
    parser.add_argument("--id", help="Case id, e.g. mz-021 (required when appending JSONL)")
    parser.add_argument("--suite", choices=["regression", "capability"], default="regression")
    parser.add_argument(
        "--category",
        default="unlabeled",
        help="Label only, never a selection filter (default unlabeled; the case labeller sets it later)",
    )
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
    parser.add_argument("--owner-name", default="", help="Owner first name kept during name redaction (the only name ever kept)")
    parser.add_argument(
        "--context-turns",
        type=int,
        default=DEFAULT_CONTEXT_TURNS,
        help="Owner/ARIN turns kept before the last owner message (default 10; 0 = none)",
    )
    parser.add_argument(
        "--fixture-check",
        action="store_true",
        help="CI leak-check on repo fixtures only: waives --known-names when --out is used; perms, git and source checks still apply",
    )
    args = parser.parse_args()

    if args.check_perms is not None:
        bad = check_perms(args.check_perms)
        print(json.dumps({"loose_paths": len(bad), "paths": bad}))
        return EXIT_BLOCKED if bad else EXIT_OK
    if args.verify_cases is not None:
        report = verify_cases(args.verify_cases)
        print(json.dumps(report))
        return EXIT_BLOCKED if (report["empty_owner"] or report["empty_reply"]) else EXIT_OK
    if args.summarize is not None:
        rows = summarize(args.summarize)
        print(json.dumps({"cases": len(rows), "rows": rows}))
        return EXIT_OK
    if args.session is None:
        print("export_blocked: session_required", file=sys.stderr)
        return EXIT_BLOCKED

    append_jsonl = args.out is not None or args.redacted_text_out is None
    if args.context_turns < 0 or args.context_turns > 50:
        print("export_blocked: bad_context_turns", file=sys.stderr)
        return EXIT_BLOCKED
    # Same gates for every output path (Vault G1): --out, --redacted-text-out, and --fixture-check.
    if args.fixture_check and not _inside(args.session, FIXTURE_ROOTS):
        print("export_blocked: fixture_check_outside_fixtures", file=sys.stderr)
        return EXIT_BLOCKED
    needs_known = args.redacted_text_out is not None or (append_jsonl and not args.fixture_check)
    if needs_known and args.known_names is None:
        print("export_blocked: known_names_required", file=sys.stderr)
        return EXIT_BLOCKED
    targets = [p for p in ((args.out if args.out is not None else (ROOT / "cases-export.local.jsonl")) if append_jsonl else None,
                           args.redacted_text_out, args.manifest) if p is not None]
    if any(inside_git_worktree(t.parent) for t in targets):
        print("export_blocked: out_inside_git_worktree", file=sys.stderr)
        return EXIT_BLOCKED
    if not args.source:
        print("export_blocked: source_required", file=sys.stderr)
        return EXIT_BLOCKED
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

    src = str(args.source or raw.get("source") or "").strip().lower()
    if raw.get("source") and args.source and str(raw.get("source")).strip().lower() != src:
        log_excluded("source_mismatch")
        return EXIT_EXCLUDED
    if src and src not in ALLOWED_SOURCES:
        log_excluded("automated_or_other_source")
        return EXIT_EXCLUDED
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

    redacted = apply_name_map(redacted, ctx._name_map)
    if structure_signature(redacted) != structure_signature(raw):
        # Keys, nesting and role values must come through redaction unchanged (Vault, Oct 19).
        print("export_blocked: structure_changed", file=sys.stderr)
        return EXIT_BLOCKED
    blob = redacted_transcript(redacted)
    # Scan every string the redacted session holds (owner_text alone is not enough
    # now that cases keep context turns and the recorded reply).
    scan_blob = "\n".join(p for p in (blob, collect_session_text(redacted)) if p)
    safety = post_export_safety_flags(scan_blob)
    if safety:
        log_excluded(",".join(safety))
        return EXIT_EXCLUDED
    residue2 = scan_residue_secondary(scan_blob)
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
    # Permission pre-check on every path this run writes (outputs, their dirs, the manifest
    # and its manifests/ dir), BEFORE anything is written: exit 1 means no output (Vault P1/P2).
    planned: list[tuple[Path, int]] = [(manifest_path, 0o600), (manifest_path.parent, 0o700)]
    if append_jsonl:
        planned += [(dest, 0o600), (dest.parent, 0o700)]
    if args.redacted_text_out:
        planned += [(args.redacted_text_out, 0o600), (args.redacted_text_out.parent, 0o700)]
    pre = _loose_targets(planned)
    if pre:
        print(f"export_blocked: loose_permissions paths={len(pre)}", file=sys.stderr)
        return EXIT_BLOCKED
    secure_mkdir(scratch_parent)
    tmp_base = Path(tempfile.mkdtemp(prefix="mz-export-", dir=scratch_parent))
    try:
        os.chmod(tmp_base, 0o700)
        if args.redacted_text_out:
            secure_write_text(args.redacted_text_out, transcript + ("\n" if not transcript.endswith("\n") else ""))
            post_t = _loose_targets([(args.redacted_text_out, 0o600), (args.redacted_text_out.parent, 0o700)])
            if post_t:
                print(f"export_blocked: loose_permissions_after_write paths={len(post_t)}", file=sys.stderr)
                return EXIT_BLOCKED
        if append_jsonl:
            session_index = derive_session_index(args.id or "mz", args.session_index)
            case = build_case(
                case_id=args.id or "mz",
                suite=args.suite,
                category=args.category or "unlabeled",
                box=args.box,
                redacted=redacted,
                session_index=session_index,
                counts=dict(ctx.class_counts),
                context_turns=args.context_turns,
                source=src,
            )
            empty = empty_case_parts(case)
            if empty:
                # A case without the owner message or ARIN's reply is useless and usually means the
                # redaction ate the structure (Keel void run 1, Oct 19). Fail, never write it.
                print(f"export_blocked: empty_case id={case['id']} parts={','.join(empty)}", file=sys.stderr)
                return EXIT_BLOCKED
            kept = case_text_blob(case)
            residue3 = [r for r in dict.fromkeys(scan_residue_secondary(kept)) if r not in ("phone", "name")]
            if residue3 or post_export_safety_flags(kept):
                log_counts(ctx.class_counts)
                print(f"export_blocked: residue={','.join(residue3) or 'safety_flag'}", file=sys.stderr)
                return EXIT_BLOCKED
            line = json.dumps(case, ensure_ascii=False) + "\n"
            secure_mkdir(dest.parent)
            pre = [p for p, want in ((dest.parent, 0o700), (dest, 0o600)) if p.exists() and loose_mode(p, want)]
            if pre:
                print(f"export_blocked: loose_permissions paths={len(pre)}", file=sys.stderr)
                return EXIT_BLOCKED
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            fd = os.open(dest, flags, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line)
            write_manifest(manifest_path, ctx.class_counts)
            post = _loose_targets([(dest, 0o600), (manifest_path, 0o600), (dest.parent, 0o700), (manifest_path.parent, 0o700)])
            if post:
                print(f"export_blocked: loose_permissions_after_write paths={len(post)}", file=sys.stderr)
                return EXIT_BLOCKED
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
