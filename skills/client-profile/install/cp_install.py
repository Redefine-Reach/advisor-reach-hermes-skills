#!/usr/bin/env python3
"""Files-only install for the client-profile skill.

python3 cp_install.py <install|uninstall|status|on|off> [box_slug]

Paths default to /opt/data. Tests set CLIENT_PROFILE_INSTALL_ROOT.
Does not restart a box, bake an image, or change a StatefulSet env var.
Prints one JSON object.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BEGIN = "<!-- BEGIN client-profile v1 -->"
END = "<!-- END client-profile v1 -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HERE = Path(__file__).resolve().parent
SKILL_SRC = HERE.parent
SOUL_BLOCK = HERE / "soul-block.md"


def emit(obj: dict, code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    raise SystemExit(code)


def install_root() -> Path:
    raw = os.environ.get("CLIENT_PROFILE_INSTALL_ROOT")
    return Path(raw) if raw else Path("/opt/data")


def paths() -> dict[str, Path]:
    root = install_root()
    return {
        "soul": root / "SOUL.md",
        "skill": root / "skills" / "client-profile",
        "cfg": root / "client-profile" / "config.json",
        "data": root / "client-profile",
    }


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_soul(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def backup_soul(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"SOUL.md.bak-client-profile-{stamp}")
    n = 0
    while dest.exists():
        n += 1
        dest = path.with_name(f"SOUL.md.bak-client-profile-{stamp}-{n}")
    shutil.copy2(path, dest)


def block_present(text: str) -> bool:
    return BEGIN in text and END in text


def load_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def skill_present(path: Path) -> bool:
    return (path / "SKILL.md").is_file() and (path / "scripts" / "cp.py").is_file()


def owner_number() -> str | None:
    raw = os.environ.get("TELNYX_SMS_ALLOWED_USERS", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1 and re.fullmatch(r"\+\d{8,15}", parts[0]):
        return parts[0]
    return None


def copy_skill(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        SKILL_SRC,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.tmp"),
    )


def run_selftest(skill: Path, data: Path) -> dict:
    script = skill / "scripts" / "cp.py"
    env = os.environ.copy()
    env["CLIENT_PROFILE_ROOT"] = str(data)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(script), "selftest"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        payload = {"ok": False, "error": "selftest_output"}
    if not isinstance(payload, dict):
        payload = {"ok": False, "error": "selftest_output"}
    return payload


def cmd_status() -> dict:
    p = paths()
    soul = read_soul(p["soul"])
    cfg = load_config(p["cfg"])
    return {
        "ok": True,
        "action": "status",
        "block_present": block_present(soul),
        "skill_present": skill_present(p["skill"]),
        "config": cfg,
        "enabled": bool(cfg and cfg.get("enabled") is True),
    }


def cmd_install(slug: str | None) -> None:
    if not SOUL_BLOCK.is_file() or BEGIN not in SOUL_BLOCK.read_text(encoding="utf-8"):
        emit({"ok": False, "error": "soul_block_missing"}, 1)
    p = paths()
    if not p["soul"].exists():
        emit({"ok": False, "error": "soul_missing", "message": "SOUL.md is not on this box."}, 1)
    before = read_soul(p["soul"])
    before_sha = sha256(before)
    backup_soul(p["soul"])
    block = SOUL_BLOCK.read_text(encoding="utf-8").strip() + "\n"
    if block_present(before):
        after = before if before.endswith("\n") else before + "\n"
    else:
        sep = "" if before.endswith("\n") or before == "" else "\n"
        after = before + sep + "\n" + block
    p["soul"].write_text(after, encoding="utf-8")
    copy_skill(p["skill"])
    existing = load_config(p["cfg"]) or {}
    existing["enabled"] = True
    existing["schema_version"] = 1
    if "consent_required" not in existing:
        existing["consent_required"] = True
    existing["installed_at"] = datetime.now(timezone.utc).isoformat()
    existing["tz"] = existing.get("tz") or "America/Phoenix"
    if slug:
        existing["box"] = slug
    elif "box" not in existing:
        existing["box"] = ""
    number = owner_number()
    if number and "owner_number" not in existing:
        existing["owner_number"] = number
    write_json(p["cfg"], existing)
    selftest = run_selftest(p["skill"], p["data"])
    result = {
        "ok": bool(selftest.get("ok")),
        "action": "install",
        "soul_sha_before": before_sha,
        "soul_sha_after": sha256(read_soul(p["soul"])),
        "block_present": block_present(read_soul(p["soul"])),
        "skill_present": skill_present(p["skill"]),
        "config": load_config(p["cfg"]),
        "selftest": selftest,
    }
    emit(result, 0 if result["ok"] else 1)


def cmd_uninstall() -> None:
    p = paths()
    if p["soul"].exists():
        backup_soul(p["soul"])
        text = read_soul(p["soul"])
        text = BLOCK_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        p["soul"].write_text(text, encoding="utf-8")
    if p["skill"].exists():
        shutil.rmtree(p["skill"])
    cfg = load_config(p["cfg"]) or {
        "schema_version": 1,
        "tz": "America/Phoenix",
        "box": "",
    }
    cfg["enabled"] = False
    write_json(p["cfg"], cfg)
    soul = read_soul(p["soul"])
    emit({
        "ok": True,
        "action": "uninstall",
        "block_present": block_present(soul),
        "skill_present": skill_present(p["skill"]),
        "config": load_config(p["cfg"]),
        "enabled": False,
    })


def cmd_flip(enabled: bool) -> None:
    p = paths()
    cfg = load_config(p["cfg"])
    if cfg is None:
        emit({"ok": False, "error": "config_missing"}, 1)
    cfg["enabled"] = enabled
    write_json(p["cfg"], cfg)
    emit({
        "ok": True,
        "action": "on" if enabled else "off",
        "enabled": enabled,
        "config": load_config(p["cfg"]),
    })


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        emit({"ok": False, "error": "usage", "message": "install|uninstall|status|on|off [box_slug]"}, 1)
    action = argv[1]
    slug = argv[2] if len(argv) > 2 else None
    if slug is not None and not SLUG_RE.fullmatch(slug):
        emit({"ok": False, "error": "bad_slug"}, 1)
    if len(argv) > 3:
        emit({"ok": False, "error": "usage"}, 1)
    if action == "status":
        emit(cmd_status())
    elif action == "install":
        cmd_install(slug)
    elif action == "uninstall":
        cmd_uninstall()
    elif action == "on":
        cmd_flip(True)
    elif action == "off":
        cmd_flip(False)
    else:
        emit({"ok": False, "error": "usage", "message": "unknown action"}, 1)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except SystemExit:
        raise
    except Exception as exc:
        emit({"ok": False, "error": "internal", "message": type(exc).__name__}, 1)
