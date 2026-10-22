"""Test-only socket guard (loaded via site-packages .pth in CI venv). Blocks non-local and Telnyx hosts."""
from __future__ import annotations

import socket

_ALLOWED = frozenset({"127.0.0.1", "::1", "localhost"})
_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_GETADDRINFO = socket.getaddrinfo
_ORIG_SOCKET_CONNECT = socket.socket.connect


def _enforce_host(host: object) -> None:
    name = str(host).lower()
    if name == "api.telnyx.com" or name.endswith(".telnyx.com"):
        raise OSError(f"blocked Telnyx host {name!r}")
    if name not in _ALLOWED:
        raise OSError(f"blocked non-local network connect to {name!r}")


def _guarded_create_connection(address, *args, **kwargs):
    _enforce_host(address[0])
    return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)


def _guarded_connect(self, address):
    if isinstance(address, tuple) and address:
        _enforce_host(address[0])
    return _ORIG_SOCKET_CONNECT(self, address)


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    if host is not None and str(host).strip():
        _enforce_host(host)
    return _ORIG_GETADDRINFO(host, port, *args, **kwargs)


socket.create_connection = _guarded_create_connection
socket.getaddrinfo = _guarded_getaddrinfo
socket.socket.connect = _guarded_connect
