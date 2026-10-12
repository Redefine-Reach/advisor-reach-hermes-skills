#!/usr/bin/env python3
"""Learning loop for one box: preferences, draft signals, and client skills.

Every save calls the box do-not-keep gate (arin_donotkeep.on_pre_tool_call on
a memory add) before anything is written. The one-line confirmation is
returned only after a read-back of that write. This script does not ask for
approval and does not turn background review on.

The gate module is /opt/box/arin_donotkeep.py on a box image that has it.
A missing module blocks the save. LEARNING_LOOP_TEST=1 is the only switch
that loads LEARNING_LOOP_JUDGE, and only for unit tests.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

CONFIRM_SAVED = "Saved. I'll use that next time."
CONFIRM_FORGOT = "Forgot that."
COULD_NOT_SAVE = "I couldn't save that right now."
ONE_CLIENT = "One preference is for the owner or for one named client."
WHICH_ONE = "Which one should I forget? Ask me to list them."
NOT_FOUND = "That isn't one I have saved."
GATE_PATH = "/opt/box/arin_donotkeep.py"
KIND_MAX = 40
TEXT_MAX = 400
NOTE_MAX = 200
WHEN_MAX = 200
STEP_MAX = 180
STEP_COUNT = 6
LABEL_MAX = 80


def emit(obj, code=0):
    confirm = obj.get("confirm")
    if confirm is not None and ("\n" in confirm or "\r" in confirm):
        obj = dict(obj)
        obj["confirm"] = None
        obj["ok"] = False
        obj["saved"] = False
        obj["say"] = COULD_NOT_SAVE
    print(json.dumps(obj, ensure_ascii=True, sort_keys=True))
    raise SystemExit(code)


def base_result(**extra):
    result = {
        "ok": False,
        "saved": False,
        "confirm": None,
        "say": None,
        "gate": None,
        "id": None,
        "items": [],
    }
    result.update(extra)
    return result


def resolve_home():
    raw = os.environ.get("HERMES_HOME") or "/opt/data"
    path = Path(raw).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise RuntimeError("home")
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_path(home):
    return home / "learning" / "loop.json"


def empty_store():
    return {"version": 1, "preferences": [], "pending_corrections": [], "signals": []}


def load_store(home):
    path = store_path(home)
    if not path.is_file():
        return empty_store()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RuntimeError("store")
    for key in ("preferences", "pending_corrections", "signals"):
        if not isinstance(data.get(key), list):
            raise RuntimeError("store")
    return data


def write_store(home, data):
    path = store_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name("loop.json.tmp")
    tmp.write_text(raw, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return path


def restore_store(path, previous):
    if previous is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(previous)
    os.chmod(path, 0o600)


def commit_store(home, mutate, check):
    path = store_path(home)
    previous = path.read_bytes() if path.is_file() else None
    data = load_store(home)
    mutate(data)
    try:
        write_store(home, data)
        loaded = load_store(home)
        if not check(loaded):
            raise RuntimeError("readback")
    except Exception:
        restore_store(path, previous)
        return None
    return loaded


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id():
    return uuid.uuid4().hex[:12]


def plain(value, limit):
    text = " ".join(str(value or "").split())
    if not text or len(text) > limit:
        return None
    if any(ch in text for ch in ":#`"):
        return None
    return text


def kind_of(value, text):
    chosen = (value or "").strip().lower()
    if not chosen and "daily brief" in str(text or "").casefold():
        chosen = "daily-brief"
    if not chosen:
        chosen = "general"
    if not chosen or len(chosen) > KIND_MAX:
        return None
    if not all(ch.islower() or ch.isdigit() or ch == "-" for ch in chosen):
        return None
    if chosen.startswith("-") or chosen.endswith("-") or "--" in chosen:
        return None
    return chosen


def slug(value):
    chars = []
    for ch in str(value or "").casefold():
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_"}:
            chars.append("-")
    text = "".join(chars)
    while "--" in text:
        text = text.replace("--", "-")
    text = text.strip("-")
    if not text or len(text) > KIND_MAX:
        return None
    return text


def norm(text):
    return " ".join(text.casefold().split())


def scope_of(args):
    scope = getattr(args, "scope", None)
    client_raw = getattr(args, "client", None)
    if scope == "owner":
        if client_raw:
            return None, ONE_CLIENT
        return ("owner", None), None
    if scope == "client":
        client = plain(client_raw, LABEL_MAX)
        if not client:
            return None, ONE_CLIENT
        return ("client", client), None
    return None, ONE_CLIENT


def load_gate():
    raw = os.environ.get("ARIN_DONOTKEEP_PY") or GATE_PATH
    path = Path(raw)
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("arin_donotkeep_gate", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "on_pre_tool_call", None)):
        return None
    return module


def load_judge():
    if os.environ.get("LEARNING_LOOP_TEST") != "1":
        return None
    raw = os.environ.get("LEARNING_LOOP_JUDGE") or ""
    path = Path(raw)
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("learning_loop_judge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("judge")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    judge = getattr(module, "judge", None)
    if not callable(judge):
        raise RuntimeError("judge")
    return judge


def admit(home, text):
    """Return (gate kind, say). say is None only when the save may proceed."""
    try:
        module = load_gate()
    except Exception:
        return "error", COULD_NOT_SAVE
    if module is None:
        return "missing", COULD_NOT_SAVE
    env = dict(os.environ)
    env["BOX_DONOTKEEP"] = "1"
    env["HERMES_HOME"] = str(home)
    kwargs = {"env": env, "home": home}
    try:
        judge = load_judge()
    except Exception:
        return "error", COULD_NOT_SAVE
    if judge is not None:
        kwargs["model"] = judge
    try:
        gate = module.on_pre_tool_call(
            "memory",
            {"action": "add", "content": text},
            **kwargs,
        )
    except Exception:
        return "error", COULD_NOT_SAVE
    message = getattr(gate, "message", None)
    kind = str(getattr(gate, "kind", "") or "error")
    if message:
        return kind, str(message)
    return "allow", None


def blocked(kind, say):
    emit(base_result(ok=False, saved=False, confirm=None, say=say, gate=kind))


def same_pref(row, pref):
    keys = ("id", "scope", "client", "kind", "text", "source", "created_at")
    return isinstance(row, dict) and all(row.get(key) == pref.get(key) for key in keys)


def find_pref(data, pref_id):
    return [row for row in data["preferences"] if isinstance(row, dict) and row.get("id") == pref_id]


def save_pref(home, pref, text):
    kind, say = admit(home, text)
    if say:
        blocked(kind, say)

    def mutate(data):
        data["preferences"].append(pref)

    def check(data):
        found = find_pref(data, pref["id"])
        return found == [pref] or (len(found) == 1 and same_pref(found[0], pref))

    loaded = commit_store(home, mutate, check)
    if loaded is None:
        blocked("error", COULD_NOT_SAVE)
    emit(base_result(
        ok=True,
        saved=True,
        confirm=CONFIRM_SAVED,
        say=None,
        gate="allow",
        id=pref["id"],
        items=[pref],
    ))


def cmd_save_explicit(home, args):
    parsed, say = scope_of(args)
    if say:
        blocked("error", say)
    scope, client = parsed
    text = plain(args.text, TEXT_MAX)
    if not text:
        blocked("error", COULD_NOT_SAVE)
    kind = kind_of(args.kind, text)
    if not kind:
        blocked("error", COULD_NOT_SAVE)
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    for row in data["preferences"]:
        if (
            isinstance(row, dict)
            and row.get("scope") == scope
            and row.get("client") == client
            and row.get("kind") == kind
            and row.get("text") == text
        ):
            emit(base_result(ok=True, saved=False, confirm=None, gate="allow", id=row.get("id"), items=[row]))
    pref = {
        "id": new_id(),
        "scope": scope,
        "client": client,
        "kind": kind,
        "text": text,
        "source": "explicit",
        "created_at": now_stamp(),
    }
    save_pref(home, pref, text)


def cmd_note_correction(home, args):
    parsed, say = scope_of(args)
    if say:
        blocked("error", say)
    scope, client = parsed
    text = plain(args.text, TEXT_MAX)
    if not text:
        blocked("error", COULD_NOT_SAVE)
    kind = kind_of(args.kind, text)
    if not kind:
        blocked("error", COULD_NOT_SAVE)
    gate_kind, gate_say = admit(home, text)
    if gate_say:
        blocked(gate_kind, gate_say)
    key = norm(text)
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    for row in data["preferences"]:
        if (
            isinstance(row, dict)
            and row.get("scope") == scope
            and row.get("client") == client
            and row.get("kind") == kind
            and norm(str(row.get("text") or "")) == key
        ):
            emit(base_result(ok=True, saved=False, confirm=None, gate="allow", id=row.get("id"), items=[row]))
    pending = None
    for row in data["pending_corrections"]:
        if (
            isinstance(row, dict)
            and row.get("scope") == scope
            and row.get("client") == client
            and row.get("kind") == kind
            and row.get("norm") == key
        ):
            pending = row
            break
    if pending is None:
        row = {
            "scope": scope,
            "client": client,
            "kind": kind,
            "norm": key,
            "text": text,
            "count": 1,
        }

        def mutate(store):
            store["pending_corrections"].append(row)

        def check(store):
            return any(
                item.get("scope") == scope
                and item.get("client") == client
                and item.get("kind") == kind
                and item.get("norm") == key
                and item.get("count") == 1
                for item in store["pending_corrections"]
                if isinstance(item, dict)
            )

        if commit_store(home, mutate, check) is None:
            blocked("error", COULD_NOT_SAVE)
        emit(base_result(ok=True, saved=False, confirm=None, gate="allow", items=[]))
    pref = {
        "id": new_id(),
        "scope": scope,
        "client": client,
        "kind": kind,
        "text": text,
        "source": "repeated-correction",
        "created_at": now_stamp(),
    }

    def promote(store):
        store["pending_corrections"] = [
            item for item in store["pending_corrections"]
            if not (
                isinstance(item, dict)
                and item.get("scope") == scope
                and item.get("client") == client
                and item.get("kind") == kind
                and item.get("norm") == key
            )
        ]
        store["preferences"].append(pref)

    def promoted(store):
        still = [
            item for item in store["pending_corrections"]
            if isinstance(item, dict)
            and item.get("scope") == scope
            and item.get("client") == client
            and item.get("kind") == kind
            and item.get("norm") == key
        ]
        found = find_pref(store, pref["id"])
        return not still and len(found) == 1 and same_pref(found[0], pref)

    if commit_store(home, promote, promoted) is None:
        blocked("error", COULD_NOT_SAVE)
    emit(base_result(
        ok=True,
        saved=True,
        confirm=CONFIRM_SAVED,
        gate="allow",
        id=pref["id"],
        items=[pref],
    ))


def visible_pref(row, scope, client, kind):
    if not isinstance(row, dict):
        return False
    if scope and row.get("scope") != scope:
        return False
    if scope == "client" and row.get("client") != client:
        return False
    if scope == "owner" and row.get("client") is not None:
        return False
    if kind and row.get("kind") != kind:
        return False
    return True


def skill_dirs(home, client):
    root = (home / "skills").resolve()
    if not root.is_dir():
        return []
    want = slug(client)
    if not want:
        return []
    prefix = f"c-{want}--"
    found = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not path.name.startswith(prefix):
            continue
        skill = path / "SKILL.md"
        if not skill.is_file():
            continue
        resolved = path.resolve()
        if resolved.parent != root:
            continue
        text = skill.read_text(encoding="utf-8")
        if f"Client: {client}\n" not in text:
            continue
        procedure = path.name[len(prefix):]
        when = ""
        for line in text.splitlines():
            if line.startswith("When: "):
                when = line[len("When: "):]
                break
        found.append({"procedure": procedure, "dir": path.name, "when": when, "client": client})
    return found


def cmd_list(home, args):
    parsed, say = scope_of(args)
    if say:
        blocked("error", say)
    scope, client = parsed
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    items = [row for row in data["preferences"] if visible_pref(row, scope, client, args.kind)]
    procedures = skill_dirs(home, client) if scope == "client" else []
    emit(base_result(
        ok=True,
        saved=False,
        confirm=None,
        gate=None,
        items=items,
        procedures=procedures,
    ))


def cmd_apply(home, args):
    kind = kind_of(args.kind, "")
    if args.kind and not kind:
        blocked("error", COULD_NOT_SAVE)
    client = None
    if args.client:
        client = plain(args.client, LABEL_MAX)
        if not client:
            blocked("error", ONE_CLIENT)
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    items = []
    for row in data["preferences"]:
        if not isinstance(row, dict):
            continue
        if kind and row.get("kind") != kind:
            continue
        if row.get("scope") == "owner":
            items.append(row)
            continue
        if client and row.get("scope") == "client" and row.get("client") == client:
            items.append(row)
    emit(base_result(ok=True, saved=False, confirm=None, items=items, procedures=skill_dirs(home, client) if client else []))


def matching_forget(data, args):
    rows = [row for row in data["preferences"] if isinstance(row, dict)]
    if args.id:
        return [row for row in rows if row.get("id") == args.id]
    needle = plain(args.text, TEXT_MAX)
    if not needle:
        return []
    return [row for row in rows if needle == row.get("text") or needle in str(row.get("text") or "")]


def cmd_forget(home, args):
    if args.procedure:
        client = plain(args.client, LABEL_MAX)
        procedure = slug(args.procedure)
        if not client or not procedure:
            blocked("error", ONE_CLIENT)
        if args.id or args.text:
            blocked("error", WHICH_ONE)
        root = (home / "skills").resolve()
        dirname = f"c-{slug(client)}--{procedure}"
        dest = (root / dirname).resolve()
        if dest.parent != root or not dest.is_dir():
            blocked("error", NOT_FOUND)
        skill = dest / "SKILL.md"
        if not skill.is_file():
            blocked("error", NOT_FOUND)
        body = skill.read_text(encoding="utf-8")
        if f"Client: {client}\n" not in body or f"Procedure: {procedure}\n" not in body:
            blocked("error", NOT_FOUND)
        extras = [path for path in dest.iterdir() if path.name != "SKILL.md"]
        if extras:
            blocked("error", COULD_NOT_SAVE)
        shutil.rmtree(dest)
        if dest.exists():
            blocked("error", COULD_NOT_SAVE)
        emit(base_result(ok=True, saved=True, confirm=CONFIRM_FORGOT, id=dirname))
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    matches = matching_forget(data, args)
    if matches is None:
        blocked("error", WHICH_ONE)
    if not matches:
        blocked("error", NOT_FOUND)
    if len(matches) != 1:
        blocked("error", WHICH_ONE)
    target = matches[0]
    pref_id = target.get("id")

    def mutate(store):
        store["preferences"] = [
            row for row in store["preferences"]
            if not (isinstance(row, dict) and row.get("id") == pref_id)
        ]

    def check(store):
        ids = [row.get("id") for row in store["preferences"] if isinstance(row, dict)]
        expected = [
            row.get("id") for row in data["preferences"]
            if isinstance(row, dict) and row.get("id") != pref_id
        ]
        return pref_id not in ids and ids == expected

    if commit_store(home, mutate, check) is None:
        blocked("error", COULD_NOT_SAVE)
    emit(base_result(ok=True, saved=True, confirm=CONFIRM_FORGOT, id=pref_id))


def cmd_record(home, args):
    action = args.action
    if action not in {"edit", "send", "skip"}:
        blocked("error", COULD_NOT_SAVE)
    kind = kind_of(args.kind, "")
    if not kind or kind == "general":
        blocked("error", COULD_NOT_SAVE)
    note = args.note
    if action == "edit":
        note = plain(note, NOTE_MAX)
        if not note:
            blocked("error", COULD_NOT_SAVE)
        candidate = note
        signal = "style"
    else:
        if note:
            blocked("error", COULD_NOT_SAVE)
        note = ""
        candidate = f"draft signal {kind} {action}"
        signal = "acted-on"
    gate_kind, say = admit(home, candidate)
    if say:
        blocked(gate_kind, say)
    item = {
        "id": new_id(),
        "draft_kind": kind,
        "action": action,
        "signal": signal,
        "note": note,
        "created_at": now_stamp(),
    }

    def mutate(store):
        store["signals"].append(item)

    def check(store):
        found = [
            row for row in store["signals"]
            if isinstance(row, dict) and row.get("id") == item["id"]
        ]
        return found == [item]

    if commit_store(home, mutate, check) is None:
        blocked("error", COULD_NOT_SAVE)
    emit(base_result(ok=True, saved=True, confirm=None, gate="allow", id=item["id"], items=[item]))


def signals_for(data, kind):
    rows = []
    for row in data["signals"]:
        if isinstance(row, dict) and (not kind or row.get("draft_kind") == kind):
            rows.append(row)
    return rows


def cmd_show(home, args):
    kind = None
    if args.kind:
        kind = kind_of(args.kind, "")
        if not kind:
            blocked("error", COULD_NOT_SAVE)
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    items = signals_for(data, kind)
    emit(base_result(ok=True, items=items))


def cmd_next(home, args):
    kind = kind_of(args.kind, "")
    if not kind or kind == "general":
        blocked("error", COULD_NOT_SAVE)
    try:
        data = load_store(home)
    except Exception:
        blocked("error", COULD_NOT_SAVE)
    items = signals_for(data, kind)
    style = [row.get("note") for row in items if row.get("signal") == "style" and row.get("note")]
    emit(base_result(ok=True, items=items, style=style, draft_kind=kind))


def render_skill(client, procedure, when, steps):
    dirname = f"c-{slug(client)}--{slug(procedure)}"
    description = f"{client} only: {procedure}. {when}"
    if len(description) > 180:
        description = description[:177] + "..."
    lines = [
        "---",
        f"name: {dirname}",
        "description: " + json.dumps(description, ensure_ascii=True),
        "---",
        "",
        f"# {procedure}",
        "",
        f"Client: {client}",
        f"Procedure: {procedure}",
        f"When: {when}",
        "",
        "This procedure is only for this client. It does not apply to the owner or to any other client.",
        "The learning-loop script wrote this file. Do not edit it by hand.",
        "",
        "## Steps",
        "",
    ]
    for index, step in enumerate(steps, 1):
        lines.append(f"{index}. {step}")
    lines.append("")
    return dirname, "\n".join(lines)


def cmd_write_client_skill(home, args):
    client = plain(args.client, LABEL_MAX)
    procedure = slug(args.name)
    when = plain(args.when, WHEN_MAX)
    steps = list(args.step or [])
    if not client or not procedure or not when or not steps or len(steps) > STEP_COUNT:
        blocked("error", COULD_NOT_SAVE)
    cleaned = []
    for step in steps:
        text = plain(step, STEP_MAX)
        if not text:
            blocked("error", COULD_NOT_SAVE)
        cleaned.append(text)
    dirname, body = render_skill(client, procedure, when, cleaned)
    gate_kind, say = admit(home, body)
    if say:
        blocked(gate_kind, say)
    root = (home / "skills").resolve()
    dest = (root / dirname).resolve()
    if dest.parent != root or not dirname.startswith("c-") or "--" not in dirname:
        blocked("error", COULD_NOT_SAVE)
    dest.mkdir(parents=True, exist_ok=True)
    skill = dest / "SKILL.md"
    previous = skill.read_bytes() if skill.is_file() else None
    tmp = dest / "SKILL.md.tmp"
    try:
        tmp.write_text(body, encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, skill)
        os.chmod(skill, 0o644)
        read = skill.read_text(encoding="utf-8")
        if read != body or f"Client: {client}\n" not in read:
            raise RuntimeError("readback")
    except Exception:
        if tmp.exists():
            tmp.unlink()
        if previous is None:
            if skill.exists():
                skill.unlink()
            if dest.is_dir() and not any(dest.iterdir()):
                dest.rmdir()
        else:
            skill.write_bytes(previous)
        blocked("error", COULD_NOT_SAVE)
    emit(base_result(ok=True, saved=True, confirm=CONFIRM_SAVED, gate="allow", id=dirname))


def review_state(path):
    if not path.is_file():
        return "unset"
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        if key.strip() != "background_review":
            continue
        token = value.strip().strip("'\"").lower()
        if token in {"true", "yes", "on", "1"}:
            return "on"
        if token in {"false", "no", "off", "0"}:
            return "off"
    return "unset"


def cmd_status(home, _args):
    path = home / "config.yaml"
    before = path.read_bytes() if path.is_file() else None
    state = review_state(path)
    after = path.read_bytes() if path.is_file() else None
    if before != after:
        blocked("error", COULD_NOT_SAVE)
    emit(base_result(ok=True, background_review=state))


def build_parser():
    parser = argparse.ArgumentParser(prog="learning_loop.py")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_scope(command):
        command.add_argument("--scope", required=True, choices=("owner", "client"))
        command.add_argument("--client")
        command.add_argument("--kind")
        command.add_argument("--text", required=True)

    save = sub.add_parser("save-explicit")
    with_scope(save)
    save.set_defaults(func=cmd_save_explicit)

    note = sub.add_parser("note-correction")
    with_scope(note)
    note.set_defaults(func=cmd_note_correction)

    listed = sub.add_parser("list")
    listed.add_argument("--scope", required=True, choices=("owner", "client"))
    listed.add_argument("--client")
    listed.add_argument("--kind")
    listed.set_defaults(func=cmd_list)

    apply = sub.add_parser("apply")
    apply.add_argument("--kind")
    apply.add_argument("--client")
    apply.set_defaults(func=cmd_apply)

    forget = sub.add_parser("forget")
    forget.add_argument("--id")
    forget.add_argument("--text")
    forget.add_argument("--client")
    forget.add_argument("--procedure")
    forget.set_defaults(func=cmd_forget)

    record = sub.add_parser("record")
    record.add_argument("--kind", required=True)
    record.add_argument("--action", required=True, choices=("edit", "send", "skip"))
    record.add_argument("--note")
    record.set_defaults(func=cmd_record)

    show = sub.add_parser("show")
    show.add_argument("--kind")
    show.set_defaults(func=cmd_show)

    nxt = sub.add_parser("next")
    nxt.add_argument("--kind", required=True)
    nxt.set_defaults(func=cmd_next)

    skill = sub.add_parser("write-client-skill")
    skill.add_argument("--client", required=True)
    skill.add_argument("--name", required=True)
    skill.add_argument("--when", required=True)
    skill.add_argument("--step", action="append", required=True)
    skill.set_defaults(func=cmd_write_client_skill)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        home = resolve_home()
        args.func(home, args)
    except SystemExit:
        raise
    except Exception:
        emit(base_result(ok=False, say=COULD_NOT_SAVE, gate="error"))


if __name__ == "__main__":
    main(sys.argv[1:])
