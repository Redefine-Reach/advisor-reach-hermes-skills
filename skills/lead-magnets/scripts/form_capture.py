#!/usr/bin/env python3
"""This box's Form Capture install in OmegaAI, through the hosted OmegaAI MCP server.

Form Capture is an OmegaAI component (form-capture repo, library "WTTC Component Library/Form Capture
Library"). Its install at "Component Installs/Form Capture" in this box's OmegaAI workspace has a public
hook URL that a website form posts to, keeps every submission as a row of Data/Submissions, and POSTs
each submission as JSON to every matching row of Data/Webhooks (url, headers, optional form). This
script only calls the install's FormCapture methods with the box's key (MCP_QUERY_OMEGA_API_KEY), the
same MCP client as skills/feeder-markets/scripts/cas_pull.py.

  form_capture.py status
  form_capture.py add-webhook --url <https://...> [--form <form>] [--header-file <path>]
  form_capture.py list-webhooks
  form_capture.py remove-webhook (--id <id> | --form <form>)
  form_capture.py submissions [--form <form>] [--limit 20]

--header-file names a 0600 file holding one line, the secret value; it is sent as header
X-Box-Script-Secret on that webhook. Header values are never printed.
Every command prints ONE JSON line: {"ok": true, ...} (exit 0) or {"ok": false, "error": "..."} (exit 1).
Standard library only.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

MCP_URL = os.environ.get("OMEGA_MCP_URL", "https://mcp.cloud.queryomega.com/mcp")
INSTALL_PAGE = "Component Installs/Form Capture"
PROTOCOL = "FormCapture"
SECRET_HEADER = "X-Box-Script-Secret"
TIMEOUT_SECONDS = 60


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


class Mcp:
    def __init__(self, key):
        self.key, self.session, self.next_id = key, None, 1

    def post(self, body):
        headers = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "User-Agent": "advisorreach-box/1.0"}
        if self.session:
            headers["mcp-session-id"] = self.session
        req = urllib.request.Request(MCP_URL, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
                self.session = r.headers.get("mcp-session-id") or self.session
                return r.headers.get("Content-Type", ""), r.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError("OmegaAI MCP answered HTTP %d" % e.code)
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError("could not reach the OmegaAI MCP server: %s" % e)

    def request(self, method, params):
        msg_id = self.next_id
        self.next_id += 1
        ctype, text = self.post({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        if "text/event-stream" in ctype:
            for line in text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == msg_id:
                        return msg
            raise RuntimeError("no MCP response for request %d" % msg_id)
        return json.loads(text)

    def tool(self, name, arguments):
        msg = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in msg:
            raise RuntimeError("%s failed: %s" % (name, json.dumps(msg["error"])[:300]))
        result = msg["result"]
        payload = json.loads(result["content"][0]["text"])
        if result.get("isError"):
            raise RuntimeError("%s failed: %s" % (name, json.dumps(payload)[:300]))
        # Two answer shapes (seen 2026-10-12): an envelope {"ok", "data" | "error"} (`run`), or the
        # tool's data itself (`list_workspaces` answers {"workspaces", "home-app-id", ...}).
        if isinstance(payload, dict) and "ok" in payload:
            if payload.get("ok") is not True:
                raise RuntimeError("%s failed: %s" % (name, str(payload.get("error"))[:300]))
            return payload.get("data")
        return payload


def connect():
    key = os.environ.get("MCP_QUERY_OMEGA_API_KEY", "")
    if not key:
        out({"ok": False, "error": "MCP_QUERY_OMEGA_API_KEY is not set: this box is not connected to OmegaAI"}, 1)
    mcp = Mcp(key)
    init = mcp.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "lead-magnets", "version": "1"}})
    if "error" in init:
        raise RuntimeError("MCP initialize failed")
    mcp.post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    app_id = (mcp.tool("list_workspaces", {}) or {}).get("home-app-id", "")
    if not app_id:
        raise RuntimeError("this box's OmegaAI key has no home workspace")
    return mcp, app_id


def call(mcp, app_id, method, arg):
    data = mcp.tool("run", {"app_id": app_id, "page_path": INSTALL_PAGE, "protocol": PROTOCOL,
                            "method": method, "args": [arg]})
    # `run` answers its solutions as a list, either bare or (2026-10-12) as {"path", "result": [...]};
    # a FormCapture method has exactly one.
    if isinstance(data, dict) and isinstance(data.get("result"), list):
        data = data["result"]
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise RuntimeError("%s answered %s" % (method, json.dumps(data)[:200]))
    return data


def masked(webhook):
    headers = webhook.get("headers") or {}
    return {"id": webhook.get("id"), "url": webhook.get("url"), "form": webhook.get("form") or None,
            "headers": sorted(headers.keys()) if isinstance(headers, dict) else []}


def read_secret(path):
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise RuntimeError("%s must be mode 0600" % path)
    with open(path) as fh:
        value = fh.read().strip()
    if len(value) < 32:
        raise RuntimeError("%s holds fewer than 32 characters" % path)
    return value


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("add-webhook")
    p.add_argument("--url", required=True)
    p.add_argument("--form", default="")
    p.add_argument("--header-file", default="")
    sub.add_parser("list-webhooks")
    p = sub.add_parser("remove-webhook")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--form")
    p = sub.add_parser("submissions")
    p.add_argument("--form", default="")
    p.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    try:
        mcp, app_id = connect()
        if a.cmd == "status":
            data = call(mcp, app_id, "endpoint", {})
            out({"ok": True, "app_id": app_id, "page": INSTALL_PAGE, "endpoint_url": data["endpoint-url"]})
        if a.cmd == "add-webhook":
            if not a.url.startswith("https://"):
                out({"ok": False, "error": "--url must start with https://"}, 1)
            arg = {"url": a.url, "headers": {}}
            if a.form:
                arg["form"] = a.form
            if a.header_file:
                arg["headers"][SECRET_HEADER] = read_secret(a.header_file)
            data = call(mcp, app_id, "add-webhook", arg)
            out({"ok": True, "id": data["id"], "url": a.url, "form": a.form or None,
                 "headers": sorted(arg["headers"])})
        if a.cmd == "list-webhooks":
            items = call(mcp, app_id, "list-webhooks", {}).get("items") or []
            out({"ok": True, "webhooks": [masked(w) for w in items]})
        if a.cmd == "remove-webhook":
            if a.id:
                ids = [a.id]
            else:
                items = call(mcp, app_id, "list-webhooks", {}).get("items") or []
                ids = [w["id"] for w in items if (w.get("form") or "") == a.form]
            for wid in ids:
                call(mcp, app_id, "remove-webhook", {"id": wid})
            out({"ok": True, "removed": ids})
        if a.cmd == "submissions":
            arg = {"limit": a.limit}
            if a.form:
                arg["form"] = a.form
            data = call(mcp, app_id, "list-submissions", arg)
            out({"ok": True, "total": data.get("total"), "submissions": data.get("items") or []})
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        out({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
