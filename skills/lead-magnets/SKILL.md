---
name: lead-magnets
description: "Lead magnets and web forms: capture leads (Form Capture), send each one to a script this box runs at /scripts/, publish the landing page, test it end to end. Also: list a magnet's leads, switch one off."
---

# lead-magnets · build one end to end

A lead magnet is something of value offered on a web page in exchange for a person's details. You build
each one yourself, with no developer, from four parts:

1. **Form Capture** keeps the leads. It is an OmegaAI component installed once in this box's OmegaAI
   workspace, at `Component Installs/Form Capture`. Its public hook URL is where the page's form posts.
   Every submission becomes a row (the record of who asked), and each matching webhook is called with it.
2. **A webhook** on that install points at a script on this box, with a secret header, so only Form
   Capture can run the script.
3. **The script** is a file you write on this box's volume, a Box Script (your `box-scripts` skill). The
   box runs it at `BOX_PUBLIC_BASE_URL + "/scripts/<name>"` once per request. It does this magnet's work.
4. **The page** with the form, published with this box's site skill.

Everything about one magnet goes in that magnet's own files and its own skill (step 7), never in this
skill.

Use your code tool (Python) for every step. `fc` below runs this skill's helper; each command prints
one JSON line and never prints a secret:
```python
import json, os, subprocess
def fc(*args):
    r = subprocess.run(["python3", "/opt/data/skills/lead-magnets/scripts/form_capture.py", *args],
                       capture_output=True, text=True)
    return json.loads(r.stdout or '{"ok": false, "error": "no output"}')
```

## 0. Can this box do it?
```python
base = os.environ.get("BOX_PUBLIC_BASE_URL", "")
can_script = os.path.isdir("/opt/data/cgi-bin")
can_ask_arin = os.path.exists("/opt/data/arin-web/api-server.key")
st = fc("status")
```
- `base` empty or `can_script` False: this box cannot serve `/scripts/` (Box Scripts are off). Stop and
  tell the team.
- `st["ok"]` False with `MCP_QUERY_OMEGA_API_KEY is not set`: this box has no OmegaAI connection, so it
  cannot keep leads. Stop and say so. Never look for another key.
- `st["ok"]` False for any other reason (for example the page `Component Installs/Form Capture` does not
  exist): Form Capture is not installed in this workspace. Stop and tell the team; installing it is a
  one-time job for an OmegaAI operator, not for you.
- `st["ok"]` True: `st["endpoint_url"]` is the URL the page's form posts to. Go on.
- `can_ask_arin` False: the script cannot start a run of you (step 4). Build only magnets whose work
  takes less than 30 seconds and needs no agent.

## 1. Name the magnet
`NAME` is two to four lowercase words joined by hyphens, unique on this box. It is the form's name in
Form Capture, the webhook's filter and the script's file name:
```python
import re
NAME = "free-market-report"                   # your words for this magnet
assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,3}", NAME)
SCRIPT = "/opt/data/cgi-bin/" + NAME
SCRIPT_URL = base + "/scripts/" + NAME
SECRET_FILE = "/opt/data/cgi-secrets/" + NAME
LOG = "/opt/data/cgi-logs/" + NAME + ".log"
```

## 2. Make the secret
One secret per magnet. It goes in the webhook's header, and the script checks it on every request:
```python
import secrets
os.makedirs("/opt/data/cgi-secrets", mode=0o700, exist_ok=True)
if not os.path.exists(SECRET_FILE):
    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, secrets.token_hex(32).encode())
    os.close(fd)
```
Never print it, never put it on a page, never paste it in a reply.

## 3. Write the script
Form Capture posts each submission as JSON: `{"id", "form", "submitted-at", "fields", "user-agent",
"origin", "referer"}`, where `fields` holds the form's fields. Start from this shape and put the magnet's
own work in `handle()`:
```python
BODY = '''#!/usr/bin/env python3
import hmac, json, os, sys, time
NAME = %r
SECRET_FILE = %r
LOG = %r

def reply(status, obj):
    sys.stdout.write("Status: %%s\\r\\nContent-Type: application/json\\r\\n\\r\\n" %% status)
    sys.stdout.write(json.dumps(obj))
    sys.exit(0)

def log(**fields):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"at": time.strftime("%%Y-%%m-%%dT%%H:%%M:%%SZ", time.gmtime()), **fields}) + "\\n")

def handle(sub):
    # This magnet's own work. sub["fields"] holds the form's fields. Return a small dict.
    return {}

if os.environ.get("REQUEST_METHOD") != "POST":
    reply("405 Method Not Allowed", {"ok": False})
with open(SECRET_FILE) as fh:
    want = fh.read().strip()
if not hmac.compare_digest(os.environ.get("HTTP_X_BOX_SCRIPT_SECRET", ""), want):
    reply("403 Forbidden", {"ok": False})
sub = json.loads(sys.stdin.read(int(os.environ.get("CONTENT_LENGTH") or 0)) or "{}")
log(id=sub.get("id"), form=sub.get("form"), event="received")
reply("200 OK", {"ok": True, **handle(sub)})
''' % (NAME, SECRET_FILE, LOG)
os.makedirs("/opt/data/cgi-bin", exist_ok=True)
with open(SCRIPT + ".tmp", "w") as fh:
    fh.write(BODY)
os.chmod(SCRIPT + ".tmp", 0o700)
os.replace(SCRIPT + ".tmp", SCRIPT)
```
Rules for the script:
- Check the secret before anything else. A request without it gets `403` and does nothing.
- Log submission ids, form names and events only. Never log an email address, a phone number or the
  secret.
