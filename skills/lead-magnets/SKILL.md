---
name: lead-magnets
description: "Lead magnets and web forms: capture leads (Form Capture), send each one to a script this box runs at /scripts/, make the result with one run of you, deliver it with code. Also: list a magnet's leads, switch one off."
---

# lead-magnets · build one end to end

A lead magnet is something of value offered on a web page in exchange for a person's details. You build
each one yourself, with no developer, from parts this skill gives you and two files you write:

1. **Form Capture** keeps the leads. It is an OmegaAI component installed once in this box's OmegaAI
   workspace, at `Component Installs/Form Capture`. Its public hook URL is where the page's form posts.
   Every submission becomes a row (the record of who asked), and each matching webhook is called with it.
2. **The Box Script** (`scripts/box_script.py`, your `box-scripts` skill runs it at `/scripts/<NAME>`)
   checks Form Capture's secret header and every field, saves the submission as a job, starts the worker
   and answers at once.
3. **The worker** (`scripts/worker.py`) starts one run of you whose prompt is your `what` plus only the
   checked product fields, as data. The run saves one file and nothing else: it never sends anything and
   never sees the submission. Then the worker calls your delivery code.
4. **Your `magnet.json`**: what the run makes, the file it saves, the fields and their patterns, and test
   values. **Your `deliver.py`**: how the result reaches the person, in code.
5. **The page** with the form, published with this box's site skill.

The script and the worker are the same for every magnet; never edit them. Everything about one magnet
lives in its own folder, `/opt/data/magnets/<NAME>/`, and in its own skill (step 8), on this box only.

Use your code tool (Python) for every step, and keep each code cell under 60 seconds. `fc` runs this
skill's Form Capture helper and `mg` its magnet helper; each prints one JSON line and never prints a
secret or a lead's details:
```python
import json, os, subprocess
def run(script, *args):
    r = subprocess.run(["python3", "/opt/data/skills/lead-magnets/scripts/" + script, *args],
                       capture_output=True, text=True)
    return json.loads(r.stdout or '{"ok": false, "error": "no output"}')
def fc(*args):
    return run("form_capture.py", *args)
def mg(*args):
    return run("magnet.py", *args)
```

## 0. Can this box do it?
```python
base = os.environ.get("BOX_PUBLIC_BASE_URL", "")
can_script = os.path.isdir("/opt/data/cgi-bin")
can_ask_arin = os.path.exists("/opt/data/arin-web/api-server.key")
st = fc("status")
```
- `base` empty or `can_script` False: this box cannot serve `/scripts/` yet. Stop and tell the team.
- `can_ask_arin` False: the worker cannot start a run of you. Stop and tell the team (ARIN Web is off).
- `st["ok"]` False with `MCP_QUERY_OMEGA_API_KEY is not set`: this box has no OmegaAI connection, so it
  cannot keep leads. Stop and say so. Never look for another key.
- `st["ok"]` False for any other reason (for example the page `Component Installs/Form Capture` does not
  exist): Form Capture is not installed in this workspace. Stop and tell the team; installing it is a
  one-time job for an OmegaAI operator, not for you.
- `st["ok"]` True: `st["endpoint_url"]` is the URL the page's form posts to. Go on.

## 1. Name the magnet and make its folders
`NAME` is two to four lowercase words joined by hyphens, unique on this box: the form's name in Form
Capture, the webhook's filter, the script's file name and the folder's name. Set it in your code cell, then:
```python
made = mg("create", NAME)
DIR = made["dir"]                # /opt/data/magnets/<NAME>, private (0700): secret, jobs, log, your files
SCRIPT_URL = made["url"]         # BOX_PUBLIC_BASE_URL + /scripts/<NAME>
```
The secret (`DIR/secret`, 0600) goes in the webhook's header (step 5); the script checks it on every
request. Never print it, never put it on a page, never paste it in a reply. Credentials your delivery
needs go in `DIR` too, one file each, mode 0600.

## 2. Write `DIR/magnet.json`
One JSON object with five keys:
- `what`: the whole instruction for the run of you: what to make and which of your skills makes it. It
  names no person's contact details. The worker adds the product fields after it as data, then fixed
  rules: save exactly one file, send nothing, open nothing under `/opt/data/magnets`, reply `DONE`.
- `result`: the one file name the run saves (letters, digits, `.`, `_`, `-`).
- `product`: each field the result is made from, mapped to the pattern its whole value must match. Only
  these reach the run.
- `contact`: each field only your delivery uses (an email address, a phone number), with its pattern.
  These never reach the run. A field may be in both lists.
- `test`: a value for every product and contact field, for step 6. A contact value here is one a teammate
  gave you for testing, never a made-up or researched one.
