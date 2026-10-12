#!/usr/bin/env python3
"""One Lead Magnet's files on this box (skills/lead-magnets). Every command prints ONE JSON line and never
prints a secret or a lead's details: {"ok": true, ...} (exit 0) or {"ok": false, "error": "..."} (exit 1).

  magnet.py create <NAME>   the private folder <root>/magnets/<NAME> (0700) with jobs/ and a new secret
                            (0600, kept if it exists), and the results folder <root>/magnet-results/<NAME>
  magnet.py install <NAME>  checks magnet.json and deliver.py, then copies this skill's worker.py to
                            <root>/magnets/<NAME>/work.py and box_script.py to <root>/cgi-bin/<NAME>
                            (both 0700; the Box Script last, so the URL goes live only when all is in place)
  magnet.py test <NAME>     posts magnet.json's "test" values through Form Capture's public hook, as the
                            page will, with the form's name (Form Capture's endpoint from form_capture.py)
  magnet.py log <NAME>      the last 20 lines of the magnet's log (ids, events, field names, reasons)
  magnet.py off <NAME>      renames the Box Script to <NAME>.off, so its URL answers 404

--root is /opt/data on a box (the default); tests pass a temporary folder.
magnet.json: {"what": the run's instruction, "result": the one file name the run saves,
"product": {field: pattern}, "contact": {field: pattern}, "test": {field: value}}; every pattern must
match a field's whole value; "test" holds a value for every product and contact field."""
import argparse, importlib.util, json, os, re, secrets, shutil, subprocess, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
NAME_RE = r"[a-z0-9]+(-[a-z0-9]+){1,3}"
RESULT_RE = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}"


def out(ok, **fields):
    print(json.dumps({"ok": ok, **fields}))
    sys.exit(0 if ok else 1)


def put(src, dst):
    shutil.copyfile(src, dst + ".tmp")
    os.chmod(dst + ".tmp", 0o700)
    os.replace(dst + ".tmp", dst)


def check(d):
    try:
        with open(d + "/magnet.json") as fh:
            m = json.load(fh)
    except (OSError, ValueError) as e:
        return "magnet.json: " + type(e).__name__
    if not isinstance(m.get("what"), str) or not m["what"].strip():
        return "magnet.json: what must be the run's instruction"
    if not isinstance(m.get("result"), str) or not re.fullmatch(RESULT_RE, m["result"]):
        return "magnet.json: result must be one file name"
    for part in ("product", "contact"):
        if not isinstance(m.get(part), dict) or not m[part]:
            return "magnet.json: " + part + " must map fields to patterns"
        for field, pattern in m[part].items():
            try:
                re.compile(pattern)
            except (re.error, TypeError):
                return "magnet.json: bad pattern for " + part + " field " + str(field)
            if not isinstance(m.get("test"), dict) or not isinstance(m["test"].get(field), str) \
                    or not re.fullmatch(pattern, m["test"][field].strip()):
                return "magnet.json: test value for " + part + " field " + str(field) + " does not match"
    try:
        spec = importlib.util.spec_from_file_location("magnet_deliver", d + "/deliver.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, "deliver", None)):
            return "deliver.py: no deliver(job, result, ctx)"
    except Exception as e:
        return "deliver.py: " + type(e).__name__
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "install", "test", "log", "off"])
    ap.add_argument("name")
    ap.add_argument("--root", default="/opt/data")
    a = ap.parse_args()
    if not re.fullmatch(NAME_RE, a.name):
        out(False, error="NAME must be two to four lowercase words joined by hyphens")
    d = os.path.join(a.root, "magnets", a.name)
    script = os.path.join(a.root, "cgi-bin", a.name)
    if a.command == "create":
        os.makedirs(d + "/jobs", mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        os.makedirs(os.path.join(a.root, "magnet-results", a.name), exist_ok=True)
        if not os.path.exists(d + "/secret"):
            fd = os.open(d + "/secret", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, secrets.token_hex(32).encode())
            os.close(fd)
        base = os.environ.get("BOX_PUBLIC_BASE_URL", "")
        out(True, dir=d, script=script, url=base + "/scripts/" + a.name if base else "")
    if a.command == "install":
        problem = check(d)
        if problem:
            out(False, error=problem)
        os.makedirs(os.path.dirname(script), exist_ok=True)
        put(os.path.join(HERE, "worker.py"), d + "/work.py")
        put(os.path.join(HERE, "box_script.py"), script)
        out(True, script=script, worker=d + "/work.py")
    if a.command == "test":
        with open(d + "/magnet.json") as fh:
            m = json.load(fh)
        r = subprocess.run([sys.executable, os.path.join(HERE, "form_capture.py"), "status"], capture_output=True, text=True)
        st = json.loads(r.stdout or '{"ok": false, "error": "no output"}')
        if not st.get("ok"):
            out(False, error="form capture: " + str(st.get("error")))
        data = urllib.parse.urlencode({"form": a.name, **m["test"]}).encode()
        req = urllib.request.Request(st["endpoint_url"], data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": "box-script/" + a.name})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                out(True, status=resp.status)
        except urllib.error.HTTPError as e:
            out(e.code < 400, status=e.code)
    if a.command == "log":
        try:
            with open(d + "/log.jsonl") as fh:
                lines = fh.read().splitlines()[-20:]
        except OSError:
            lines = []
        out(True, log=[json.loads(l) for l in lines if l.strip()])
    if a.command == "off":
        if os.path.exists(script):
            os.replace(script, script + ".off")
        out(True, script=script + ".off")


if __name__ == "__main__":
    main()
