#!/usr/bin/env python3
"""A Lead Magnet's Box Script (skills/lead-magnets, step 4). Installed as /opt/data/cgi-bin/<NAME>; the
magnet's name is this file's name. It checks Form Capture's secret header and every field against the
magnet's magnet.json, saves the submission as a job, starts the magnet's worker in a session of its own
(Box Scripts "Detached workers"), and answers at once. It never waits for the result.
The magnet's private folder is <root>/magnets/<NAME>, where <root> is the parent of this file's folder
(/opt/data on a box)."""
import hmac, json, os, re, subprocess, sys, time

NAME = os.path.basename(sys.argv[0])
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0]))), "magnets", NAME)


def reply(status, obj):
    sys.stdout.write("Status: " + status + "\r\nContent-Type: application/json\r\n\r\n" + json.dumps(obj))
    sys.exit(0)


def log(job_id, event, **fields):
    with open(DIR + "/log.jsonl", "a") as fh:
        fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "id": job_id,
                             "event": event, **fields}) + "\n")


if os.environ.get("REQUEST_METHOD") != "POST":
    reply("405 Method Not Allowed", {"ok": False})
with open(DIR + "/secret") as fh:
    want = fh.read().strip()
if not hmac.compare_digest(os.environ.get("HTTP_X_BOX_SCRIPT_SECRET", ""), want):
    reply("403 Forbidden", {"ok": False})
with open(DIR + "/magnet.json") as fh:
    magnet = json.load(fh)
try:
    sub = json.loads(sys.stdin.read(int(os.environ.get("CONTENT_LENGTH") or 0)) or "{}")
    sub_id = str(sub["id"])
    got = sub["fields"]
    if not isinstance(got, dict):
        raise TypeError("fields")
except (ValueError, KeyError, TypeError):
    reply("400 Bad Request", {"ok": False, "error": "not a Form Capture submission"})
if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", sub_id):
    reply("400 Bad Request", {"ok": False, "error": "bad id"})
job = {"id": sub_id, "product": {}, "contact": {}}
for part in ("product", "contact"):
    for field, pattern in magnet[part].items():
        value = str(got.get(field, "")).strip()
        if not re.fullmatch(pattern, value):
            log(sub_id, "rejected", field=field)
            reply("422 Unprocessable Entity", {"ok": False, "field": field})
        job[part][field] = value
path = DIR + "/jobs/" + sub_id + ".json"
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    reply("200 OK", {"ok": True, "duplicate": True})
with os.fdopen(fd, "w") as fh:
    json.dump(job, fh)
subprocess.Popen([sys.executable, DIR + "/work.py", path], cwd=DIR, start_new_session=True,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
log(sub_id, "received")
reply("202 Accepted", {"ok": True})