Make each pattern as narrow as the field allows, with a length limit. A field the form may leave empty
gets a pattern that also matches the empty string, `(|...)`. Form Capture posts each submission as JSON
`{"id", "form", "submitted-at", "fields", "user-agent", "origin", "referer"}`; the script reads `fields`.

## 3. Write `DIR/deliver.py`
A Python module that defines `deliver(job, result, ctx)`: send `result` (a file path), or a link to it, to
the person in `job["contact"]`, with code. `ctx` holds `dir` (`DIR`), `name` (`NAME`) and `log`, a
function `log(event, **fields)` that adds one line to the magnet's log. Rules:
- Use only the values in `job["contact"]`: never an address the run or your research found.
- Read credentials from 0600 files in `ctx["dir"]`; never put one in the code.
- Send a named `User-Agent` on every request (`box-script/` plus `ctx["name"]`): some APIs refuse
  Python's default.
- Raise an exception when delivery fails, and never put a contact value in its message or in a log line.

## 4. Install the script and the worker
```python
r = mg("install", NAME)
```
It checks `magnet.json` (every key, every pattern, every test value against its pattern) and that
`deliver.py` loads and defines `deliver`, then copies this skill's worker to `DIR/work.py` and its Box
Script to `/opt/data/cgi-bin/<NAME>`, the script last. `r["ok"]` False names what to fix.

## 5. Point a webhook at the script
```python
r = fc("add-webhook", "--url", SCRIPT_URL, "--form", NAME, "--header-file", DIR + "/secret")
```
`--form NAME` makes the webhook fire only for this magnet's form, so one Form Capture install serves
every magnet. `fc("list-webhooks")` shows each webhook's id, URL, form and header names, never header
values. To change one, `fc("remove-webhook", "--form", NAME)` and add it again.

## 6. Test before the page exists
```python
import urllib.error, urllib.request
req = urllib.request.Request(SCRIPT_URL, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
try:
    no_secret = urllib.request.urlopen(req, timeout=60).status
except urllib.error.HTTPError as e:
    no_secret = e.code              # expect 403: without the secret the script does nothing
through = mg("test", NAME)          # magnet.json's test values through Form Capture, as the page posts
```
Then confirm: `fc("submissions", "--form", NAME, "--limit", "5")` shows the test row, and `mg("log", NAME)`
shows its id with `received`, then `run_started`, `produced` and `delivered`. The run can take many
minutes: read the log in short cells, a minute apart. A `failed` line carries a reason; fix the cause,
then run the job again by hand (`python3 DIR/work.py DIR/jobs/<id>.json 2`, the `2` making a new run).

## 7. Publish the page
A plain HTML form: `method="post"`, `action` = `st["endpoint_url"]`, a hidden input `form` = `NAME`, a
hidden input `redirect` = the page's own thank-you URL (Form Capture answers the browser with a redirect
there), and exactly the product and contact fields. Publish it with this box's site skill, and follow
that skill's rules on copy and on confirming the page is live. Then run `mg("test", NAME)` once more and
check step 6's confirmations again. Only then tell the team it is live, with the page URL.

## 8. Write it down (your own skill, on this box only)
Write `/opt/data/skills/lead-magnet-builds/<NAME>/SKILL.md` with your code tool, `description` starting
with the magnet's plain name. It says: what the magnet gives and to whom; the page URL; `NAME`; what
`magnet.json` and `deliver.py` say and do, and every file `deliver.py` reads (paths only); how to tell it
worked (`mg("log", NAME)`, Form Capture rows); how to run a failed job again; and how to switch it off
(step 9). Never put a secret in it.

## 9. Switch one off
`fc("remove-webhook", "--form", NAME)` stops the script being called; Form Capture keeps recording
submissions. Then `mg("off", NAME)`, so its URL answers 404, and say in the magnet's own skill that it is
off. Never delete Form Capture rows: they are the record of who asked.

## Rules
- Nothing about one magnet goes in this skill; it goes in the magnet's folder and its own skill.
- Never edit the installed `work.py` or Box Script: change `magnet.json` or `deliver.py`, then
  `mg("install", NAME)` again.
- A run of you only makes the result: its prompt is `what` plus the checked product fields, and it never
  sends anything, never sees a contact field and never reads the submission or the job.
- Delivery is code, and it uses only the submitted contact values.
- Never print, log or reply with a secret, a token, or a lead's contact details. The log holds ids,
  events, field names and reasons only.
- Never tell anyone a magnet is live before step 7's check came through.
- Never install, re-install or change the Form Capture component itself.
- Never start a server, a daemon or a cron job for a magnet: the worker ends when its job ends.