- The box stops the script after 30 seconds. Work that needs you (an agent turn, a skill, a report)
  goes to an api_server run that `handle()` starts and does not wait for. Your `box-scripts` skill shows
  the call ("Work that takes longer than 30 seconds"). Use the submission's `id` as the
  `Idempotency-Key`, so a repeated delivery never starts a second run. Then `handle()` returns at once
  and the script answers `202 Accepted` instead of `200 OK`.
- The run starts with no conversation, so the prompt you give it carries everything: the lead's fields,
  the skill to use, and the exact last step. When that last step must be exact (a message to the lead,
  a file name), write it as a second program under `/opt/data/cgi-secrets/<NAME>-steps/` (outside
  `/opt/data/cgi-bin`, so it is never a public URL), and tell the run to finish by running it with
  the values as arguments.
- Credentials the script or its steps need are files on this volume, mode 0600, read at run time. Never
  put one in the script's text.
- No server, no daemon, no loop that keeps running, no cron job.

## 4. Point a webhook at the script
```python
r = fc("add-webhook", "--url", SCRIPT_URL, "--form", NAME, "--header-file", SECRET_FILE)
```
`--form NAME` makes the webhook fire only for this magnet's form, so one Form Capture install serves
every magnet. `fc("list-webhooks")` shows each webhook's id, URL, form and header names, never header
values. To change one, `fc("remove-webhook", "--form", NAME)` and add it again.

## 5. Test before the page exists
In this order, and do not go on until each passes:
```python
import urllib.error, urllib.request
def post(url, data, headers):
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
# a) without the secret: refused (expect 403)
no_secret = post(SCRIPT_URL, b"{}", {"Content-Type": "application/json"})
# b) through Form Capture, exactly as the page will post (the form's fields plus its name)
hook = fc("status")["endpoint_url"]
through = post(hook, ("form=" + NAME + "&name=Test+Lead&email=test%40example.com").encode(),
               {"Content-Type": "application/x-www-form-urlencoded"})
```
Then confirm (b) arrived both ways: `fc("submissions", "--form", NAME, "--limit", "5")` shows the test
row, and the script's log `LOG` has its id with `"event": "received"`. If the magnet's work sends
anything to a person, test with an address a teammate gave you for testing, never a made-up one.

## 6. Publish the page
A plain HTML form: `method="post"`, `action` = `st["endpoint_url"]`, a hidden input `form` = `NAME`, a
hidden input `redirect` = the page's own thank-you URL (Form Capture answers the browser with a redirect
there), and the fields the magnet needs. Publish it with this box's site skill (`publish-site` for the
customer's own domain; on the AdvisorReach team box, `advisorreach-site`, at `public/m/<NAME>/` with the
thank-you page at `public/m/<NAME>/thanks/`), and
follow that skill's rules on copy and on confirming the page is live. Then submit the live page once
yourself with a test address, and check step 5's two confirmations again. Only then tell the team it
is live, with the page URL.

## 7. Write it down (your own skill, on this box only)
Write `/opt/data/skills/lead-magnet-builds/<NAME>/SKILL.md` with your file tool, `description` starting
with the magnet's plain name. It says: what the magnet gives and to whom; the page URL; the form's
fields; `NAME`; the script's path and URL; every file the script or its steps read (paths only); what a
run does and what it prints; how to tell it worked (log lines, Form Capture rows); and how to switch it
off (step 8). Never put a secret in it.

## 8. Switch one off
`fc("remove-webhook", "--form", NAME)` stops the script being called; Form Capture keeps recording
submissions. Then rename the script to `<NAME>.off`, so its URL answers 404, and say in the magnet's own skill
that it is off. Never delete Form Capture rows: they are the record of who asked.

## Rules
- Nothing about one magnet goes in this skill; it goes in the magnet's own skill (step 7).
- Never print, log or reply with a secret, a token, or a lead's email or phone number.
- Never tell anyone a magnet is live before step 6's live submission came through.
- Never install, re-install or change the Form Capture component itself.
- Never start a server, a daemon or a cron job for a magnet.
