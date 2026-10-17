#!/usr/bin/env python3
"""Owner-only proactive texts. Default off.

Enablement is the file ``$HERMES_HOME/proactivity/config.json`` (``/opt/data``
when that variable is unset). The file must contain ``"enabled": true``.
No environment variable turns the feature on. The box zone is the top-level
``timezone`` key in ``$HERMES_HOME/config.yaml``. This script does not read a
timezone from the environment.

Nothing here sends SMS. There is no destination argument. Client texts stay
on ``sms-send-confirmed``, which refuses cron. Scheduled output is a final
response to the owner, or exactly ``[SILENT]``.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KINDS = ("brief", "nudge", "receipt")
QUIET_PHRASES = frozenset({
    "quiet",
    "pause nudges",
    "pause proactive",
    "pause proactive texts",
    "stop nudges",
})
RESUME_PHRASES = frozenset({
    "resume",
    "unquiet",
    "nudges on",
    "resume nudges",
    "resume proactive",
})
CRON_ENVS = (
    "HERMES_CRON_JOB_ID",
    "HERMES_CRON_JOB_NAME",
    "HERMES_CRON_AUTO_DELIVER_PLATFORM",
    "HERMES_CRON_AUTO_DELIVER_CHAT_ID",
)
FORBIDDEN_FLAGS = (
    "--dest",
    "--to",
    "--phone",
    "--recipient",
    "--body",
    "--send",
)
CONTACT_SOURCES = frozenset({"fub", "ghl"})
DEFAULT_CAP = 3
DEFAULT_QUIET = ((21, 0), (8, 0))
DEFAULT_STALE_DAYS = 7
DEFAULT_UNANSWERED_HOURS = 48
DEFAULT_WHO_LIMIT = 3
MAX_CONFIG_BYTES = 16 * 1024
MAX_INPUT_BYTES = 256 * 1024
MAX_ROWS = 50
MAX_NAME = 80
MAX_TOKENS = 64
STAGE_HINT = (
    "Reply 1 to stage. Staging uses sms-send-confirmed and still needs SEND. "
    "This run does not text them."
)
TOKEN_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TZ_LINE = re.compile(r"^timezone:\s*(.*)$")
PHONE_RE = re.compile(r"\+[1-9]\d{6,14}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PROMISE_RE = re.compile(r"\b(i'll|i will)\b", re.IGNORECASE)
OWNER_FACING = ("draft", "sms", "text", "why", "section")


class Stop(Exception):
    def __init__(self, payload: dict, code: int = 0) -> None:
        self.payload = payload
        self.code = code


def home_dir() -> Path:
    raw = os.environ.get("HERMES_HOME") or "/opt/data"
    return Path(raw)


def emit(payload: dict, code: int = 0) -> None:
    print(json.dumps(_scrub(payload), ensure_ascii=False))
    raise SystemExit(code)


def _scrub(value):
    if isinstance(value, dict):
        return {key: _scrub_text(item) if key in OWNER_FACING else _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _scrub_text(value):
    if not isinstance(value, str):
        return _scrub(value)
    value = PHONE_RE.sub("[number omitted]", value)
    value = EMAIL_RE.sub("[address omitted]", value)
    if PROMISE_RE.search(value):
        return "Draft withheld."
    return value


def refuse_forbidden_flags(argv: list[str]) -> None:
    for arg in argv:
        name = arg.split("=", 1)[0]
        if name in FORBIDDEN_FLAGS:
            emit(
                {
                    "ok": False,
                    "owner_only": True,
                    "reason": "refused_owner_only",
                    "detail": "proactive texts go to the owner only",
                },
                2,
            )


def cron_running() -> bool:
    return any(str(os.environ.get(name, "")).strip() for name in CRON_ENVS)


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise Stop({"ok": False, "reason": "usage", "detail": "now is not ISO-8601"}, 2) from exc
    if parsed.tzinfo is None:
        raise Stop({"ok": False, "reason": "usage", "detail": "now must include an offset"}, 2)
    return parsed


def _clock(hm: object) -> tuple[int, int] | None:
    if not isinstance(hm, str) or len(hm) != 5 or hm[2] != ":":
        return None
    hour, minute = hm[:2], hm[3:]
    if not (hour.isdigit() and minute.isdigit()):
        return None
    h, m = int(hour), int(minute)
    if h > 23 or m > 59:
        return None
    return h, m


def _bounded_int(value: object, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < low or value > high:
        return None
    return value


def validate_config(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("config")
    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("enabled")
    cap = DEFAULT_CAP if "daily_cap" not in data else _bounded_int(data.get("daily_cap"), 0, 20)
    stale = DEFAULT_STALE_DAYS if "stale_touch_days" not in data else _bounded_int(data.get("stale_touch_days"), 1, 90)
    hours = (
        DEFAULT_UNANSWERED_HOURS
        if "unanswered_email_hours" not in data
        else _bounded_int(data.get("unanswered_email_hours"), 1, 24 * 14)
    )
    limit = DEFAULT_WHO_LIMIT if "who_limit" not in data else _bounded_int(data.get("who_limit"), 1, 5)
    if None in (cap, stale, hours, limit):
        raise ValueError("bounds")
    start, end = DEFAULT_QUIET
    if "quiet_hours" in data:
        window = data.get("quiet_hours")
        if not isinstance(window, dict):
            raise ValueError("quiet_hours")
        parsed_start = _clock(window.get("start"))
        parsed_end = _clock(window.get("end"))
        if parsed_start is None or parsed_end is None or parsed_start == parsed_end:
            raise ValueError("quiet_hours")
        start, end = parsed_start, parsed_end
    return {
        "enabled": enabled,
        "daily_cap": cap,
        "stale_touch_days": stale,
        "unanswered_email_hours": hours,
        "who_limit": limit,
        "quiet_start": start,
        "quiet_end": end,
    }


def load_config(home: Path) -> tuple[dict | None, str | None]:
    path = home / "proactivity" / "config.json"
    if path.is_symlink():
        return None, "config_unreadable"
    if not path.exists():
        return None, None
    if not path.is_file():
        return None, "config_unreadable"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, "config_unreadable"
    if len(raw) > MAX_CONFIG_BYTES:
        return None, "config_invalid"
    try:
        data = json.loads(raw.decode("utf-8"))
        return validate_config(data), None
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return None, "config_invalid"


def read_timezone(home: Path) -> tuple[str | None, str | None]:
    path = home / "config.yaml"
    if path.is_symlink():
        return None, "timezone_unreadable"
    if not path.exists():
        return None, "timezone_unset"
    if not path.is_file():
        return None, "timezone_unreadable"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, "timezone_unreadable"
    found = None
    for line in text.splitlines():
        if not line or line[0] in " \t#":
            continue
        match = TZ_LINE.match(line.strip())
        if not match:
            continue
        raw = match.group(1).strip()
        if "#" in raw:
            raw = raw.split("#", 1)[0].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1].strip()
        found = raw
        break
    if not found:
        return None, "timezone_unset"
    if found == "UTC" or found.startswith("Etc/"):
        return None, "timezone_refused"
    try:
        ZoneInfo(found)
    except ZoneInfoNotFoundError:
        return None, "timezone_invalid"
    return found, None


def _writable_by_group_or_other(mode: int) -> bool:
    return bool(mode & 0o022)


def _fresh_state() -> dict:
    return {"paused": False, "paused_at": None, "counts": {}, "tokens": []}


def _validate_state(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("state")
    paused = data.get("paused", False)
    if not isinstance(paused, bool):
        raise ValueError("paused")
    paused_at = data.get("paused_at")
    if paused_at is not None and not isinstance(paused_at, str):
        raise ValueError("paused_at")
    counts = data.get("counts", {})
    if not isinstance(counts, dict):
        raise ValueError("counts")
    clean_counts: dict[str, dict[str, int]] = {}
    for day, entry in counts.items():
        if not isinstance(day, str) or DATE_RE.match(day) is None or not isinstance(entry, dict):
            raise ValueError("counts")
        clean_entry = {}
        for kind in KINDS:
            amount = entry.get(kind, 0)
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0 or amount > 1000:
                raise ValueError("counts")
            clean_entry[kind] = amount
        clean_counts[day] = clean_entry
    tokens = data.get("tokens", [])
    if not isinstance(tokens, list) or any(not isinstance(token, str) or TOKEN_RE.match(token) is None for token in tokens):
        raise ValueError("tokens")
    return {
        "paused": paused,
        "paused_at": paused_at,
        "counts": clean_counts,
        "tokens": tokens[-MAX_TOKENS:],
    }


def load_state(home: Path) -> tuple[dict | None, str | None]:
    directory = home / "proactivity"
    path = directory / "state.json"
    if directory.is_symlink() or path.is_symlink():
        return None, "state_unreadable"
    if directory.exists() and _writable_by_group_or_other(directory.stat().st_mode):
        return None, "state_unreadable"
    if not path.exists():
        return _fresh_state(), None
    if not path.is_file():
        return None, "state_unreadable"
    try:
        info = path.stat()
        if _writable_by_group_or_other(info.st_mode):
            return None, "state_unreadable"
        data = json.loads(path.read_text(encoding="utf-8"))
        return _validate_state(data), None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None, "state_unreadable"


def _lock(directory: Path):
    handle = open(directory / ".lock", "a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _prepare_dir(home: Path) -> Path | None:
    directory = home / "proactivity"
    if directory.is_symlink():
        return None
    if not directory.exists():
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    if not directory.is_dir() or directory.is_symlink():
        return None
    if _writable_by_group_or_other(directory.stat().st_mode):
        return None
    return directory


def write_state(home: Path, state: dict) -> str | None:
    """Persist state. Caller holds the directory lock."""
    directory = home / "proactivity"
    if directory.is_symlink() or not directory.is_dir():
        return "state_unreadable"
    if _writable_by_group_or_other(directory.stat().st_mode):
        return "state_unreadable"
    path = directory / "state.json"
    if path.is_symlink():
        return "state_unreadable"
    try:
        payload = json.dumps(_validate_state(state)) + "\n"
    except ValueError:
        return "state_unreadable"
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return "state_unreadable"
    try:
        os.chmod(path, 0o600)
    except OSError:
        return "state_unreadable"
    return None


def _minutes(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


def in_quiet_hours(local: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    current = local.hour * 60 + local.minute
    start_m = _minutes(start)
    end_m = _minutes(end)
    if start_m < end_m:
        return start_m <= current < end_m
    return current >= start_m or current < end_m


def _count(state: dict, day: str) -> int:
    entry = state["counts"].get(day) or {}
    return sum(int(entry.get(kind, 0)) for kind in KINDS)


def _quiet_payload(cfg: dict | None) -> dict:
    if cfg is None:
        start, end = DEFAULT_QUIET
    else:
        start, end = cfg["quiet_start"], cfg["quiet_end"]
    return {"start": f"{start[0]:02d}:{start[1]:02d}", "end": f"{end[0]:02d}:{end[1]:02d}"}


def decide(home: Path, now: datetime, kind: str) -> dict:
    cfg, config_error = load_config(home)
    base = {
        "ok": True,
        "owner_only": True,
        "kind": kind,
        "enabled": False,
        "wakeAgent": False,
        "paused": False,
        "timezone": None,
        "local_date": None,
        "local_time": None,
        "in_quiet_hours": None,
        "count": 0,
        "daily_cap": DEFAULT_CAP if cfg is None else cfg["daily_cap"],
        "remaining": None,
        "quiet_hours": _quiet_payload(cfg),
        "reason": "disabled",
    }
    if config_error:
        base["reason"] = config_error
        return base
    if cfg is None or not cfg["enabled"]:
        state, _state_error = load_state(home)
        if state is not None:
            base["paused"] = state["paused"]
        return base
    base["enabled"] = True
    base["daily_cap"] = cfg["daily_cap"]
    zone_name, zone_error = read_timezone(home)
    if zone_error:
        base["reason"] = zone_error
        return base
    zone = ZoneInfo(zone_name)
    local = now.astimezone(zone)
    base["timezone"] = zone_name
    base["local_date"] = local.date().isoformat()
    base["local_time"] = local.strftime("%H:%M")
    state, state_error = load_state(home)
    if state_error or state is None:
        base["reason"] = state_error or "state_unreadable"
        return base
    count = _count(state, base["local_date"])
    quiet = in_quiet_hours(local, cfg["quiet_start"], cfg["quiet_end"])
    base["paused"] = state["paused"]
    base["in_quiet_hours"] = quiet
    base["count"] = count
    base["remaining"] = max(cfg["daily_cap"] - count, 0)
    if state["paused"]:
        base["reason"] = "quiet"
        return base
    if quiet:
        base["reason"] = "quiet_hours"
        return base
    if count >= cfg["daily_cap"]:
        base["reason"] = "daily_cap"
        return base
    base["wakeAgent"] = True
    base["reason"] = "allowed"
    return base


def record(home: Path, now: datetime, kind: str, token: str) -> dict:
    if TOKEN_RE.match(token) is None:
        raise Stop({"ok": False, "reason": "usage", "detail": "token is not a short id"}, 2)
    directory = home / "proactivity"
    if not directory.exists() and not directory.is_symlink():
        prepared = _prepare_dir(home)
        if prepared is None:
            return {"ok": False, "owner_only": True, "reason": "state_unreadable", "wakeAgent": False, "recorded": False}
        directory = prepared
    if directory.is_symlink() or not directory.is_dir():
        return {"ok": False, "owner_only": True, "reason": "state_unreadable", "wakeAgent": False, "recorded": False}
    if _writable_by_group_or_other(directory.stat().st_mode):
        return {"ok": False, "owner_only": True, "reason": "state_unreadable", "wakeAgent": False, "recorded": False}
    handle = _lock(directory)
    try:
        decision = decide(home, now, kind)
        state, error = load_state(home)
        if error or state is None:
            decision["wakeAgent"] = False
            decision["recorded"] = False
            decision["reason"] = error or "state_unreadable"
            return decision
        if token in state["tokens"]:
            decision["wakeAgent"] = decision["reason"] == "allowed" or decision["reason"] == "daily_cap"
            # A retry of a text that already counted may finish. A new text may not.
            decision["recorded"] = False
            decision["idempotent"] = True
            if decision["reason"] == "daily_cap":
                decision["wakeAgent"] = True
                decision["reason"] = "allowed"
            return decision
        if not decision["wakeAgent"]:
            decision["recorded"] = False
            return decision
        day = decision["local_date"]
        entry = dict(state["counts"].get(day) or {})
        for name in KINDS:
            entry.setdefault(name, 0)
        entry[kind] = int(entry.get(kind, 0)) + 1
        state["counts"][day] = entry
        state["tokens"] = (state["tokens"] + [token])[-MAX_TOKENS:]
        write_error = write_state(home, state)
        if write_error:
            decision["wakeAgent"] = False
            decision["recorded"] = False
            decision["reason"] = write_error
            return decision
        decision["recorded"] = True
        decision["count"] = _count(state, day)
        decision["remaining"] = max(decision["daily_cap"] - decision["count"], 0)
        if decision["remaining"] == 0:
            # This text is the one that fills the cap. It may still go out.
            decision["wakeAgent"] = True
            decision["reason"] = "allowed"
        return decision
    finally:
        handle.close()


def _mutate_pause(home: Path, paused: bool) -> dict:
    if cron_running():
        return {
            "ok": False,
            "owner_only": True,
            "reason": "refused_autonomous",
            "detail": "a scheduled job cannot pause or resume proactive texts",
        }
    directory = _prepare_dir(home)
    if directory is None:
        return {"ok": False, "owner_only": True, "reason": "state_unreadable"}
    handle = _lock(directory)
    try:
        state, error = load_state(home)
        if error or state is None:
            return {"ok": False, "owner_only": True, "reason": error or "state_unreadable"}
        state["paused"] = paused
        state["paused_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if paused else None
        write_error = write_state(home, state)
        if write_error:
            return {"ok": False, "owner_only": True, "reason": write_error}
        cfg, config_error = load_config(home)
        enabled = bool(cfg and cfg["enabled"])
        return {
            "ok": True,
            "owner_only": True,
            "action": "pause" if paused else "resume",
            "paused": paused,
            "enabled": enabled,
            "reason": config_error,
        }
    finally:
        handle.close()


def normalize_phrase(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    collapsed = collapsed.strip("\"'`")
    collapsed = re.sub(r"[.!?]+$", "", collapsed).strip()
    return collapsed


def owner_text(home: Path, text: str) -> dict:
    if len(text) > 80:
        return {"ok": False, "owner_only": True, "reason": "not_a_command"}
    phrase = normalize_phrase(text)
    if phrase in QUIET_PHRASES:
        result = _mutate_pause(home, True)
        result["matched"] = phrase
        return result
    if phrase in RESUME_PHRASES:
        result = _mutate_pause(home, False)
        result["matched"] = phrase
        return result
    state, _error = load_state(home)
    return {
        "ok": False,
        "owner_only": True,
        "reason": "not_a_command",
        "paused": bool(state and state["paused"]),
    }


def _usable_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = " ".join(value.split())
    if not name or len(name) > MAX_NAME:
        return None
    if "@" in name or PHONE_RE.search(name):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        return None
    return name


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _parse_date(value: object) -> datetime | None:
    """Return a date-only value, or a zoned datetime the caller converts."""
    if isinstance(value, str) and DATE_RE.match(value.strip()):
        year, month, day = (int(part) for part in value.strip().split("-"))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return _parse_dt(value)


def _local_date_of(value: object, zone: ZoneInfo) -> object:
    if isinstance(value, str) and DATE_RE.match(value.strip()):
        parsed = _parse_date(value)
        if parsed is None:
            return None
        return parsed.date()
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return parsed.astimezone(zone).date()


def load_candidates(path: Path) -> tuple[dict | None, str | None]:
    if path.is_symlink():
        return None, "input_unreadable"
    if not path.exists() or not path.is_file():
        return None, "input_missing"
    try:
        info = path.stat()
        if info.st_size > MAX_INPUT_BYTES:
            return None, "input_too_large"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "input_invalid"
    if not isinstance(data, dict):
        return None, "input_invalid"
    for key in ("contacts", "emails", "events"):
        rows = data.get(key, [])
        if rows is None:
            rows = []
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            return None, "input_too_large" if isinstance(rows, list) else "input_invalid"
        data[key] = rows
    return data, None


def _when_phrase(moment: datetime, today) -> str:
    local_day = moment.date()
    delta = (today - local_day).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta <= 6:
        return moment.strftime("%A")
    return f"{moment.day} {moment.strftime('%b')}"


def rank_candidates(data: dict, now: datetime, zone_name: str, cfg: dict) -> list[dict]:
    zone = ZoneInfo(zone_name)
    local_now = now.astimezone(zone)
    today = local_now.date()
    found: list[dict] = []

    for row in data.get("contacts") or []:
        if not isinstance(row, dict) or row.get("source") not in CONTACT_SOURCES:
            continue
        name = _usable_name(row.get("name"))
        if name is None:
            continue
        stage_day = _local_date_of(row.get("stage_due"), zone) if row.get("stage_due") else None
        if stage_day is not None and stage_day <= today:
            why = "stage due today" if stage_day == today else "stage overdue"
            found.append({
                "priority": 0,
                "sort": stage_day.toordinal(),
                "who": name,
                "why": why,
                "source": row["source"],
                "draft": f"Draft to {name}: Your file shows a stage due. What should we do next?",
            })
            continue
        last = _parse_dt(row.get("last_touch"))
        if last is None:
            continue
        age_days = (today - last.astimezone(zone).date()).days
        if age_days >= cfg["stale_touch_days"]:
            found.append({
                "priority": 3,
                "sort": last.timestamp(),
                "who": name,
                "why": f"no touch in {age_days} days",
                "source": row["source"],
                "draft": (
                    f"Draft to {name}: It has been {age_days} days since the last logged touch. "
                    "What is the next step?"
                ),
            })

    for item in _open_emails(data, now, zone, today, cfg):
        found.append({
            "priority": 2,
            "sort": item["sort"],
            "who": item["who"],
            "why": f"no reply since {item['when']}",
            "source": "gmail",
            "when": item["when"],
            "draft": f"Draft to {item['who']}: Following up on your email from {item['when']}.",
        })

    for row in data.get("events") or []:
        if not isinstance(row, dict):
            continue
        name = _usable_name(row.get("who"))
        start = _parse_dt(row.get("start"))
        if name is None or start is None:
            continue
        if start.astimezone(zone).date() != today:
            continue
        found.append({
            "priority": 1,
            "sort": start.timestamp(),
            "who": name,
            "why": "on your calendar today",
            "source": "calendar",
            "draft": f"Draft to {name}: Confirming today's meeting. What should we settle first?",
        })

    found.sort(key=lambda item: (item["priority"], item["sort"], item["who"]))
    chosen: list[dict] = []
    seen: set[str] = set()
    for item in found:
        key = item["who"].casefold()
        if key in seen:
            continue
        seen.add(key)
        public = {
            "who": item["who"],
            "why": item["why"],
            "source": item["source"],
            "draft": item["draft"],
        }
        if "when" in item:
            public["when"] = item["when"]
        chosen.append(public)
    return chosen


def _open_emails(data: dict, now: datetime, zone: ZoneInfo, today, cfg: dict) -> list[dict]:
    """Unanswered known-client mail older than the configured hours. Oldest first."""
    found: list[dict] = []
    for row in data.get("emails") or []:
        if not isinstance(row, dict):
            continue
        if row.get("unanswered") is not True or row.get("known_client") is not True:
            continue
        name = _usable_name(row.get("name"))
        received = _parse_dt(row.get("received_at"))
        if name is None or received is None:
            continue
        if (now - received).total_seconds() < cfg["unanswered_email_hours"] * 3600:
            continue
        found.append({
            "sort": received.timestamp(),
            "who": name,
            "when": _when_phrase(received.astimezone(zone), today),
        })
    found.sort(key=lambda item: (item["sort"], item["who"]))
    return found


def unanswered_emails(data: dict, now: datetime, zone_name: str, cfg: dict) -> list[dict]:
    """Oldest unanswered known-client emails. Not limited by the morning section."""
    zone = ZoneInfo(zone_name)
    today = now.astimezone(zone).date()
    chosen: list[dict] = []
    seen: set[str] = set()
    for item in _open_emails(data, now, zone, today, cfg):
        key = item["who"].casefold()
        if key in seen:
            continue
        seen.add(key)
        chosen.append({"who": item["who"], "when": item["when"], "source": "gmail"})
    return chosen


def _sms_hint(items: list[dict]) -> str | None:
    if not items:
        return None
    parts: list[str] = []
    for item in items:
        parts.append(f"{item['who']} ({item['why']})")
        trial = "Who needs you: " + "; ".join(parts)
        if len(trial) > 320:
            parts.pop()
            break
    if not parts:
        return "Who needs you: " + items[0]["who"]
    return "Who needs you: " + "; ".join(parts)


def who(home: Path, now: datetime, input_path: Path | None) -> dict:
    cfg, config_error = load_config(home)
    if config_error:
        return {
            "ok": False,
            "owner_only": True,
            "enabled": False,
            "reason": config_error,
            "section": None,
            "items": [],
            "sms": None,
        }
    if cfg is None or not cfg["enabled"]:
        return {
            "ok": True,
            "owner_only": True,
            "enabled": False,
            "reason": "disabled",
            "section": None,
            "items": [],
            "sms": None,
        }
    zone_name, zone_error = read_timezone(home)
    if zone_error:
        return {
            "ok": False,
            "owner_only": True,
            "enabled": True,
            "reason": zone_error,
            "section": None,
            "items": [],
            "sms": None,
        }
    if input_path is None:
        return {
            "ok": False,
            "owner_only": True,
            "enabled": True,
            "reason": "input_missing",
            "section": None,
            "items": [],
            "sms": None,
        }
    data, input_error = load_candidates(input_path)
    if input_error or data is None:
        return {
            "ok": False,
            "owner_only": True,
            "enabled": True,
            "reason": input_error or "input_invalid",
            "section": None,
            "items": [],
            "sms": None,
        }
    ranked = rank_candidates(data, now, zone_name, cfg)
    items = []
    for item in ranked[: cfg["who_limit"]]:
        numbered = dict(item)
        numbered["rank"] = len(items) + 1
        items.append(numbered)
    section = "Who needs you today" if items else None
    return {
        "ok": True,
        "owner_only": True,
        "enabled": True,
        "reason": "ready" if items else "none",
        "timezone": zone_name,
        "section": section,
        "items": items,
        "sms": _sms_hint(items),
        "stage_hint": STAGE_HINT if items else None,
    }


def _nudge_text(emails: list[dict]) -> str | None:
    if not emails:
        return None
    top = emails[0]
    extra = len(emails) - 1
    when = top.get("when") or "earlier"
    lead = f"You haven't replied to {top['who']}'s email from {when}."
    if extra == 1:
        lead += " 1 other client email is also waiting."
    elif extra > 1:
        lead += f" {extra} other client emails are also waiting."
    return f"{lead} Draft: Following up on your email from {when}."


def nudge(home: Path, now: datetime, input_path: Path | None, token: str | None) -> dict:
    decision = decide(home, now, "nudge")
    silent = {
        "ok": True,
        "owner_only": True,
        "deliver": False,
        "silent": True,
        "text": "[SILENT]",
        "recorded": False,
        "reason": decision["reason"],
        "wakeAgent": False,
    }
    if not decision["wakeAgent"]:
        return silent
    if input_path is None:
        silent["reason"] = "input_missing"
        return silent
    data, input_error = load_candidates(input_path)
    if input_error or data is None:
        silent["reason"] = input_error or "input_invalid"
        return silent
    emails = unanswered_emails(data, now, decision["timezone"], _cfg_from_decision(home))
    text = _nudge_text(emails)
    if text is None:
        silent["reason"] = "none"
        return silent
    if len(text) > 549:
        silent["reason"] = "too_long"
        return silent
    record_token = token or f"nudge:{decision['local_date']}"
    recorded = record(home, now, "nudge", record_token)
    if recorded.get("idempotent") or not recorded.get("wakeAgent"):
        silent["reason"] = "already_sent" if recorded.get("idempotent") else (recorded.get("reason") or "daily_cap")
        return silent
    return {
        "ok": True,
        "owner_only": True,
        "deliver": True,
        "silent": False,
        "text": text,
        "recorded": bool(recorded.get("recorded")),
        "idempotent": bool(recorded.get("idempotent")),
        "reason": "allowed",
        "wakeAgent": True,
        "timezone": decision["timezone"],
        "local_date": decision["local_date"],
    }


def _cfg_from_decision(home: Path) -> dict:
    cfg, error = load_config(home)
    if error or cfg is None or not cfg["enabled"]:
        raise Stop({"ok": False, "owner_only": True, "reason": error or "disabled", "text": "[SILENT]", "silent": True}, 0)
    return cfg


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--now", default=None)
    parser = argparse.ArgumentParser(prog="proactive.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gate = sub.add_parser("gate", parents=[common])
    gate.add_argument("--kind", required=True, choices=KINDS)
    gate.add_argument("--pre-script", action="store_true")

    recorded = sub.add_parser("record", parents=[common])
    recorded.add_argument("--kind", required=True, choices=KINDS)
    recorded.add_argument("--token", required=True)

    owner = sub.add_parser("owner", parents=[common])
    owner.add_argument("--text", required=True)

    sub.add_parser("status", parents=[common])

    listed = sub.add_parser("who", parents=[common])
    listed.add_argument("--input", required=False)

    afternoon = sub.add_parser("nudge", parents=[common])
    afternoon.add_argument("--input", required=False)
    afternoon.add_argument("--token", default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args_list = list(sys_argv() if argv is None else argv)
    refuse_forbidden_flags(args_list)
    try:
        args = build_parser().parse_args(args_list)
        now = parse_now(args.now)
        root = home_dir()
        if args.cmd == "gate":
            payload = decide(root, now, args.kind)
            payload["pre_script"] = bool(args.pre_script)
            emit(payload)
        elif args.cmd == "record":
            emit(record(root, now, args.kind, args.token))
        elif args.cmd == "owner":
            emit(owner_text(root, args.text))
        elif args.cmd == "status":
            payload = decide(root, now, "brief")
            payload["cmd"] = "status"
            emit(payload)
        elif args.cmd == "who":
            path = Path(args.input) if args.input else None
            emit(who(root, now, path))
        elif args.cmd == "nudge":
            path = Path(args.input) if args.input else None
            emit(nudge(root, now, path, args.token))
        else:
            emit({"ok": False, "reason": "usage"}, 2)
    except Stop as stop:
        emit(stop.payload, stop.code)


def sys_argv() -> list[str]:
    return sys.argv[1:]


if __name__ == "__main__":
    main()
