#!/usr/bin/env python3
"""SmartLead campaigns for this box's customer, straight against SmartLead's API.

The customer's SmartLead client account and its API key come from the AdvisorReach API
(/smartlead/v1/clients, /smartlead/v1/clients/{id}/api-key — the same calls the
email-outreach-client skill uses); every campaign call then goes to SmartLead itself
(https://server.smartlead.ai/api/v1, api_key as a query parameter — endpoint shapes from the
SmartLead Connector's tested queries, wttc/smartlead component-src/SmartLead Connector/Queries).
The key is held in memory for one command and never printed. Every command prints ONE JSON
object on stdout. Exit codes: 0 ok; 1 error (read "error").
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SMARTLEAD_API_BASE = os.environ.get("SMARTLEAD_API_BASE", "https://server.smartlead.ai/api/v1")
# SmartLead sits behind Cloudflare; always send an explicit User-Agent (circle-member-token's rule).
USER_AGENT = "advisorreach-box/1.0"
TIMEOUT_SECONDS = 60


def _out(obj, code: int = 0):
    print(json.dumps(obj))
    sys.exit(code)


def _request(method: str, url: str, headers=None, body=None):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
            text = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        text, status = e.read().decode(), e.code
    except (urllib.error.URLError, TimeoutError) as e:
        _out({"ok": False, "error": f"could not reach {url.split('?')[0]}: {e}"}, 1)
    try:
        return status, json.loads(text) if text else None
    except ValueError:
        return status, text[:2000]


def _advisorreach(path: str):
    base = os.environ.get("ADVISORREACH_API_URL", "").rstrip("/")
    key = os.environ.get("ADVISORREACH_API_KEY", "")
    if not base or not key:
        _out({"ok": False, "error": "ADVISORREACH_API_URL / ADVISORREACH_API_KEY are not set"}, 1)
    return _request("GET", base + path, {"Authorization": "Bearer " + key})


def _client(client_id):
    status, clients = _advisorreach("/smartlead/v1/clients")
    if status != 200:
        _out({"ok": False, "status": status, "error": f"could not list SmartLead accounts: {clients}"}, 1)
    if not clients:
        _out({"ok": False, "error": "this customer has no SmartLead account yet — set one up with the email-outreach skill"}, 1)
    if client_id is not None:
        match = [c for c in clients if int(c["client_id"]) == int(client_id)]
        if not match:
            _out({"ok": False, "error": f"SmartLead account {client_id} is not this customer's"}, 1)
        return match[0]
    if len(clients) > 1:
        _out({"ok": False, "error": "this customer has several SmartLead accounts — pass --client-id",
              "accounts": [{"client_id": c["client_id"], "name": c["name"]} for c in clients]}, 1)
    return clients[0]


def _key(client_id: int) -> str:
    status, body = _advisorreach(f"/smartlead/v1/clients/{client_id}/api-key")
    keys = body.get("api_keys") if isinstance(body, dict) else None
    if status != 200 or not keys:
        _out({"ok": False, "status": status, "error": "could not get the SmartLead API key for this account"}, 1)
    return keys[0]


def _sl(args, method: str, path: str, body=None, query=None):
    client = _client(args.client_id)
    params = {**(query or {}), "api_key": _key(client["client_id"])}
    status, data = _request(method, SMARTLEAD_API_BASE + path + "?" + urllib.parse.urlencode(params), body=body)
    if status >= 400:
        _out({"ok": False, "status": status, "error": data}, 1)
    return data


def _read_json_file(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        _out({"ok": False, "error": f"could not read JSON from {path}: {e}"}, 1)


def cmd_account(args):
    c = _client(args.client_id)
    _out({"ok": True, "client_id": c["client_id"], "name": c["name"], "email": c["email"]})


def cmd_campaigns(args):
    data = _sl(args, "GET", "/campaigns")
    _out({"ok": True, "campaigns": [{"id": c.get("id"), "name": c.get("name"), "status": c.get("status"),
                                     "created_at": c.get("created_at")} for c in data or []]})


STAT_FIELDS = ("sent_count", "unique_sent_count", "open_count", "unique_open_count", "click_count",
               "reply_count", "bounce_count", "unsubscribed_count", "total_count", "drafted_count")


def cmd_stats(args):
    data = _sl(args, "GET", f"/campaigns/{args.campaign_id}/analytics") or {}
    _out({"ok": True, "campaign_id": args.campaign_id, "name": data.get("name"), "status": data.get("status"),
          **{k: data.get(k) for k in STAT_FIELDS}})


def cmd_sequences(args):
    data = _sl(args, "GET", f"/campaigns/{args.campaign_id}/sequences") or []
    _out({"ok": True, "campaign_id": args.campaign_id,
          "sequences": [{"seq_number": s.get("seq_number"), "subject": s.get("subject"),
                         "email_body": s.get("email_body"),
                         "delay_in_days": (s.get("seq_delay_details") or {}).get("delay_in_days")} for s in data]})


def cmd_mailboxes(args):
    data = _sl(args, "GET", "/email-accounts/", query={"offset": 0, "limit": 100}) or []
    _out({"ok": True, "mailboxes": [{"id": a.get("id"), "from_email": a.get("from_email"),
                                     "sending_ok": a.get("is_smtp_success"), "receiving_ok": a.get("is_imap_success")}
                                    for a in data]})


def cmd_create(args):
    data = _sl(args, "POST", "/campaigns/create", body={"name": args.name}) or {}
    _out({"ok": True, "campaign_id": data.get("id"), "name": data.get("name", args.name), "status": "DRAFTED"})


def cmd_save_sequences(args):
    sequences = _read_json_file(args.file)
    if not isinstance(sequences, list) or not sequences:
        _out({"ok": False, "error": "the file must hold a non-empty JSON list of emails"}, 1)
    _sl(args, "POST", f"/campaigns/{args.campaign_id}/sequences", body={"sequences": sequences})
    _out({"ok": True, "campaign_id": args.campaign_id, "emails_saved": len(sequences)})


def cmd_add_leads(args):
    leads = _read_json_file(args.file)
    if not isinstance(leads, list) or not leads:
        _out({"ok": False, "error": "the file must hold a non-empty JSON list of leads"}, 1)
    data = _sl(args, "POST", f"/campaigns/{args.campaign_id}/leads", body={"lead_list": leads})
    _out({"ok": True, "campaign_id": args.campaign_id, "leads_sent": len(leads), "smartlead": data})


def cmd_attach_mailboxes(args):
    _sl(args, "POST", f"/campaigns/{args.campaign_id}/email-accounts",
        body={"email_account_ids": [int(i) for i in args.mailbox_ids]})
    _out({"ok": True, "campaign_id": args.campaign_id, "mailbox_ids": [int(i) for i in args.mailbox_ids]})


def cmd_schedule(args):
    body = {"timezone": args.timezone, "days_of_the_week": [int(d) for d in args.days.split(",")],
            "start_hour": args.start_hour, "end_hour": args.end_hour,
            "min_time_btw_emails": args.min_minutes_between, "max_new_leads_per_day": args.max_new_leads_per_day}
    _sl(args, "POST", f"/campaigns/{args.campaign_id}/schedule", body=body)
    _out({"ok": True, "campaign_id": args.campaign_id, "schedule": body})


def _set_status(args, status: str):
    _sl(args, "POST", f"/campaigns/{args.campaign_id}/status", body={"status": status})
    _out({"ok": True, "campaign_id": args.campaign_id, "status": status})


def main():
    p = argparse.ArgumentParser(prog="smartlead.py", description=__doc__.splitlines()[0])
    p.add_argument("--client-id", type=int, help="only when the customer has several SmartLead accounts")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("account", help="the customer's SmartLead account").set_defaults(fn=cmd_account)
    sub.add_parser("campaigns", help="list campaigns with their status").set_defaults(fn=cmd_campaigns)
    for name, fn, h in (("stats", cmd_stats, "sent/open/reply/bounce counts for one campaign"),
                        ("sequences", cmd_sequences, "the emails (subject/body) of one campaign")):
        s = sub.add_parser(name, help=h)
        s.add_argument("campaign_id")
        s.set_defaults(fn=fn)
    sub.add_parser("mailboxes", help="sending mailboxes and whether they work").set_defaults(fn=cmd_mailboxes)
    s = sub.add_parser("create", help="create a DRAFT campaign (after the user's yes)")
    s.add_argument("name")
    s.set_defaults(fn=cmd_create)
    for name, fn, h in (("save-sequences", cmd_save_sequences, "write the campaign's emails from a JSON file"),
                        ("add-leads", cmd_add_leads, "add leads from a JSON file")):
        s = sub.add_parser(name, help=h)
        s.add_argument("campaign_id")
        s.add_argument("--file", required=True)
        s.set_defaults(fn=fn)
    s = sub.add_parser("attach-mailboxes", help="send this campaign from these mailboxes")
    s.add_argument("campaign_id")
    s.add_argument("mailbox_ids", nargs="+")
    s.set_defaults(fn=cmd_attach_mailboxes)
    s = sub.add_parser("schedule", help="set sending days/hours")
    s.add_argument("campaign_id")
    s.add_argument("--timezone", required=True)
    s.add_argument("--days", default="1,2,3,4,5")
    s.add_argument("--start-hour", default="09:00")
    s.add_argument("--end-hour", default="17:00")
    s.add_argument("--min-minutes-between", type=int, default=20)
    s.add_argument("--max-new-leads-per-day", type=int, default=50)
    s.set_defaults(fn=cmd_schedule)
    for name, status in (("start", "START"), ("pause", "PAUSED")):
        s = sub.add_parser(name, help=f"set the campaign to {status} (after the user's yes)")
        s.add_argument("campaign_id")
        s.set_defaults(fn=lambda a, st=status: _set_status(a, st))
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
