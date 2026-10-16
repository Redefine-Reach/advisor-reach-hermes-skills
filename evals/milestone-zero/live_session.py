#!/usr/bin/env python3
"""Live Hermes eval sandbox: stub SMS, throwaway HERMES_HOME, interception probe."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from outbound_stub import OutboundRecorder, start_http_stub, stub_env

CREDENTIAL_ENV_KEYS = [
    "COMPOSIO_API_KEY",
    "COMPOSIO_ENTITY_ID",
    "COMPOSIO_CONNECTED_ACCOUNT_ID",
    "GHL_API_KEY",
    "GHL_LOCATION_ID",
    "FUB_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GMAIL_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "TELNYX_API_KEY",
]

SANDBOX_REMOVE_RELATIVE = [
    "MEMORY.md",
    "USER.md",
    "sessions",
    "memory",
    "audit",
    "learning-loop",
    "client-profile",
    "google_token.json",
    ".env",
]


@dataclass
class LiveEvalContext:
    hermes_home: Path
    stub_base: str
    server: Any
    recorder: OutboundRecorder
    sms_runtime_env: Path
    sms_proc_environ: Path
    probe: dict[str, Any]

    def env_overlay(self) -> dict[str, str]:
        overlay = stub_env(self.recorder, self.stub_base)
        overlay.update(
            {
                "HERMES_HOME": str(self.hermes_home),
                "SMS_RUNTIME_ENV_FILE": str(self.sms_runtime_env),
                "SMS_PROC_ENVIRON": str(self.sms_proc_environ),
                "TELNYX_API_KEY": "",
                "ARIN_EVAL_BOX": os.environ.get("ARIN_EVAL_BOX", "e23fjkv6"),
                # Keep staged drafts and the outbound audit log inside the throwaway home,
                # never the real /opt/data/audit (sms_send_confirmed.py defaults to it).
                "SMS_DRAFT_DIR": str(self.hermes_home / "audit" / "sms-drafts"),
                "SMS_AUDIT_PATH": str(self.hermes_home / "audit" / "sms-outbound.jsonl"),
            }
        )
        (self.hermes_home / "audit" / "sms-drafts").mkdir(parents=True, exist_ok=True)
        for key in CREDENTIAL_ENV_KEYS:
            overlay.setdefault(key, "")
        return overlay

    def shutdown(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        if self.hermes_home.exists():
            shutil.rmtree(self.hermes_home, ignore_errors=True)


def hermes_chat_argv(binary: str, owner_text: str) -> list[str]:
    """Hermes 0.21.0: ``chat -Q -q "<text>" --source telnyx_sms``.

    ``--source`` makes the CLI session look like an SMS turn so sms_stage does not refuse
    it as "not the authorized owner". ARIN_EVAL_OWNER_PREFIX (default names the stub owner
    number) is prepended to the owner text, standing in for the gateway's sender context.
    Set either to an empty string to disable.
    """
    src = os.environ.get("ARIN_EVAL_SOURCE", "telnyx_sms")
    prefix = os.environ.get("ARIN_EVAL_OWNER_PREFIX", "[SMS from box owner +15550100099]")
    text = f"{prefix} {owner_text}".strip() if prefix else owner_text
    extra = ["--source", src] if src else []
    if len(text) > 4000 or "\n" in text:
        query_file = Path(tempfile.mkstemp(prefix="arin-eval-query-", suffix=".txt")[1])
        query_file.write_text(text, encoding="utf-8")
        return [binary, "chat", "-Q", "--query-file", str(query_file), *extra]
    return [binary, "chat", "-Q", "-q", text, *extra]


def write_sms_stub_files(stub_base: str, dest_dir: Path) -> tuple[Path, Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    runtime = dest_dir / "sms-runtime.env"
    proc_empty = dest_dir / "proc-environ.empty"
    runtime.write_text(
        "\n".join(
            [
                f"TELNYX_SMS_API_BASE={stub_base.rstrip('/')}",
                "TELNYX_SMS_FROM_NUMBER=+15550100001",
                "TELNYX_SMS_ALLOWED_USERS=+15550100099",
                "TELNYX_API_KEY=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    proc_empty.write_bytes(b"")
    return runtime, proc_empty


def _ignore_copy(directory: str, names: list[str]) -> set[str]:
    skip = set(shutil.ignore_patterns(".git", "node_modules", "__pycache__")(directory, names))
    for n in names:
        if stat.S_ISSOCK(os.lstat(os.path.join(directory, n)).st_mode):
            skip.add(n)
    return skip


def make_eval_hermes_home(source: Path | None) -> Path:
    src = source or Path(os.environ.get("HERMES_HOME", "/opt/data"))
    dest = Path(tempfile.mkdtemp(prefix="arin-eval-hermes-home-"))
    if src.is_dir():
        shutil.copytree(
            src,
            dest,
            dirs_exist_ok=True,
            ignore=_ignore_copy,
        )
    for rel in SANDBOX_REMOVE_RELATIVE:
        target = dest / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.is_file():
            target.unlink(missing_ok=True)
    (dest / "MEMORY.md").write_text("# ARIN eval sandbox\n", encoding="utf-8")
    (dest / "USER.md").write_text("# ARIN eval sandbox\n", encoding="utf-8")
    return dest


def interception_probe(stub_base: str, runtime_env: Path, proc_environ: Path) -> tuple[bool, dict[str, Any]]:
    """Fail closed unless outbound SMS can only reach the local stub."""
    detail: dict[str, Any] = {"stub_base": stub_base}
    try:
        runtime_text = runtime_env.read_text(encoding="utf-8")
    except OSError as exc:
        return False, {**detail, "error": f"runtime_env_missing: {exc}"}
    if "TELNYX_API_KEY=" in runtime_text:
        for line in runtime_text.splitlines():
            if line.startswith("TELNYX_API_KEY=") and line.split("=", 1)[1].strip():
                return False, {**detail, "error": "runtime_env_has_telnyx_api_key"}
    if stub_base.rstrip("/") not in runtime_text:
        return False, {**detail, "error": "runtime_env_missing_stub_base"}
    try:
        proc_blob = proc_environ.read_bytes()
    except OSError as exc:
        return False, {**detail, "error": f"proc_environ_missing: {exc}"}
    if b"TELNYX" in proc_blob or b"COMPOSIO" in proc_blob:
        return False, {**detail, "error": "proc_environ_must_be_empty"}
    url = stub_base.rstrip("/") + "/v2/messages"
    req = urllib.request.Request(
        url,
        data=b'{"to":"+15550100002","text":"arin-eval-probe"}',
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return False, {**detail, "error": f"probe_http_failed: {exc}"}
    detail["probe_response"] = body[:200]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return False, {**detail, "error": "probe_not_json"}
    if not parsed.get("blocked") and parsed.get("provider_status") != "eval_stub":
        return False, {**detail, "error": "probe_not_stubbed"}
    return True, detail


def begin_live_session(source_home: Path | None = None) -> tuple[LiveEvalContext | None, str | None]:
    recorder = OutboundRecorder()
    server, base = start_http_stub(recorder)
    stub_dir = Path(tempfile.mkdtemp(prefix="arin-eval-sms-stub-"))
    runtime, proc_empty = write_sms_stub_files(base, stub_dir)
    ok, probe_detail = interception_probe(base, runtime, proc_empty)
    if not ok:
        server.shutdown()
        shutil.rmtree(stub_dir, ignore_errors=True)
        return None, probe_detail.get("error") or "interception_probe_failed"
    home = make_eval_hermes_home(source_home)
    ctx = LiveEvalContext(
        hermes_home=home,
        stub_base=base,
        server=server,
        recorder=recorder,
        sms_runtime_env=runtime,
        sms_proc_environ=proc_empty,
        probe=probe_detail,
    )
    return ctx, None


def is_fixture_only_live(case: dict[str, Any]) -> bool:
    return case.get("live_mode") == "fixture_only"


def filter_cases_for_live(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return cases
