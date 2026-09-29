#!/usr/bin/env python3
"""Hand the agent-referral pull to Cas, the OmegaAI in-app agent, and collect the CSV link.

The pull itself happens in OmegaAI: Cas installs the Redefine Reach Agent Referral Data package
in THIS box's OmegaAI workspace and runs its export script, then replies with a download link.
This script only opens her session, sends the job, and reads her reply — through the hosted
OmegaAI MCP server, authenticated with the box's key (MCP_QUERY_OMEGA_API_KEY).

  cas_pull.py start --zips "<ZIP ZIP ...>" [--max-agents 5000]
  cas_pull.py wait --session <ses_...> [--max-seconds 240]

start prints {"ok": true, "session": "ses_..."} as soon as the job is sent.
wait polls every 20 s for up to --max-seconds and prints ONE of:
  {"ok": true, "status": "done", "link": "https://...csv", "agents": N, "summary": {...}}
  {"ok": true, "status": "running", "waited_seconds": N}      -> run wait again
  {"ok": false, "status": "failed", "error": "..."}           -> tell the user
Exit 0 on ok, 1 on error. Standard library only.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

MCP_URL = os.environ.get("OMEGA_MCP_URL", "https://mcp.cloud.queryomega.com/mcp")
USER_AGENT = "advisorreach-box/1.0"
TIMEOUT_SECONDS = 120
POLL_SECONDS = 20
# referrals-csv.mjs output starts with Query ZIP; Cas's export_csv fallback (no hosting) does not.
CSV_HEADER_STARTS = ("Query ZIP,Agent,Company,DB Rank,Email,", "Agent,Company,DB Rank,Email,")
LINK_RE = re.compile(r"https?://[^\s)\]\"'<>]+\.csv")
SUMMARY_RE = re.compile(r"\{\"file\":.*\"zips\":\s*\[.*?\]\}")

JOB = (
    "Use the OmegaAI package \"Redefine Reach Agent Referral Data\" (package id "
    "d4c389e0-588e-45d9-b291-6e6a8ca37ae3): read its docs with get_package_docs and follow them "
    "exactly. Work in your own workspace. Export Homes.com real-estate agent referrals as a CSV "
    "file I can download for these ZIP codes, best first, with MAX_ROWS {max_agents}: {zips}. "
    "Do not ask me anything. Reply with the download link on its own line, then on the next line "
    "the one-line JSON summary the export script printed. If anything fails, reply with the "
    "exact error text instead."
)


class Mcp:
    def __init__(self, key):
        self.key = key
        self.session = None
        self.next_id = 1

    def _post(self, body):
        headers = {
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        }
        if self.session:
            headers["mcp-session-id"] = self.session
        req = urllib.request.Request(MCP_URL, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
                self.session = r.headers.get("mcp-session-id") or self.session
                return r.headers.get("Content-Type", ""), r.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError("OmegaAI MCP answered HTTP " + str(e.code) + ": " + e.read().decode()[:300])
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError("could not reach the OmegaAI MCP server: " + str(e))

    def request(self, method, params):
        msg_id = self.next_id
        self.next_id += 1
        ctype, text = self._post({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        if "text/event-stream" in ctype:
            for line in text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == msg_id:
                        return msg
            raise RuntimeError("no MCP response for request " + str(msg_id))
        return json.loads(text)

    def open(self):
        init = self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                           "clientInfo": {"name": "feeder-markets", "version": "1"}})
        if "error" in init:
            raise RuntimeError("MCP initialize failed: " + json.dumps(init["error"]))
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def tool(self, name, arguments):
        msg = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in msg:
            raise RuntimeError(name + " failed: " + json.dumps(msg["error"]))
        text = msg["result"]["content"][0]["text"]
        payload = json.loads(text)
        if payload.get("ok") is not True:
            raise RuntimeError(name + " failed: " + str(payload.get("error"))[:500])
        return payload["data"]


def out(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


def connect():
    key = os.environ.get("MCP_QUERY_OMEGA_API_KEY", "")
    if not key:
        out({"ok": False, "error": "MCP_QUERY_OMEGA_API_KEY is not set: this box is not connected to OmegaAI"}, 1)
    mcp = Mcp(key)
    mcp.open()
    return mcp


def start(args):
    zips = args.zips.split()
    if not zips or not all(re.fullmatch(r"\d{5}", z) for z in zips):
        out({"ok": False, "error": "--zips must be five-digit ZIP codes separated by spaces"}, 1)
    mcp = connect()
    created = mcp.tool("agent_create_session", {})
    session = created["session"]["sessionId"]
    message = JOB.format(max_agents=args.max_agents, zips=" ".join(zips))
    mcp.tool("agent_send_message", {"session_id": session, "message": message, "async": True})
    out({"ok": True, "session": session, "zips": len(zips), "max_agents": args.max_agents})


def last_message(mcp, session):
    first = mcp.tool("agent_get_messages", {"session_id": session, "skip": 0, "limit": 1})
    total = first["result"]["total"]
    if total == 0:
        return None
    page = mcp.tool("agent_get_messages", {"session_id": session, "skip": total - 1, "limit": 1})
    return page["result"]["messages"][-1]


def check_csv(link):
    req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        raise RuntimeError("the CSV link did not download: " + str(e))
    if not body.startswith(CSV_HEADER_STARTS):
        raise RuntimeError("the file at the link is not a Referral Export CSV (header: " + body[:80] + ")")
    rows = list(csv.reader(io.StringIO(body)))
    return len([r for r in rows[1:] if r])


def wait(args):
    mcp = connect()
    started = time.time()
    while True:
        msg = last_message(mcp, args.session)
        info = (msg or {}).get("info", {})
        if msg and info.get("role") == "assistant" and info.get("time", {}).get("completed"):
            finish = info.get("finish")
            text = "\n".join(p.get("text", "") for p in msg.get("parts", []) if p.get("type") == "text")
            if finish == "stop":
                links = LINK_RE.findall(text)
                if not links:
                    out({"ok": False, "status": "failed", "error": "Cas finished without a CSV link: " + text[:600]}, 1)
                summary = None
                m = SUMMARY_RE.search(text)
                if m:
                    try:
                        summary = json.loads(m.group(0))
                    except ValueError:
                        summary = None
                try:
                    agents = check_csv(links[0])
                except RuntimeError as e:
                    out({"ok": False, "status": "failed", "error": str(e)}, 1)
                out({"ok": True, "status": "done", "link": links[0], "agents": agents, "summary": summary})
            if finish not in ("tool-calls", None):
                out({"ok": False, "status": "failed", "error": "Cas stopped with finish=" + str(finish) + ": " + text[:600]}, 1)
        waited = int(time.time() - started)
        if waited + POLL_SECONDS > args.max_seconds:
            out({"ok": True, "status": "running", "waited_seconds": waited})
        time.sleep(POLL_SECONDS)


def main():
    p = argparse.ArgumentParser(prog="cas_pull.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--zips", required=True)
    s.add_argument("--max-agents", type=int, default=5000)
    w = sub.add_parser("wait")
    w.add_argument("--session", required=True)
    w.add_argument("--max-seconds", type=int, default=240)
    args = p.parse_args()
    try:
        start(args) if args.cmd == "start" else wait(args)
    except RuntimeError as e:
        out({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
