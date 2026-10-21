#!/usr/bin/env python3
"""Record outbound SMS attempts during evals; never deliver off-box."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DELIVERED = "delivered"
STAGED = "staged"
BLOCKED = "blocked"


@dataclass
class OutboundRecorder:
    """In-process log used by fixture replay and live Hermes trials."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def clear(self) -> None:
        self.entries.clear()

    def record(self, kind: str, **fields: Any) -> None:
        self.entries.append({"kind": kind, **fields})

    def staged_count(self) -> int:
        return sum(1 for e in self.entries if e.get("kind") == STAGED)

    def delivered_count(self) -> int:
        return sum(1 for e in self.entries if e.get("kind") == DELIVERED)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.entries)

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in self.entries:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class _StubHandler(BaseHTTPRequestHandler):
    recorder: OutboundRecorder | None = None

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        rec = self.recorder
        if rec is not None:
            rec.record(BLOCKED, path=self.path, body_len=len(body), note="stub_blocked_no_network")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"blocked":true,"provider_status":"eval_stub"}')


def start_http_stub(recorder: OutboundRecorder) -> tuple[HTTPServer, str]:
    handler = type("Handler", (_StubHandler,), {})
    handler.recorder = recorder
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    return server, f"http://{host}:{port}"


def stub_env(recorder: OutboundRecorder, base_url: str) -> dict[str, str]:
    return {
        "ARIN_EVAL": "1",
        "ARIN_EVAL_BLOCK_OUTBOUND": "1",
        "TELNYX_SMS_API_BASE": base_url.rstrip("/"),
        "TELNYX_SMS_FROM_NUMBER": "+15550100001",
        "TELNYX_SMS_ALLOWED_USERS": "+15550100099",
    }


def infer_fixture_outbound(case: dict[str, Any], recorder: OutboundRecorder) -> None:
    """Seed outbound log for fixture replay from case expectations."""
    expect = case.get("expect") or {}
    if expect.get("send_staged_not_sent"):
        recorder.record(STAGED, tool="sms_send_confirmed", confirmed=False)
    if expect.get("send_confirmed"):
        recorder.record(STAGED, tool="sms_send_confirmed", confirmed=True)
        recorder.record(DELIVERED, tool="sms_send_confirmed", confirmed=True)
