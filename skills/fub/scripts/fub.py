#!/usr/bin/env python3
"""Follow Up Boss (FUB) for this box: connect, claim, status, api, disconnect.

The access token lives ONLY in /opt/data/fub/token.json (mode 0600, written atomically)
and is never printed. `api` sends it to Follow Up Boss itself. The AdvisorReach API's
FUB Mount (/fub/v1) holds the OAuth client secret and the registered system key;
this script never stores or sends either one. Every command prints one JSON object.

The Follow Up Boss host is fixed to api.followupboss.com. FUB_API_BASE is honored
only for an http loopback origin so tests can stand in; any other value is refused.

Exit codes: 0 ok; 1 error (read "error"); 2 `claim` before the user finished signing in.
"""
import argparse
import http.client
import json
import math
import os
import ssl
import stat
import sys
import time
import urllib.parse

FUB_HOST = "api.followupboss.com"
FUB_PREFIX = "/v1"
MOUNT_PREFIX = "/fub/v1"
USER_AGENT = "advisorreach-box/1.0"
REFRESH_MARGIN_SECONDS = 300
TIMEOUT_SECONDS = 30
MAX_BYTES = 1024 * 1024
MAX_DEPTH = 32

# Folded JSON key names whose values are credentials. "system" is the public
# X-System name and is intentionally not in this set (review F8).
SECRET_FIELDS = frozenset({
    "apikey",
    "systemkey",
    "authorization",
    "accesstoken",
    "refreshtoken",
    "token",
    "secret",
    "password",
    "xsystemkey",
    "clientsecret",
    "clientid",
})
TOKEN_LITERAL_KEYS = ("access_token", "refresh_token", "system_key", "api_key", "client_secret")
STORED_TOKEN_KEYS = (
    "access_token",
    "token_type",
    "refresh_token",
    "expires_in",
    "system",
    "scope",
    "account_id",
    "user_id",
    "obtained_at",
    "expires_at",
)

NOTE_FIELDS = frozenset({"personId", "subject", "body", "isHtml"})
PERSON_FIELDS = frozenset({
    "firstName", "lastName", "name", "emails", "phones", "addresses", "background", "price",
})
EMAIL_FIELDS = frozenset({"value", "type", "isPrimary", "status"})
PHONE_FIELDS = frozenset({"value", "type", "isPrimary", "status"})
ADDRESS_FIELDS = frozenset({"type", "street", "city", "state", "code", "country"})
CREDENTIAL_BASENAMES = frozenset({
    "credentials.json", "token.json", "pending.json", ".env",
})


def _out(obj, code=0, literals=()):
    print(json.dumps(_redact(obj, _literals(literals)), ensure_ascii=True))
    raise SystemExit(code)


def _literals(extra):
    found = []
    key = os.environ.get("ADVISORREACH_API_KEY") or ""
    if len(key) >= 16:
        found.append(key)
    for literal in extra:
        if isinstance(literal, str) and len(literal) >= 16 and literal not in found:
            found.append(literal)
    return found


def _secret_field(name):
    folded = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return folded in SECRET_FIELDS


def _redact(value, literals):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _secret_field(key) else _redact(item, literals)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, literals) for item in value]
    if isinstance(value, str):
        for literal in literals:
            value = value.replace(literal, "[REDACTED]")
        return value
    return value


def _token_literals(token):
    if not isinstance(token, dict):
        return ()
    return tuple(token.get(key) for key in TOKEN_LITERAL_KEYS if isinstance(token.get(key), str))


def _home_dir():
    return os.path.join(os.environ.get("HERMES_HOME") or "/opt/data", "fub")


def _is_private(info):
    return info.st_uid == os.geteuid() and (stat.S_IMODE(info.st_mode) & 0o077) == 0


