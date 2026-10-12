#!/usr/bin/env python3
"""git credential helper for the ARIN Lane (skills/advisorreach-site/SKILL.md).

git runs this for every HTTPS operation on github.com. It asks the WTTC workspace's GitHub OAuth Client
(`Component Installs/OAuth/GitHub`, signed in as the team machine user `ar-team-arin`) for a current
token through the hosted OmegaAI MCP server, as this box's service account (MCP_QUERY_OMEGA_API_KEY,
the key the query-omega MCP entry and feeder-markets' cas_pull.py already use). Nothing is stored.
This is OmegaAI's `Public/OAuth/devcontainer-git` helper for a box with no `qo`: same OAuth Client,
same `get-token`, reached over MCP instead of the CLI.

  git -c credential.https://github.com.helper='!python3 /opt/data/skills/advisorreach-site/scripts/git-credential-wttc-oauth.py' ...

Only `get` answers (username=x-access-token, password=<token>, to git on stdout). Never run it yourself:
its output is the token. A failure prints `git-credential-wttc-oauth: <error type>` on stderr, exit 1.
"""
import json
import os
import sys
import urllib.error
import urllib.request

MCP_URL = os.environ.get("OMEGA_MCP_URL", "https://mcp.cloud.queryomega.com/mcp")
WTTC_APP_ID = "5b4edd7a-f920-450b-8732-399095154c83"   # Welcome To The Cause, team ARIN's workspace
CLIENT_PAGE = "Component Installs/OAuth/GitHub"
TIMEOUT_SECONDS = 30


def fail(kind):
    sys.stderr.write("git-credential-wttc-oauth: %s\n" % kind)
    sys.exit(1)


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
            fail("omega/mcp/HTTP%d" % e.code)
        except (urllib.error.URLError, TimeoutError, OSError):
            fail("omega/mcp/Unreachable")

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
            fail("omega/mcp/NoResponse")
        return json.loads(text)


def error_type(error):
    """The OAuth Client's typed error (oauth/NotConnected, oauth/TokenExpired, …) or the raw first line."""
    first = str(error).split("\n")[0]
    try:
        return json.loads(first).get("type") or first[:120]
    except (ValueError, AttributeError):
        return first[:120]


def find_token(value):
    if isinstance(value, dict):
        if isinstance(value.get("access-token"), str) and value["access-token"]:
            return value["access-token"]
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            token = find_token(item)
            if token:
                return token
    return None


def get_token():
    key = os.environ.get("MCP_QUERY_OMEGA_API_KEY", "")
    if not key:
        fail("omega/mcp/NoKey")
    mcp = Mcp(key)
    init = mcp.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "git-credential-wttc-oauth", "version": "1"}})
    if "error" in init:
        fail("omega/mcp/InitializeFailed")
    mcp.post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    msg = mcp.request("tools/call", {"name": "run", "arguments": {
        "app_id": WTTC_APP_ID, "page_path": CLIENT_PAGE, "protocol": "OAuth Client",
        "method": "get-token", "args": [{}]}})
    if "error" in msg:
        fail(error_type(msg["error"].get("message", msg["error"])))
    payload = json.loads(msg["result"]["content"][0]["text"])
    if payload.get("ok") is not True:
        fail(error_type(payload.get("error")))
    token = find_token(payload.get("data"))
    if not token:
        fail("oauth/NoToken")
    return token


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "get":
        return 0                                     # store / erase: nothing is stored
    sys.stdin.read()                                 # git's request attributes; github.com is the only host configured
    token = get_token()
    sys.stdout.write("username=x-access-token\npassword=%s\n" % token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
