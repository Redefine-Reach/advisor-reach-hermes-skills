"""Test-only socket guard (PYTHONSTARTUP). Blocks non-local and Telnyx hosts."""
from __future__ import annotations

import socket

_ALLOWED = frozenset({"127.0.0.1", "::1", "localhost"})
_ORIG = socket.create_connection


def _guarded(address, *args, **kwargs):
    host = str(address[0]).lower()
    if host == "api.telnyx.com" or host.endswith(".telnyx.com"):
        raise OSError(f"blocked Telnyx host {host!r}")
    if host not in _ALLOWED:
        raise OSError(f"blocked non-local network connect to {host!r}")
    return _ORIG(address, *args, **kwargs)


socket.create_connection = _guarded