def _storage_dir():
    """Return the credential directory. Pre-existing loose or foreign dirs are refused.

    A directory this process just created is tightened to 0700 (umask can widen mkdir).
    A directory that already failed the private check is not chmod'd into compliance.
    """
    directory = _home_dir()
    if os.path.lexists(directory) and os.path.islink(directory):
        _out({"ok": False, "error": "credential directory may not be a link"}, 1)
    created = False
    if not os.path.isdir(directory):
        if os.path.lexists(directory):
            _out({"ok": False, "error": "credential directory is unavailable"}, 1)
        try:
            os.mkdir(directory, 0o700)
            created = True
        except FileExistsError:
            created = False
        except OSError:
            _out({"ok": False, "error": "credential directory is unavailable"}, 1)
    try:
        info = os.lstat(directory)
    except OSError:
        _out({"ok": False, "error": "credential directory is unavailable"}, 1)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _out({"ok": False, "error": "credential directory may not be a link"}, 1)
    if created:
        try:
            os.chmod(directory, 0o700)
            info = os.lstat(directory)
        except OSError:
            _out({"ok": False, "error": "credential directory is unavailable"}, 1)
    if not _is_private(info):
        _out({"ok": False, "error": "credential directory is not private"}, 1)
    return directory


def _store_path(name):
    return os.path.join(_storage_dir(), name)


def _read_store(name):
    path = os.path.join(_home_dir(), name)
    if os.path.lexists(path) and os.path.islink(path):
        _out({"ok": False, "error": "credential storage may not be a link"}, 1)
    if not os.path.exists(path):
        # Still fail closed when the directory itself is loose, even with no file yet.
        if os.path.isdir(_home_dir()) or os.path.lexists(_home_dir()):
            _storage_dir()
        return None
    _storage_dir()
    try:
        info = os.lstat(path)
    except OSError:
        _out({"ok": False, "error": "credential storage is unreadable"}, 1)
    if not stat.S_ISREG(info.st_mode) or not _is_private(info):
        _out({"ok": False, "error": "credential storage is not private"}, 1)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        _out({"ok": False, "error": "credential storage is unreadable"}, 1)
    try:
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError:
        _out({"ok": False, "error": "credential storage is unreadable"}, 1)
    if len(raw) > MAX_BYTES:
        _out({"ok": False, "error": "credential storage exceeds 1 MiB"}, 1)
    try:
        value = _strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        _out({"ok": False, "error": "credential storage is corrupt"}, 1)
    if not isinstance(value, dict):
        _out({"ok": False, "error": "credential storage is corrupt"}, 1)
    return value


