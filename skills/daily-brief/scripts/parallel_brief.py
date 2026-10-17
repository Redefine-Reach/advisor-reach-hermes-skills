#!/usr/bin/env python3
"""Four-item morning brief as parallel helpers (RED-629).

The parent runs ``run``. It starts one helper process per brief slot, at most
four at once, and merges their parts in a fixed order. Each helper appends a
start line and an end line to the box log so overlap is visible. ``status``
answers "what are you working on" from that log and the live state file.
A helper asked to send a text or an email is refused and does not call a
provider. Kanban stays off.

Stacked on the Path A Why line (PR #10): a delegated child still cannot stage
or send through ``sms-send-confirmed``. This script is not a sender either.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

DELEGATED_CHILD_ENV = "HERMES_DELEGATED_CHILD_CONTEXT"
PROVIDER_LOG_ENV = "PARALLEL_BRIEF_PROVIDER_LOG"
ORDER = ("priorities", "meetings", "commitments", "followups")
LABELS = {
    "priorities": "priorities",
    "meetings": "meetings",
    "commitments": "commitments",
    "followups": "follow-ups",
}
HEADINGS = {
    "priorities": "Priorities",
    "meetings": "Meetings",
    "commitments": "Commitments",
    "followups": "Follow-ups",
}
SEND_CHANNELS = frozenset({"sms", "email"})
_WRITE_LOCK = threading.Lock()


def wall_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "parallel-brief.json"


def load_config() -> dict:
    with config_path().open(encoding="utf-8") as handle:
        data = json.load(handle)
    kanban = data.get("kanban")
    if not isinstance(kanban, dict) or kanban.get("enabled") is not False:
        raise GateFailure("refused_kanban", "Kanban stays off")
    if data.get("max_concurrent_children") != 4:
        raise GateFailure("refused_cap", "max concurrent helpers is 4")
    if list(data.get("order") or []) != list(ORDER):
        raise GateFailure("refused_cap", "brief order is fixed")
    timeout = data.get("child_timeout_seconds")
    token_cap = data.get("token_cap")
    default_tokens = data.get("default_item_tokens")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise GateFailure("refused_cap", "per-helper timeout must be set")
    if not isinstance(token_cap, int) or token_cap <= 0:
        raise GateFailure("refused_cap", "total token cap must be set")
    if not isinstance(default_tokens, int) or default_tokens < 0:
        raise GateFailure("refused_cap", "default item tokens must be set")
    return data


class GateFailure(Exception):
    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason


def emit(payload: Mapping[str, object], code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return code


def storage_paths() -> tuple[Path, Path]:
    root = os.environ.get("PARALLEL_BRIEF_DIR", "").strip()
    if root:
        base = Path(root)
    elif os.access("/opt/data", os.W_OK):
        base = Path("/opt/data/parallel-brief")
    else:
        base = Path("/tmp/parallel-brief")
    base.mkdir(parents=True, exist_ok=True)
    log_path = Path(os.environ.get("PARALLEL_BRIEF_LOG", str(base / "helpers.jsonl")))
    state_path = Path(os.environ.get("PARALLEL_BRIEF_STATE", str(base / "state.json")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path, state_path


def append_log(path: Path, record: dict) -> None:
    line = json.dumps(record, separators=(",", ":")) + "\n"
    visible = (
        f"parallel-brief slot={record.get('slot', '-')} "
        f"event={record.get('event', '-')} ts={record.get('ts', '-')}\n"
    )
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        sys.stderr.write(visible)
        sys.stderr.flush()


def _empty_state() -> dict:
    return {"kanban": False, "helpers": {}}


def write_state(path: Path, mutate) -> dict:
    with _WRITE_LOCK:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = _empty_state()
        else:
            data = _empty_state()
        if not isinstance(data, dict):
            data = _empty_state()
        helpers = data.get("helpers")
        if not isinstance(helpers, dict):
            helpers = {}
        data = {"kanban": False, "helpers": helpers}
        mutate(data)
        data["kanban"] = False
        path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
        return data


def read_json_file(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def timeout_seconds(config: dict) -> float:
    raw = os.environ.get("PARALLEL_BRIEF_TIMEOUT_SECONDS", "").strip()
    if raw:
        return float(raw)
    return float(config["child_timeout_seconds"])


def token_cap(config: dict) -> int:
    raw = os.environ.get("PARALLEL_BRIEF_TOKEN_CAP", "").strip()
    if raw:
        return int(raw)
    return int(config["token_cap"])


def item_tokens(item: dict, default_tokens: int) -> int:
    if "tokens" not in item:
        return default_tokens
    tokens = item["tokens"]
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        raise GateFailure("refused_jobs", "tokens must be a non-negative integer")
    return tokens


def command_is_send(argv: object) -> bool:
    if not isinstance(argv, list) or not argv:
        return False
    flat = [str(part) for part in argv]
    joined = " ".join(flat)
    if "sms_send_confirmed.py" in joined:
        return True
    if "smartlead.py" in joined and any(part in {"start", "schedule"} for part in flat):
        return True
    return False


def is_send_request(item: Mapping[str, object]) -> bool:
    if str(item.get("action") or "").strip().lower() == "send":
        return True
    return command_is_send(item.get("command"))


def refuse_send(channel: str) -> dict:
    """A helper never sends. The provider log is not created."""
    chosen = channel if channel in SEND_CHANNELS else "sms"
    if os.environ.get(DELEGATED_CHILD_ENV, "").strip():
        reason = "a delegated child cannot send a text or an email"
    else:
        reason = "a helper cannot send a text or an email"
    return {
        "ok": False,
        "outcome": "refused_autonomous",
        "reason": reason,
        "provider_called": False,
        "channel": chosen,
    }


def open_helpers(events: list[dict]) -> dict[str, str]:
    """Slots with a start and no later end. Unknown slots are ignored."""
    running: dict[str, str] = {}
    for event in events:
        slot = event.get("slot")
        if slot not in ORDER:
            continue
        kind = event.get("event")
        if kind == "start" and isinstance(event.get("ts"), str):
            running[str(slot)] = str(event["ts"])
        elif kind == "end":
            running.pop(str(slot), None)
    return running


def status_text(events: list[dict]) -> str:
    running = open_helpers(events)
    if not running:
        return "Nothing is running."
    parts = [
        f"{LABELS[slot]} (started {running[slot]})"
        for slot in ORDER
        if slot in running
    ]
    return "Working on: " + "; ".join(parts) + "."


def ignored_state_helpers(state: dict, events: list[dict]) -> list[str]:
    helpers = state.get("helpers") if isinstance(state, dict) else None
    if not isinstance(helpers, dict):
        return []
    open_slots = set(open_helpers(events))
    ignored = []
    for name, row in helpers.items():
        if name not in ORDER:
            ignored.append(str(name))
            continue
        if not isinstance(row, dict):
            continue
        if row.get("status") == "running" and name not in open_slots:
            ignored.append(str(name))
    return ignored


def mark_helper(state_path: Path, slot: str, status: str, started_at: str | None) -> None:
    def mutate(data: dict) -> None:
        current = data["helpers"].get(slot)
        row = dict(current) if isinstance(current, dict) else {}
        row["status"] = status
        if started_at:
            row["started_at"] = started_at
        data["helpers"][slot] = row

    write_state(state_path, mutate)


def log_event(log_path: Path, slot: str, event: str, **extra: object) -> dict:
    record = {
        "event": event,
        "slot": slot,
        "ts": wall_ts(),
        "mono_ns": time.monotonic_ns(),
        **extra,
    }
    append_log(log_path, record)
    return record


def run_helper_work(item: dict, timeout_s: float) -> str:
    delay_ms = item.get("delay_ms", 0)
    if isinstance(delay_ms, bool) or not isinstance(delay_ms, int) or delay_ms < 0:
        raise GateFailure("refused_jobs", "delay_ms must be a non-negative integer")
    if delay_ms:
        time.sleep(delay_ms / 1000)
    command = item.get("command")
    if command is not None:
        if not isinstance(command, list) or not all(isinstance(part, str) and part for part in command):
            raise GateFailure("refused_jobs", "command must be an argv list")
        if command_is_send(command):
            raise GateFailure("refused_autonomous", "a helper cannot send a text or an email")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
        if completed.returncode != 0:
            raise GateFailure("helper_failed", completed.stderr.strip() or "helper command failed")
        text = completed.stdout.strip()
        if text:
            return text
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise GateFailure("helper_failed", "helper returned no text")


def helper_main(args: argparse.Namespace) -> int:
    log_path, state_path = storage_paths()
    slot = args.slot
    if slot not in ORDER:
        return emit({"ok": False, "outcome": "refused_jobs", "reason": "unknown brief slot"}, 2)
    item = {
        "slot": slot,
        "delay_ms": args.delay_ms,
        "text": args.text,
        "action": args.action,
        "channel": args.channel,
        "command": json.loads(args.command_json) if args.command_json else None,
    }
    started = log_event(log_path, slot, "start")
    mark_helper(state_path, slot, "running", str(started["ts"]))
    try:
        if is_send_request(item):
            refusal = refuse_send(str(args.channel or "sms"))
            log_event(log_path, slot, "end", ok=False, outcome="refused_autonomous")
            mark_helper(state_path, slot, "done", str(started["ts"]))
            refusal["slot"] = slot
            refusal["text"] = f"couldn't get {LABELS[slot]}"
            return emit(refusal, 2)
        text = run_helper_work(item, float(args.timeout_seconds))
        log_event(log_path, slot, "end", ok=True)
        mark_helper(state_path, slot, "done", str(started["ts"]))
        return emit({"ok": True, "slot": slot, "text": text, "provider_called": False}, 0)
    except subprocess.TimeoutExpired:
        log_event(log_path, slot, "end", ok=False, outcome="timeout")
        mark_helper(state_path, slot, "done", str(started["ts"]))
        return emit(
            {
                "ok": False,
                "slot": slot,
                "outcome": "timeout",
                "text": f"couldn't get {LABELS[slot]}",
                "provider_called": False,
            },
            2,
        )
    except GateFailure as failure:
        log_event(log_path, slot, "end", ok=False, outcome=failure.outcome)
        mark_helper(state_path, slot, "done", str(started["ts"]))
        return emit(
            {
                "ok": False,
                "slot": slot,
                "outcome": failure.outcome,
                "reason": failure.reason,
                "text": f"couldn't get {LABELS[slot]}",
                "provider_called": False,
            },
            2,
        )


def parse_jobs(path: str) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise GateFailure("refused_jobs", "jobs file needs an items list")
    if len(items) > 4:
        raise GateFailure("refused_over_cap", "at most 4 brief helpers")
    seen: set[str] = set()
    parsed: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise GateFailure("refused_jobs", "each item must be an object")
        slot = item.get("slot")
        if slot not in ORDER:
            raise GateFailure("refused_jobs", "unknown brief slot")
        if slot in seen:
            raise GateFailure("refused_jobs", "duplicate brief slot")
        seen.add(str(slot))
        parsed.append(item)
    return parsed


def select_items(items: list[dict], config: dict) -> tuple[list[dict], list[tuple[str, str]]]:
    cap = token_cap(config)
    default_tokens = int(config["default_item_tokens"])
    by_slot = {str(item["slot"]): item for item in items}
    chosen: list[dict] = []
    skipped: list[tuple[str, str]] = []
    running = 0
    for slot in ORDER:
        item = by_slot.get(slot)
        if item is None:
            skipped.append((slot, "missing"))
            continue
        tokens = item_tokens(item, default_tokens)
        if running + tokens > cap:
            skipped.append((slot, "token_cap"))
            continue
        running += tokens
        chosen.append(item)
    return chosen, skipped


def helper_argv(item: dict, timeout_s: float) -> list[str]:
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "helper",
        "--slot",
        str(item["slot"]),
        "--delay-ms",
        str(int(item.get("delay_ms") or 0)),
        "--timeout-seconds",
        str(timeout_s),
    ]
    if isinstance(item.get("text"), str):
        argv.extend(["--text", item["text"]])
    if item.get("action"):
        argv.extend(["--action", str(item["action"])])
    if item.get("channel"):
        argv.extend(["--channel", str(item["channel"])])
    if item.get("command") is not None:
        argv.extend(["--command-json", json.dumps(item["command"])])
    return argv


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env[DELEGATED_CHILD_ENV] = "1"
    return env


def slot_has_end(log_path: Path, slot: str, after_mono: int) -> bool:
    for event in read_events(log_path):
        if event.get("slot") == slot and event.get("event") == "end":
            mono = event.get("mono_ns")
            if isinstance(mono, int) and mono >= after_mono:
                return True
    return False


def relay_stderr(stream: object) -> None:
    if not stream:
        return
    if isinstance(stream, bytes):
        sys.stderr.write(stream.decode("utf-8", "replace"))
    else:
        sys.stderr.write(str(stream))
    sys.stderr.flush()


def spawn_helper(item: dict, timeout_s: float, log_path: Path) -> dict:
    slot = str(item["slot"])
    started = time.monotonic_ns()
    try:
        completed = subprocess.run(
            helper_argv(item, timeout_s),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=child_env(),
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        relay_stderr(expired.stderr)
        if not slot_has_end(log_path, slot, started):
            log_event(log_path, slot, "end", ok=False, outcome="timeout", source="parent")
            mark_helper(storage_paths()[1], slot, "done", None)
        return {
            "slot": slot,
            "ok": False,
            "text": f"couldn't get {LABELS[slot]}",
            "outcome": "timeout",
        }
    relay_stderr(completed.stderr)
    payload = None
    try:
        payload = json.loads(completed.stdout or "null")
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        return {
            "slot": slot,
            "ok": bool(payload.get("ok")),
            "text": payload["text"],
            "outcome": payload.get("outcome"),
        }
    return {
        "slot": slot,
        "ok": False,
        "text": f"couldn't get {LABELS[slot]}",
        "outcome": "helper_failed",
    }


def render_text(parts: list[dict]) -> str:
    lines = []
    for part in parts:
        slot = str(part["slot"])
        if part.get("ok"):
            lines.append(f"{HEADINGS[slot]}: {part['text']}")
        else:
            lines.append(f"couldn't get {LABELS[slot]}")
    return "\n".join(lines)


def finish_parts(results: dict[str, dict], skipped: list[tuple[str, str]]) -> list[dict]:
    skip_reason = {slot: reason for slot, reason in skipped}
    parts = []
    for slot in ORDER:
        if slot in results:
            row = results[slot]
            parts.append(
                {
                    "slot": slot,
                    "ok": bool(row.get("ok")),
                    "text": row.get("text") if row.get("ok") else f"couldn't get {LABELS[slot]}",
                    "outcome": row.get("outcome"),
                }
            )
            continue
        reason = skip_reason.get(slot, "missing")
        parts.append(
            {
                "slot": slot,
                "ok": False,
                "text": f"couldn't get {LABELS[slot]}",
                "outcome": reason,
            }
        )
    return parts


def run_main(args: argparse.Namespace) -> int:
    try:
        config = load_config()
        items = parse_jobs(args.jobs)
        chosen, skipped = select_items(items, config)
    except GateFailure as failure:
        return emit(
            {
                "ok": False,
                "outcome": failure.outcome,
                "reason": failure.reason,
                "kanban": False,
                "helpers_started": 0,
                "provider_called": False,
            },
            2,
        )
    except (OSError, json.JSONDecodeError) as failure:
        return emit(
            {
                "ok": False,
                "outcome": "refused_jobs",
                "reason": str(failure),
                "kanban": False,
                "helpers_started": 0,
                "provider_called": False,
            },
            2,
        )
    mode = args.mode
    if mode not in {"parallel", "sequential"}:
        return emit(
            {
                "ok": False,
                "outcome": "refused_jobs",
                "reason": "mode must be parallel or sequential",
                "kanban": False,
                "helpers_started": 0,
            },
            2,
        )
    log_path, state_path = storage_paths()

    def clear_helpers(data: dict) -> None:
        data["helpers"] = {}

    write_state(state_path, clear_helpers)
    workers = 1 if mode == "sequential" else int(config["max_concurrent_children"])
    timeout_s = timeout_seconds(config)
    started = time.monotonic_ns()
    results: dict[str, dict] = {}
    if chosen:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(spawn_helper, item, timeout_s, log_path): str(item["slot"])
                for item in chosen
            }
            for future in as_completed(futures):
                slot = futures[future]
                try:
                    results[slot] = future.result()
                except Exception as failure:
                    sys.stderr.write(
                        f"parallel-brief slot={slot} event=error ts={wall_ts()} "
                        f"reason={type(failure).__name__}\n"
                    )
                    if not any(
                        event.get("slot") == slot and event.get("event") == "end"
                        for event in read_events(log_path)
                    ):
                        log_event(log_path, slot, "end", ok=False, outcome="helper_failed", source="parent")
                    results[slot] = {
                        "slot": slot,
                        "ok": False,
                        "text": f"couldn't get {LABELS[slot]}",
                        "outcome": "helper_failed",
                    }
    for slot, reason in skipped:
        log_event(log_path, slot, "skip", reason=reason)
    parts = finish_parts(results, skipped)
    elapsed_ms = (time.monotonic_ns() - started) // 1_000_000
    return emit(
        {
            "ok": True,
            "outcome": "merged",
            "order": list(ORDER),
            "mode": mode,
            "kanban": False,
            "max_concurrent": workers,
            "token_cap": token_cap(config),
            "child_timeout_seconds": timeout_s,
            "helpers_started": len(chosen),
            "provider_called": False,
            "elapsed_ms": elapsed_ms,
            "parts": parts,
            "text": render_text(parts),
        }
    )


def status_main() -> int:
    try:
        load_config()
    except GateFailure as failure:
        return emit({"ok": False, "outcome": failure.outcome, "reason": failure.reason, "kanban": False}, 2)
    log_path, state_path = storage_paths()
    events = read_events(log_path)
    state = read_json_file(state_path, _empty_state())
    if not isinstance(state, dict):
        state = _empty_state()
    text = status_text(events)
    return emit(
        {
            "ok": True,
            "outcome": "status",
            "text": text,
            "kanban": False,
            "log_read": True,
            "state_read": True,
            "helpers": [
                {"slot": slot, "started_at": started}
                for slot, started in open_helpers(events).items()
            ],
            "ignored_state_helpers": ignored_state_helpers(state, events),
        }
    )


def send_main(args: argparse.Namespace) -> int:
    channel = str(args.channel or "").strip().lower()
    if channel not in SEND_CHANNELS:
        return emit(
            {
                "ok": False,
                "outcome": "refused_autonomous",
                "reason": "channel must be sms or email",
                "provider_called": False,
            },
            2,
        )
    return emit(refuse_send(channel), 2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parallel four-item morning brief (RED-629).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_cmd = sub.add_parser("run", help="Run the four brief helpers and merge in order.")
    run_cmd.add_argument("--jobs", required=True)
    run_cmd.add_argument("--mode", default="parallel", choices=("parallel", "sequential"))

    sub.add_parser("status", help="Answer what is working from the live state and log.")

    send_cmd = sub.add_parser("send", help="Refuse a helper send. This script never sends.")
    send_cmd.add_argument("--channel", required=True, choices=("sms", "email"))

    helper_cmd = sub.add_parser("helper", help="One brief helper. Internal.")
    helper_cmd.add_argument("--slot", required=True)
    helper_cmd.add_argument("--delay-ms", type=int, default=0)
    helper_cmd.add_argument("--timeout-seconds", type=float, default=120)
    helper_cmd.add_argument("--text", default="")
    helper_cmd.add_argument("--action", default="")
    helper_cmd.add_argument("--channel", default="")
    helper_cmd.add_argument("--command-json", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run_main(args)
    if args.cmd == "status":
        return status_main()
    if args.cmd == "send":
        return send_main(args)
    if args.cmd == "helper":
        return helper_main(args)
    return emit({"ok": False, "outcome": "refused_jobs", "reason": "unknown command"}, 2)


if __name__ == "__main__":
    sys.exit(main())
