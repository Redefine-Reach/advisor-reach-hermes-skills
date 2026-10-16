#!/usr/bin/env python3
"""Thin wrapper around the Hermes 0.21.0 runtime for milestone-zero evals."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

HERMES_PIN = "0.21.0"


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


def run_fixture(case: dict[str, Any]) -> dict[str, Any]:
    """Replay a redacted trajectory without calling the model."""
    fixture = case.get("fixture") or {}
    return {
        "mode": "fixture",
        "assistant_text": fixture.get("assistant_text", ""),
        "tool_calls": fixture.get("tool_calls") or [],
        "hermes_pin": HERMES_PIN,
    }


def run_hermes(case: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
    proof = prove_wrap()
    if not proof.ok and not dry_run:
        return {"mode": "hermes", "ok": False, "error": "hermes_version_mismatch", "proof": proof.__dict__}
    owner = (case.get("input") or {}).get("owner_text", "")
    if dry_run:
        return {
            "mode": "hermes",
            "dry_run": True,
            "ok": True,
            "would_send": owner[:120],
            "proof": proof.__dict__,
            "hermes_pin": HERMES_PIN,
            "assistant_text": (case.get("fixture") or {}).get("assistant_text", ""),
            "tool_calls": (case.get("fixture") or {}).get("tool_calls") or [],
        }
    # Live invoke is box-only; not enabled in this repo's CI.
    return {"mode": "hermes", "ok": False, "error": "live_invoke_disabled", "proof": proof.__dict__}


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))