def _write_store(name, data):
    directory = _storage_dir()
    path = os.path.join(directory, name)
    if os.path.lexists(path) and os.path.islink(path):
        _out({"ok": False, "error": "credential storage may not be a link"}, 1)
    temporary = path + ".tmp"
    if os.path.lexists(temporary):
        if os.path.islink(temporary):
            _out({"ok": False, "error": "credential storage may not be a link"}, 1)
        try:
            os.unlink(temporary)
        except OSError:
            _out({"ok": False, "error": "credential storage could not be written"}, 1)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(temporary, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        _out({"ok": False, "error": "credential storage could not be written"}, 1)
    try:
        info = os.lstat(path)
    except OSError:
        _out({"ok": False, "error": "credential storage is not private"}, 1)
    if not stat.S_ISREG(info.st_mode) or not _is_private(info):
        try:
            os.unlink(path)
        except OSError:
            pass
        _out({"ok": False, "error": "credential storage is not private"}, 1)


def _remove_store(name):
    directory = _home_dir()
    path = os.path.join(directory, name)
    if not os.path.lexists(path):
        return
    if os.path.islink(path):
        _out({"ok": False, "error": "credential storage may not be a link"}, 1)
    try:
        info = os.lstat(path)
    except OSError:
        _out({"ok": False, "error": "credential storage could not be removed"}, 1)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        _out({"ok": False, "error": "credential storage could not be removed"}, 1)
    try:
        os.unlink(path)
    except OSError:
        _out({"ok": False, "error": "credential storage could not be removed"}, 1)


def _reject_constant(_value):
    raise ValueError("non-finite")


def _within_depth(value, limit, level=0):
    if level > limit:
        return False
    if isinstance(value, dict):
        return all(_within_depth(item, limit, level + 1) for item in value.values())
    if isinstance(value, list):
        return all(_within_depth(item, limit, level + 1) for item in value)
    return True


def _strict_json(raw):
    try:
        value = json.loads(raw, parse_constant=_reject_constant)
    except RecursionError as error:
        raise ValueError("too deep") from error
    if not _within_depth(value, MAX_DEPTH):
        raise ValueError("too deep")
    return value


def _header_value(value, limit):
    """Printable ASCII header text. Spaces are allowed; CR/LF and padding are not."""
    if not isinstance(value, str) or not value or len(value) > limit or value != value.strip():
        return False
    return all(32 <= ord(ch) < 127 for ch in value)


def _opaque(value, limit):
    """A token or OAuth state: header-safe and free of spaces."""
    return _header_value(value, limit) and all(ord(ch) > 32 for ch in value)


def _summary(token):
    return {
        "connected": True,
        "account_id": token.get("account_id"),
        "user_id": token.get("user_id"),
        "system": token.get("system"),
        "scope": token.get("scope"),
        "expires_at": token.get("expires_at"),
    }


def _save_token(raw, previous=None):
    if not isinstance(raw, dict):
        _out({"ok": False, "error": "Follow Up Boss token is invalid"}, 1)
    access = raw.get("access_token")
    refresh = raw.get("refresh_token")
    # The mount returns FUB's token JSON, which has no system name. Keep a name we
    # already stored when a refresh omits it. Never invent one.
    if raw.get("system") is not None:
        system = raw.get("system")
    elif isinstance(previous, dict):
        system = previous.get("system")
    else:
        system = None
    expires_in = raw.get("expires_in")
    if not _opaque(access, 4096) or not _opaque(refresh, 4096):
        _out({"ok": False, "error": "Follow Up Boss token is invalid"}, 1)
    if system is not None and not _header_value(system, 128):
        _out({"ok": False, "error": "Follow Up Boss token is invalid"}, 1)
    if type(expires_in) is not int or isinstance(expires_in, bool) or expires_in < 1 or expires_in > 10 * 365 * 24 * 3600:
        _out({"ok": False, "error": "Follow Up Boss token is invalid"}, 1)
    token = {
        "access_token": access,
        "token_type": "Bearer",
        "refresh_token": refresh,
        "expires_in": expires_in,
    }
    if system is not None:
        token["system"] = system
    for key in ("scope", "account_id", "user_id"):
        if raw.get(key) is None:
            continue
        if not _header_value(raw.get(key), 1024):
            _out({"ok": False, "error": "Follow Up Boss token is invalid"}, 1)
        token[key] = raw[key]
    token["obtained_at"] = int(time.time())
    token["expires_at"] = token["obtained_at"] + expires_in
    stored = {key: token[key] for key in STORED_TOKEN_KEYS if key in token}
    _write_store("token.json", stored)
    return stored


def _usable_token(token):
    if not isinstance(token, dict):
        return False
    if not _opaque(token.get("access_token"), 4096):
        return False
    if not _opaque(token.get("refresh_token"), 4096):
        return False
    if token.get("system") is not None and not _header_value(token.get("system"), 128):
        return False
    expires_at = token.get("expires_at")
    return type(expires_at) is int and not isinstance(expires_at, bool)


def _loopback_origin(url):
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.hostname
    if parts.scheme != "http" or host not in ("127.0.0.1", "localhost"):
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/") or not parts.port:
        return None
    return "http://%s:%s" % (host, parts.port)


def _base_url(url, loopback_only):
    raw = url.strip()
    if loopback_only:
        return _loopback_origin(raw)
    parts = urllib.parse.urlsplit(raw)
    if parts.username or parts.password or parts.query or parts.fragment or not parts.hostname:
        return None
    loopback = parts.hostname in ("127.0.0.1", "localhost") and bool(parts.port)
    if parts.scheme == "https":
        return raw.rstrip("/")
    if parts.scheme == "http" and loopback:
        return raw.rstrip("/")
    return None


def _fub_origin():
    override = os.environ.get("FUB_API_BASE", "")
    if not override.strip():
        return "https://" + FUB_HOST
    origin = _loopback_origin(override)
    if origin is None:
        _out({
            "ok": False,
            "error": "FUB API host is fixed; FUB_API_BASE is refused unless it is an http loopback test origin",
        }, 1)
    return origin


def _exchange(method, url, headers, body=None):
    """One HTTP request. Does not follow redirects. Returns (status, body, headers)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise _PreTransport()
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    payload = None
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    hdrs.update(headers)
    if body is not None:
        try:
            payload = json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise _PreTransport() from error
        hdrs["Content-Type"] = "application/json"
    if len(path) > 4096:
        raise _PreTransport()
    connection = None
    try:
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                parts.hostname,
                parts.port or 443,
                timeout=TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            )
        else:
            connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=TIMEOUT_SECONDS)
        connection.request(method, path, body=payload, headers=hdrs)
        response = connection.getresponse()
        data = response.read(MAX_BYTES + 1)
        status = response.status
        got = {key.lower(): value for key, value in response.getheaders()}
    except http.client.InvalidURL as error:
        raise _PreTransport() from error
    except (OSError, TimeoutError, http.client.HTTPException, ValueError) as error:
        raise _UnknownTransport() from error
    finally:
        if connection is not None:
            try:
                connection.close()
            except (OSError, http.client.HTTPException):
                pass
    return status, data, got


class _PreTransport(Exception):
    pass


class _UnknownTransport(Exception):
    pass


def _advisorreach(method, path, body=None, literals=()):
    base = os.environ.get("ADVISORREACH_API_URL", "")
    key = os.environ.get("ADVISORREACH_API_KEY", "")
    if not base.strip() or not key:
        _out({"ok": False, "error": "ADVISORREACH_API_URL / ADVISORREACH_API_KEY are not set"}, 1, literals)
    origin = _base_url(base, loopback_only=False)
    if origin is None or not path.startswith("/"):
        _out({"ok": False, "error": "ADVISORREACH_API_URL is not a usable https origin"}, 1, literals)
    try:
        status, data, _headers = _exchange(
            method, origin + path, {"Authorization": "Bearer " + key}, body,
        )
    except _PreTransport:
        _out({"ok": False, "error": "could not call the AdvisorReach API"}, 1, literals)
    except _UnknownTransport:
        _out({"ok": False, "error": "could not reach the AdvisorReach API"}, 1, literals)
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        text = ""
    return status, text


def _mount_json(status, text, literals=()):
    if len(text.encode("utf-8")) > MAX_BYTES:
        _out({"ok": False, "status": status, "error": "AdvisorReach API response exceeds 1 MiB"}, 1, literals)
    try:
        value = _strict_json(text)
    except (UnicodeError, ValueError):
        _out({"ok": False, "status": status, "error": "AdvisorReach API returned an unreadable response"}, 1, literals)
    if not isinstance(value, dict):
        _out({"ok": False, "status": status, "error": "AdvisorReach API returned an unreadable response"}, 1, literals)
    return value


def cmd_connect(_args):
    status, text = _advisorreach("POST", MOUNT_PREFIX + "/connect")
    if status != 200:
        _out({"ok": False, "status": status, "error": "AdvisorReach API returned HTTP %s" % status}, 1)
    data = _mount_json(status, text)
    connect_url = data.get("connect_url")
    state = data.get("state")
    expires = data.get("expires_in_seconds")
    if not _opaque(state, 256) or type(expires) is not int or expires < 1:
        _out({"ok": False, "error": "AdvisorReach API returned an invalid connect link"}, 1)
    parts = urllib.parse.urlsplit(connect_url if isinstance(connect_url, str) else "")
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        _out({"ok": False, "error": "AdvisorReach API returned an invalid connect link"}, 1)
    _write_store("pending.json", {"state": state, "created_at": int(time.time())})
    _out({"ok": True, "connect_url": connect_url, "expires_in_seconds": expires})


def _try_claim(pending):
    state = pending.get("state") if isinstance(pending, dict) else None
    if not _opaque(state, 256):
        _remove_store("pending.json")
        return "expired", (None, "pending Follow Up Boss sign-in is invalid")
    status, text = _advisorreach("POST", MOUNT_PREFIX + "/claim", {"state": state})
    if status == 409:
        return "waiting", (status, "the user has not finished signing in yet")
    if status in (404, 410):
        _remove_store("pending.json")
        return "expired", (status, "the Follow Up Boss sign-in link expired")
    if status != 200:
        return "expired", (status, "AdvisorReach API returned HTTP %s" % status)
    token = _save_token(_mount_json(status, text))
    _remove_store("pending.json")
    return "claimed", token


def cmd_claim(_args):
    pending = _read_store("pending.json")
    if pending is None:
        _out({"ok": False, "error": "no pending Follow Up Boss connection; run connect first"}, 1)
    outcome, result = _try_claim(pending)
    if outcome == "waiting":
        _status, err = result
        _out({"ok": False, "pending": True, "error": err}, 2)
    if outcome == "expired":
        status, err = result
        body = {"ok": False, "error": err}
        if status is not None:
            body["status"] = status
        _out(body, 1)
    _out({"ok": True, **_summary(result)}, literals=_token_literals(result))


def cmd_status(_args):
    token = _read_store("token.json")
    pending = _read_store("pending.json")
    if token is not None and not _usable_token(token):
        _out({"ok": False, "error": "credential storage is corrupt"}, 1, _token_literals(token))
    if token is None and pending is not None:
        outcome, result = _try_claim(pending)
        if outcome == "claimed":
            _out({**_summary(result), "just_connected": True}, literals=_token_literals(result))
        if outcome == "waiting":
            _out({"connected": False, "pending": True, "waiting_for_user": True})
        _status, err = result
        _out({"connected": False, "pending": False, "error": err})
    if token is None:
        _out({"connected": False, "pending": pending is not None})
    _out({
        **_summary(token),
        "access_token_expired": time.time() >= token["expires_at"],
        "pending": pending is not None,
    }, literals=_token_literals(token))


def _refresh(token):
    status, text = _advisorreach(
        "POST",
        MOUNT_PREFIX + "/refresh",
        {"refresh_token": token["refresh_token"]},
        literals=_token_literals(token),
    )
    if status != 200:
        _out({
            "ok": False,
            "status": status,
            "error": "could not refresh the Follow Up Boss token",
            "reconnect": status == 409,
        }, 1, _token_literals(token))
    return _save_token(_mount_json(status, text, _token_literals(token)), previous=token)


def _valid_token(force_refresh=False):
    token = _read_store("token.json")
    if token is not None and not _usable_token(token):
        _out({"ok": False, "error": "credential storage is corrupt"}, 1, _token_literals(token))
    if token is None:
        pending = _read_store("pending.json")
        if pending is not None:
            outcome, result = _try_claim(pending)
            if outcome == "claimed":
                token = result
        if token is None:
            _out({"ok": False, "connected": False, "error": "Follow Up Boss is not connected; run connect"}, 1)
    if force_refresh or time.time() >= token["expires_at"] - REFRESH_MARGIN_SECONDS:
        token = _refresh(token)
    return token


def _relative_fub_path(url):
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.username or parts.password or parts.hostname != FUB_HOST or parts.port not in (None, 443):
        return None
    if parts.path == FUB_PREFIX:
        relative = "/"
    elif parts.path.startswith(FUB_PREFIX + "/"):
        relative = parts.path[len(FUB_PREFIX):]
    else:
        return None
    if parts.query:
        relative += "?" + parts.query
    if parts.fragment:
        return None
    return relative


def _rewrite_next_links(value):
    if isinstance(value, dict):
        rewritten = {}
        for key, item in value.items():
            if key == "nextLink" and isinstance(item, str):
                relative = _relative_fub_path(item)
                rewritten[key] = relative if relative is not None else _rewrite_next_links(item)
            else:
                rewritten[key] = _rewrite_next_links(item)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_next_links(item) for item in value]
    return value


def _normalize_path(path):
    if not isinstance(path, str) or not path or path.startswith("//"):
        _out({"ok": False, "error": "path must be a relative API path"}, 1)
    if path.startswith("https://") or path.startswith("http://"):
        relative = _relative_fub_path(path)
        if relative is None:
            _out({"ok": False, "error": "path must be a relative API path"}, 1)
        path = relative
    if not path.startswith("/") or path.startswith("//") or "#" in path or "\\" in path:
        _out({"ok": False, "error": "path must be a relative API path"}, 1)
    if len(path) > 2048 or any(ord(ch) <= 32 or ord(ch) == 127 for ch in path):
        _out({"ok": False, "error": "path contains an invalid character"}, 1)
    resource, marker, query = path.partition("?")
    try:
        decoded = urllib.parse.unquote(resource)
        decoded_query = urllib.parse.unquote(query) if marker else ""
    except UnicodeError:
        _out({"ok": False, "error": "path contains an invalid character"}, 1)
    if "%" in decoded or "\\" in decoded or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded):
        _out({"ok": False, "error": "path contains traversal or an invalid segment"}, 1)
    if any(part in ("", ".", "..") for part in decoded.split("/")[1:]):
        _out({"ok": False, "error": "path contains traversal or an invalid segment"}, 1)
    if marker and any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded_query):
        _out({"ok": False, "error": "query contains an invalid character"}, 1)
    if resource != "/" and resource.endswith("/"):
        resource = resource.rstrip("/")
        path = resource + (("?" + query) if marker else "")
    return path


def _resource(path):
    return path.split("?", 1)[0]


def _read_only():
    return os.environ.get("FUB_READ_ONLY", "") == "1"


def _write_resource_error(method, resource):
    """Code gate for writes. --confirm-write cannot unlock a path outside the allowlist."""
    if method == "GET":
        return None
    if _read_only():
        return "writes are disabled on this box"
    if method == "DELETE":
        return "DELETE is not allowed"
    if method not in ("POST", "PUT"):
        return "%s is not allowed" % method
    if method == "POST" and resource == "/notes":
        return None
    if method == "PUT" and resource.startswith("/people/"):
        person_id = resource[len("/people/"):]
        if person_id.isdigit() and person_id[0] != "0":
            return None
    return "%s %s is not on the write allowlist" % (method, resource)


def _banned_basename(name):
    if name in CREDENTIAL_BASENAMES or name.startswith(".env"):
        return True
    if name.startswith(".credentials.") or name.startswith(".token.") or name.startswith(".pending."):
        return True
    return False


def _data_file_error(path):
    if not isinstance(path, str) or not path or "\x00" in path:
        return "data file path is invalid"
    if os.path.islink(path):
        return "data file may not be a link"
    try:
        real = os.path.realpath(path)
    except OSError:
        return "could not read data file"
    base = os.path.basename(real)
    if _banned_basename(base):
        return "data file is a credential or token file"
    hermes = os.path.realpath(os.environ.get("HERMES_HOME") or "/opt/data")
    storage = os.path.realpath(_home_dir())
    if real == storage or real.startswith(storage + os.sep):
        return "data file is inside Follow Up Boss credential storage"
    if os.path.dirname(real) == hermes and (base.endswith(".json") or base.startswith(".env")):
        return "data file is a credential or token file"
    for name in ("token.json", "pending.json", "credentials.json"):
        candidate = os.path.join(_home_dir(), name)
        if not os.path.lexists(candidate):
            continue
        try:
            if os.path.samefile(path, candidate):
                return "data file is a credential or token file"
        except OSError:
            continue
    return None


def _load_data_file(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        _out({"ok": False, "error": "could not read data file"}, 1)
    try:
        with os.fdopen(fd, "rb") as handle:
            content = handle.read(MAX_BYTES + 1)
    except OSError:
        _out({"ok": False, "error": "could not read data file"}, 1)
    if len(content) > MAX_BYTES:
        _out({"ok": False, "error": "request body exceeds 1 MiB"}, 1)
    try:
        return content.decode("utf-8")
    except UnicodeError:
        _out({"ok": False, "error": "request data is not valid UTF-8"}, 1)


def _parse_body(raw):
    try:
        encoded = raw.encode("utf-8")
    except UnicodeError:
        _out({"ok": False, "error": "request data is not valid UTF-8"}, 1)
    if len(encoded) > MAX_BYTES:
        _out({"ok": False, "error": "request body exceeds 1 MiB"}, 1)
    try:
        return _strict_json(raw)
    except (TypeError, ValueError):
        _out({"ok": False, "error": "request data is not valid JSON"}, 1)


def _short_string(value, limit):
    return isinstance(value, str) and len(value) <= limit and "\x00" not in value


def _contact_list(value, fields):
    if not isinstance(value, list) or len(value) > 20:
        return False
    for item in value:
        if not isinstance(item, dict) or not item or not set(item).issubset(fields):
            return False
        for key, item_value in item.items():
            if key == "isPrimary":
                if type(item_value) is not bool:
                    return False
            elif not _short_string(item_value, 500):
                return False
    return True


def _check_note(body):
    if not isinstance(body, dict) or set(body) - NOTE_FIELDS or "personId" not in body or "body" not in body:
        return "POST /notes accepts only personId, subject, body, and isHtml"
    person_id = body.get("personId")
    if type(person_id) is not int or person_id < 1:
        return "POST /notes personId must be a positive integer"
    if not isinstance(body.get("body"), str) or not body["body"].strip() or len(body["body"]) > 20000:
        return "POST /notes body must be text"
    if "subject" in body and not _short_string(body["subject"], 500):
        return "POST /notes subject must be text"
    if "isHtml" in body and type(body["isHtml"]) is not bool:
        return "POST /notes isHtml must be a boolean"
    return None


def _check_person(body):
    if not isinstance(body, dict) or not body or set(body) - PERSON_FIELDS:
        refused = sorted(set(body) - PERSON_FIELDS) if isinstance(body, dict) else []
        if refused:
            return "PUT /people/{id} refuses fields: " + ", ".join(refused)
        return "PUT /people/{id} accepts only name, email, phone, address, background, and price fields"
    for key in ("firstName", "lastName", "name"):
        if key in body and not _short_string(body[key], 500):
            return "PUT /people/{id} %s must be text" % key
    if "background" in body and not _short_string(body["background"], 20000):
        return "PUT /people/{id} background must be text"
    if "price" in body:
        price = body["price"]
        if type(price) is bool or not isinstance(price, (int, float)) or (
            isinstance(price, float) and not math.isfinite(price)
        ):
            return "PUT /people/{id} price must be a number"
    if "emails" in body and not _contact_list(body["emails"], EMAIL_FIELDS):
        return "PUT /people/{id} emails must be a list of value/type objects"
    if "phones" in body and not _contact_list(body["phones"], PHONE_FIELDS):
        return "PUT /people/{id} phones must be a list of value/type objects"
    if "addresses" in body and not _contact_list(body["addresses"], ADDRESS_FIELDS):
        return "PUT /people/{id} addresses must be a list of address objects"
    return None


def _rate_limit(headers):
    extra = {}
    parsed = {}
    for header, key in (
        ("x-ratelimit-limit", "limit"),
        ("x-ratelimit-remaining", "remaining"),
        ("x-ratelimit-window", "window"),
        ("x-ratelimit-context", "context"),
    ):
        if header not in headers or headers[header] == "":
            continue
        value = headers[header]
        if key != "context":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        parsed[key] = value
    if parsed:
        extra["rate_limit"] = parsed
    if headers.get("retry-after"):
        raw = headers["retry-after"].strip()
        try:
            extra["retry_after"] = int(raw)
        except ValueError:
            extra["retry_after"] = raw
    return extra


def _fub_call(method, path, body, token):
    origin = _fub_origin()
    url = origin + FUB_PREFIX + path
    headers = {"Authorization": "Bearer " + token["access_token"]}
    if token.get("system"):
        headers["X-System"] = token["system"]
    try:
        return _exchange(method, url, headers, body)
    except _PreTransport:
        _out({
            "ok": False,
            "error": "path was rejected before the request was sent",
        }, 1, _token_literals(token))
    except _UnknownTransport:
        result = {"ok": False, "error": "transport failed"}
        if method != "GET":
            result["outcome_unknown"] = True
            result["reconciliation_required"] = True
        _out(result, 1, _token_literals(token))


def _emit_fub(method, status, data, headers, token):
    literals = _token_literals(token)
    if len(data) > MAX_BYTES:
        result = {"ok": False, "status": status, "error": "response exceeds 1 MiB"}
        if method != "GET":
            result["outcome_unknown"] = True
            result["reconciliation_required"] = True
        _out(result, 1, literals)
    try:
        parsed = _strict_json(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        parsed = data.decode("utf-8", "replace")[:4000]
    if 300 <= status < 400:
        result = {"ok": False, "status": status, "error": "redirect refused"}
        if method != "GET":
            result["outcome_unknown"] = True
            result["reconciliation_required"] = True
        _out(result, 1, literals)
    body = _rewrite_next_links(parsed)
    result = {"status": status, "body": body}
    result.update(_rate_limit(headers))
    if status >= 400:
        result["ok"] = False
        result["error"] = "Follow Up Boss returned HTTP %s" % status
        # 429 was not processed. Other 4xx were refused. 5xx may have landed.
        if method != "GET" and status >= 500:
            result["outcome_unknown"] = True
            result["reconciliation_required"] = True
    _out(result, 0 if status < 400 else 1, literals)


def _body_has_secret(raw, token):
    if not isinstance(raw, str) or not isinstance(token, dict):
        return False
    for literal in _token_literals(token):
        if isinstance(literal, str) and len(literal) >= 16 and literal in raw:
            return True
    return False


def cmd_api(args):
    # Refuse a redirected host before any mount or Follow Up Boss call.
    _fub_origin()
    path = _normalize_path(args.path)
    method = args.method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        _out({"ok": False, "error": "method must be GET, POST, PUT, PATCH, or DELETE"}, 1)
    if args.data is not None and args.data_file is not None:
        _out({"ok": False, "error": "use only one data source"}, 1)
    if method == "GET" and (args.data is not None or args.data_file is not None):
        _out({"ok": False, "error": "GET cannot include a body"}, 1)
    if method != "GET" and "?" in path:
        _out({"ok": False, "error": "writes do not accept a query string"}, 1)
    if args.data_file is not None:
        refusal = _data_file_error(args.data_file)
        if refusal:
            _out({"ok": False, "error": refusal}, 1)
    resource = _resource(path)
    if method != "GET":
        blocked = _write_resource_error(method, resource)
        if blocked:
            _out({"ok": False, "error": blocked}, 1)
        if not args.confirm_write:
            _out({
                "ok": False,
                "error": "write requires a yes from the user; say exactly what will change, wait for yes, then pass --confirm-write",
            }, 1)
    raw = args.data
    if args.data_file is not None:
        raw = _load_data_file(args.data_file)
    body = None if raw is None else _parse_body(raw)
    if method != "GET":
        if method == "POST":
            field_error = _check_note(body)
        else:
            field_error = _check_person(body)
        if field_error:
            _out({"ok": False, "error": field_error}, 1)
    stored = _read_store("token.json")
    if _body_has_secret(raw, stored):
        _out({"ok": False, "error": "data file is a credential or token file"}, 1, _token_literals(stored))
    token = _valid_token()
    if _body_has_secret(raw, token):
        _out({"ok": False, "error": "data file is a credential or token file"}, 1, _token_literals(token))

    def call(current):
        return _fub_call(method, path, body, current)

    status, data, headers = call(token)
    if status == 401:
        token = _valid_token(force_refresh=True)
        status, data, headers = call(token)
    _emit_fub(method, status, data, headers, token)


def _token_for_revoke():
    """Return the private token when we can revoke it. Do not read a loose file."""
    path = os.path.join(_home_dir(), "token.json")
    if not os.path.lexists(path):
        return None
    if os.path.islink(path):
        _out({"ok": False, "error": "credential storage may not be a link"}, 1)
    try:
        info = os.lstat(path)
    except OSError:
        _out({"ok": False, "error": "credential storage is unreadable"}, 1)
    if not stat.S_ISREG(info.st_mode) or not _is_private(info):
        return None
    token = _read_store("token.json")
    if not isinstance(token, dict) or not _opaque(token.get("access_token"), 4096):
        return None
    return token


def cmd_disconnect(_args):
    token = _token_for_revoke()
    revoked = False
    if token is not None:
        literals = _token_literals(token)
        status, _text = _advisorreach(
            "POST", MOUNT_PREFIX + "/revoke", {"access_token": token["access_token"]}, literals,
        )
        if status == 200:
            revoked = True
        elif status != 409:
            _out({
                "ok": False,
                "connected": True,
                "status": status,
                "error": "could not revoke the Follow Up Boss token",
            }, 1, literals)
    _remove_store("token.json")
    _remove_store("pending.json")
    _out({"ok": True, "connected": False, "revoked": revoked}, literals=_token_literals(token))


class JsonParser(argparse.ArgumentParser):
    def error(self, _message):
        _out({"ok": False, "error": "invalid command arguments"}, 2)


def main():
    parser = JsonParser(prog="fub.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connect", help="get a sign-in link to text the user").set_defaults(fn=cmd_connect)
    sub.add_parser("claim", help="after the user signed in: save the token on this box").set_defaults(fn=cmd_claim)
    sub.add_parser("status", help="is Follow Up Boss connected, and until when").set_defaults(fn=cmd_status)
    api = sub.add_parser("api", help="call the Follow Up Boss API with the saved token")
    api.add_argument("method", help="GET, POST, PUT, PATCH, or DELETE")
    api.add_argument("path", help="relative API path, or an https://api.followupboss.com/v1 nextLink")
    api.add_argument("--data", help="JSON request body")
    api.add_argument("--data-file", help="JSON file outside credential storage")
    api.add_argument("--confirm-write", action="store_true", help="required for an allowlisted write after the user says yes")
    api.set_defaults(fn=cmd_api)
    sub.add_parser("disconnect", help="revoke the token, then delete it from this box").set_defaults(fn=cmd_disconnect)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
