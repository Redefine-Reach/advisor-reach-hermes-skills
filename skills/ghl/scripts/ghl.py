#!/usr/bin/env python3
"""GoHighLevel (GHL) for this box: connect, claim, status, api, disconnect.

The token lives ONLY in /opt/data/ghl/token.json ($HERMES_HOME/ghl) (mode 0600, written atomically) and is
never printed: `api` injects it into the GHL request itself. The AdvisorReach API's GHL Mount
(/crm/v1) holds the app's Client Secret; this script never sees it. Every command prints one
JSON object on stdout.

Exit codes: 0 ok; 1 error (read "error"); 2 `claim` before the user finished signing in.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

GHL_API_BASE = os.environ.get("GHL_API_BASE", "https://services.leadconnectorhq.com")
GHL_API_VERSION = "2021-07-28"
# GHL sits behind Cloudflare; always send an explicit User-Agent (circle-member-token's rule).
USER_AGENT = "advisorreach-box/1.0"
REFRESH_MARGIN_SECONDS = 300
TIMEOUT_SECONDS = 30


def _dir() -> str:
    # HERMES_HOME is not in the sandbox env passthrough (hermes_boot_config.py); /opt/data is its
    # value on every box (charts/sms-box statefulset.yaml), so fall back to it.
    d = os.path.join(os.environ.get("HERMES_HOME") or "/opt/data", "ghl")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _token_path() -> str:
    return os.path.join(_dir(), "token.json")


def _pending_path() -> str:
    return os.path.join(_dir(), "pending.json")


def _read(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _write(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _out(obj: dict, code: int = 0):
    print(json.dumps(obj))
    sys.exit(code)


def _request(method: str, url: str, headers: dict, body=None):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json", **headers}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, TimeoutError) as e:
        _out({"ok": False, "error": f"could not reach {url.split('?')[0]}: {e}"}, 1)


def _advisorreach(method: str, path: str, body=None):
    base = os.environ.get("ADVISORREACH_API_URL", "").rstrip("/")
    key = os.environ.get("ADVISORREACH_API_KEY", "")
    if not base or not key:
        _out({"ok": False, "error": "ADVISORREACH_API_URL / ADVISORREACH_API_KEY are not set"}, 1)
    return _request(method, base + path, {"Authorization": "Bearer " + key}, body)


def _save_token(token: dict) -> dict:
    token["obtained_at"] = int(time.time())
    token["expires_at"] = token["obtained_at"] + int(token.get("expires_in", 0))
    _write(_token_path(), token)
    return token


def _summary(t: dict) -> dict:
    return {
        "connected": True,
        "location_id": t.get("locationId"),
        "company_id": t.get("companyId"),
        "user_type": t.get("userType"),
        "scope": t.get("scope"),
        "expires_at": t.get("expires_at"),
    }


def cmd_connect(_args) -> None:
    status, text = _advisorreach("POST", "/crm/v1/connect")
    if status != 200:
        _out({"ok": False, "status": status, "error": text[:500]}, 1)
    d = json.loads(text)
    _write(_pending_path(), {"state": d["state"], "created_at": int(time.time())})
    _out({"ok": True, "connect_url": d["connect_url"], "expires_in_seconds": d["expires_in_seconds"]})


def _try_claim(pending: dict):
    """Ask the AdvisorReach API to claim a pending GoHighLevel sign-in.

    Returns ("claimed", token), ("waiting", status_and_text) or ("expired", status_and_text).
    Removes pending.json on 200/404/410 (a final outcome); leaves it alone on 409 (still waiting).
    """
    status, text = _advisorreach("POST", "/crm/v1/claim", {"state": pending["state"]})
    if status == 409:
        return "waiting", (status, "the user has not finished signing in yet")
    if status in (404, 410):
        _remove(_pending_path())
        return "expired", (status, text[:500])
    if status != 200:
        return "expired", (status, text[:500])
    token = _save_token(json.loads(text))
    _remove(_pending_path())
    return "claimed", token


def cmd_claim(_args) -> None:
    pending = _read(_pending_path())
    if pending is None:
        _out({"ok": False, "error": "no pending GoHighLevel connection; run connect first"}, 1)
    outcome, result = _try_claim(pending)
    if outcome == "waiting":
        _, err = result
        _out({"ok": False, "pending": True, "error": err}, 2)
    if outcome == "expired":
        status, err = result
        _out({"ok": False, "status": status, "error": err}, 1)
    _out({"ok": True, **_summary(result)})


def cmd_status(_args) -> None:
    t = _read(_token_path())
    pending = _read(_pending_path())
    if t is None and pending is not None:
        outcome, result = _try_claim(pending)
        if outcome == "claimed":
            _out({**_summary(result), "just_connected": True})
        if outcome == "waiting":
            _out({"connected": False, "pending": True, "waiting_for_user": True})
        _, err = result
        _out({"connected": False, "pending": False, "error": err})
    if t is None:
        _out({"connected": False, "pending": pending is not None})
    _out({**_summary(t), "access_token_expired": time.time() >= t["expires_at"], "pending": pending is not None})


def _refresh(t: dict) -> dict:
    status, text = _advisorreach("POST", "/crm/v1/refresh",
                                 {"refresh_token": t["refresh_token"], "user_type": t.get("userType", "Location")})
    if status != 200:
        _out({"ok": False, "status": status, "error": text[:500], "reconnect": status == 409}, 1)
    return _save_token(json.loads(text))


def _valid_token(force_refresh: bool = False) -> dict:
    t = _read(_token_path())
    if t is None:
        pending = _read(_pending_path())
        if pending is not None:
            outcome, result = _try_claim(pending)
            if outcome == "claimed":
                t = result
        if t is None:
            _out({"ok": False, "connected": False, "error": "GoHighLevel is not connected; run connect"}, 1)
    if force_refresh or time.time() >= t["expires_at"] - REFRESH_MARGIN_SECONDS:
        t = _refresh(t)
    return t


def cmd_api(args) -> None:
    if not args.path.startswith("/"):
        _out({"ok": False, "error": "path must start with / (e.g. /contacts/?locationId={locationId})"}, 1)
    if args.data is not None:
        try:
            json.loads(args.data)
        except ValueError as e:
            _out({"ok": False, "error": f"--data is not valid JSON: {e}"}, 1)
    t = _valid_token()

    def call(tok: dict):
        location = tok.get("locationId") or ""
        path = args.path.replace("{locationId}", location)
        body = None if args.data is None else json.loads(args.data.replace("{locationId}", location))
        return _request(args.method.upper(), GHL_API_BASE + path,
                        {"Authorization": "Bearer " + tok["access_token"], "Version": GHL_API_VERSION}, body)

    status, text = call(t)
    if status == 401:
        status, text = call(_valid_token(force_refresh=True))
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = text[:2000]
    _out({"status": status, "body": parsed}, 0 if status < 400 else 1)


def cmd_disconnect(_args) -> None:
    _remove(_token_path())
    _remove(_pending_path())
    _out({"ok": True, "connected": False})


def main() -> None:
    p = argparse.ArgumentParser(prog="ghl.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("connect", help="get a sign-in link to text the user").set_defaults(fn=cmd_connect)
    sub.add_parser("claim", help="after the user signed in: save the token on this box").set_defaults(fn=cmd_claim)
    sub.add_parser("status", help="is GoHighLevel connected, for which location, until when").set_defaults(fn=cmd_status)
    api = sub.add_parser("api", help="call the GoHighLevel API with the saved token")
    api.add_argument("method", help="GET, POST, PUT, PATCH or DELETE")
    api.add_argument("path", help="API path; {locationId} is replaced with the connected location")
    api.add_argument("--data", help="JSON request body")
    api.set_defaults(fn=cmd_api)
    sub.add_parser("disconnect", help="delete the saved token from this box").set_defaults(fn=cmd_disconnect)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
