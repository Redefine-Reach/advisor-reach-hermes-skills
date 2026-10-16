#!/usr/bin/env python3
"""Thin wrapper around the Hermes 0.21.0 runtime for milestone-zero evals."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from live_session import LiveEvalContext, begin_live_session, hermes_chat_argv, is_fixture_only_live
from outbound_stub import DELIVERED, OutboundRecorder, infer_fixture_outbound, start_http_stub, stub_env

HERMES_PIN = "0.21.0"

_live_ctx: LiveEvalContext | None = None


@dataclass
class HermesWrapProof:
    pin: str
    detected: str | None
    ok: bool
    detail: str


def detect_hermes_version() -> str | None:
    env = os.environ.get("HERMES_VERSION") or os.environ.get("HERMES_PIN")
    if env:
        return env.strip()
    binary = shutil.which("hermes")
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    return text or None


def prove_wrap() -> HermesWrapProof:
    detected = detect_hermes_version()
    if not detected:
        return HermesWrapProof(
            pin=HERMES_PIN,
            detected=None,
            ok=False,
            detail="hermes binary not found; set HERMES_VERSION for fixture-only trials",
        )
    ok = HERMES_PIN in detected
    return HermesWrapProof(
        pin=HERMES_PIN,
        detected=detected,
        ok=ok,
        detail="version matches pin" if ok else f"expected {HERMES_PIN} in {detected}",
    )


def ensure_live_session() -> tuple[LiveEvalContext | None, str | None]:
    global _live_ctx
    if _live_ctx is not None:
        return _live_ctx, None
    source = Path(os.environ.get("HERMES_HOME", "/opt/data"))
    ctx, err = begin_live_session(source)
    if err:
        return None, err
    _live_ctx = ctx
    return ctx, None


def shutdown_live_session() -> None:
    global _live_ctx
    if _live_ctx is not None:
        _live_ctx.shutdown()
        _live_ctx = None


def _parse_tool_calls(text: str) -> list[dict[str, str]]:
    tools: list[dict[str, str]] = []
    for match in re.finditer(r'"tool(?:_name)?"\s*:\s*"([^"]+)"', text):
        tools.append({"name": match.group(1)})
    for name in ("sms_send_confirmed", "learning_loop", "client-profile"):
        if name in text and not any(t.get("name") == name for t in tools):
            tools.append({"name": name})
    return tools


def run_fixture(case: dict[str, Any], recorder: OutboundRecorder | None = None) -> dict[str, Any]:
    fixture = case.get("fixture") or {}
    rec = recorder or OutboundRecorder()
    rec.clear()
    infer_fixture_outbound(case, rec)
    return {
        "mode": "fixture",
        "assistant_text": fixture.get("assistant_text", ""),
        "tool_calls": fixture.get("tool_calls") or [],
        "outbound_log": rec.snapshot(),
        "hermes_pin": HERMES_PIN,
    }


def _stub_hermes_live(case: dict[str, Any], recorder: OutboundRecorder) -> dict[str, Any]:
    fixture = case.get("fixture") or {}
    infer_fixture_outbound(case, recorder)
    return {
        "mode": "hermes",
        "dry_run": False,
        "stub_hermes": True,
        "ok": True,
        "assistant_text": fixture.get("assistant_text", ""),
        "tool_calls": fixture.get("tool_calls") or [],
        "outbound_log": recorder.snapshot(),
        "hermes_pin": HERMES_PIN,
    }


def run_hermes(
    case: dict[str, Any],
    dry_run: bool = True,
    recorder: OutboundRecorder | None = None,
    live_ctx: LiveEvalContext | None = None,
) -> dict[str, Any]:
    proof = prove_wrap()
    rec = recorder or OutboundRecorder()
    rec.clear()
    owner = (case.get("input") or {}).get("owner_text", "")

    if dry_run:
        fixture = case.get("fixture") or {}
        infer_fixture_outbound(case, rec)
        return {
            "mode": "hermes",
            "dry_run": True,
            "ok": True,
            "would_send": owner[:120],
            "proof": proof.__dict__,
            "hermes_pin": HERMES_PIN,
            "assistant_text": fixture.get("assistant_text", ""),
            "tool_calls": fixture.get("tool_calls") or [],
            "outbound_log": rec.snapshot(),
        }

    if is_fixture_only_live(case):
        out = run_fixture(case, recorder=rec)
        out["mode"] = "hermes"
        out["live_skipped"] = "fixture_only"
        out["ok"] = True
        return out

    if os.environ.get("ARIN_EVAL_STUB_HERMES") == "1":
        return {**_stub_hermes_live(case, rec), "proof": proof.__dict__}

    if not proof.ok:
        return {"mode": "hermes", "ok": False, "error": "hermes_version_mismatch", "proof": proof.__dict__}

    binary = shutil.which("hermes")
    if not binary:
        return {"mode": "hermes", "ok": False, "error": "hermes_missing", "proof": proof.__dict__}

    ctx = live_ctx
    if ctx is None:
        ctx, err = ensure_live_session()
        if err or ctx is None:
            return {"mode": "hermes", "ok": False, "error": err or "live_session_failed", "proof": proof.__dict__}

    ctx.recorder.clear()
    rec = ctx.recorder
    env = {**os.environ, **ctx.env_overlay()}
    argv = hermes_chat_argv(binary, owner)
    query_file = None
    if "--query-file" in argv:
        query_file = argv[argv.index("--query-file") + 1]

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("ARIN_EVAL_HERMES_TIMEOUT", "180")),
            check=False,
            env=env,
            cwd=str(ctx.hermes_home),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"mode": "hermes", "ok": False, "error": str(exc), "proof": proof.__dict__}
    finally:
        if query_file:
            Path(query_file).unlink(missing_ok=True)

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assistant = (proc.stdout or "").strip()
    if rec.delivered_count() > 0:
        return {
            "mode": "hermes",
            "ok": False,
            "error": "outbound_delivered",
            "outbound_log": rec.snapshot(),
            "proof": proof.__dict__,
        }

    return {
        "mode": "hermes",
        "dry_run": False,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "assistant_text": assistant,
        "tool_calls": _parse_tool_calls(combined),
        "outbound_log": rec.snapshot(),
        "hermes_pin": HERMES_PIN,
        "proof": proof.__dict__,
        "interception_probe": ctx.probe,
        "hermes_home": str(ctx.hermes_home),
    }


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))
