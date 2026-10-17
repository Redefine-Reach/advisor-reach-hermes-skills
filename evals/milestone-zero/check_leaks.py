#!/usr/bin/env python3
"""Run a redactor command over the FAKE session set; report leaks per category and over-redaction.

Redactor contract (one session at a time):
  command template with {in} {out} and optional {known} {rules} {forgotten} placeholders.
  Excluded = non-zero exit, crash, timeout, OR no output file / empty output.
  Anything written to {out} is scanned even when the exit code is non-zero (fail-open output = leak).
Exit codes: 0 clean; 1 any leak (or a detector-error session not excluded); 2 only over-redaction/over-exclusion
(controls changed/dropped) and --fail-on-overredaction; 3 setup error.
Report prints counts only: categories, session ids and counts. Planted FAKE values are never printed.
"""
import argparse, json, os, re, shlex, subprocess, sys, tempfile
from os import environ
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

def collapse_digits(s):
    return re.sub(r"(?<=\d)[\s\-.()+](?=[\s\-.()+]*\d)", "", s)

def leaked(span, out):
    hits = []
    for needle in span["leak_if_any"]:
        if span["type"] == "digits":
            hay = collapse_digits(out)
            hay = re.sub(r"(?<=\d)[\s\-.()+]+(?=\d)", "", hay)
            if re.search(r"(?<!\d)" + re.escape(needle) + r"(?!\d)", hay):
                hits.append(needle)
        else:
            if re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", out, re.I):
                hits.append(needle)
    return bool(hits)

def run_one(cmd_tpl, src, ctx, timeout):
    with tempfile.TemporaryDirectory() as td:
        outp = Path(td) / "out.txt"
        cmd = cmd_tpl.format(**{"in": str(src), "out": str(outp), **ctx})
        try:
            r = subprocess.run(shlex.split(cmd), capture_output=True, timeout=timeout, cwd=ctx.get("cwd") or None)
            code = r.returncode
            if b"Traceback (most recent call last)" in r.stderr:
                code = "traceback"
        except subprocess.TimeoutExpired:
            code = "timeout"
        text = ""
        if outp.exists():
            try:
                text = outp.read_bytes().decode("utf-8", "replace")
            except Exception:
                text = ""
        return code, text

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmd", required=True, help='e.g. "python3 redact.py --in {in} --out {out} --fail-closed"')
    ap.add_argument("--sessions", default=str(FIXTURES / "fake_sessions"))
    ap.add_argument("--label", default="redactor")
    ap.add_argument("--cwd", help="working dir for the redactor command")
    ap.add_argument("--timeout", type=float, default=20)
    ap.add_argument("--fail-on-overredaction", action="store_true")
    ap.add_argument("--strict-drop", action="store_true",
                    help="count a health/legal/do-not-keep/forgotten session that was redacted but not dropped as a leak")
    ap.add_argument("--json", help="write the machine report here (counts only)")
    ap.add_argument(
        "--private-sessions",
        help="Optional extra session dir (not committed); or set MZ_PRIVATE_LEAK_SESSIONS",
    )
    a = ap.parse_args()
    private = a.private_sessions or environ.get("MZ_PRIVATE_LEAK_SESSIONS")
    if private:
        code = main_run(
            a.cmd,
            Path(private).resolve(),
            f"{a.label}-private",
            a.cwd,
            a.timeout,
            a.fail_on_overredaction,
            a.strict_drop,
            a.json,
        )
        if code != 0:
            return code
    return main_run(
        a.cmd,
        Path(a.sessions).resolve(),
        a.label,
        a.cwd,
        a.timeout,
        a.fail_on_overredaction,
        a.strict_drop,
        a.json,
    )


def main_run(cmd_tpl, sd: Path, label: str, cwd, timeout, fail_on_over, strict_drop, json_path):
    sd = Path(sd).resolve()
    keys = [json.loads(l) for l in (sd / "answer_keys.jsonl").read_text().splitlines() if l.strip()]
    if not keys:
        print("no answer keys", file=sys.stderr)
        return 3
    ctx = {
        "known": str(sd / "known_names.txt"),
        "rules": str(sd / "donotkeep_rules.json"),
        "forgotten": str(sd / "forgotten.txt"),
        "cwd": cwd or "",
    }
    planted = defaultdict(int)
    leak = defaultdict(int)
    leak_ids = defaultdict(list)
    excluded_by_cat = defaultdict(int)
    not_dropped = defaultdict(list)
    crashes = []
    over = []
    over_excl = []
    err_not_excluded = []
    for k in keys:
        code, out = run_one(cmd_tpl, sd / k["file"], ctx, timeout)
        crashed = code in ("timeout", "traceback") or (isinstance(code, int) and code not in (0, 1, 2))
        if crashed:
            crashes.append(k["id"])
        excluded = (code != 0) or not out.strip()
        kind = k["kind"]
        if kind == "control":
            if excluded:
                over_excl.append((k["id"], bool(k.get("tricky"))))
            else:
                for kp in k["keep"]:
                    if kp not in out:
                        over.append((k["id"], bool(k.get("tricky"))))
                        break
            continue
        if kind == "error":
            planted["detector_error"] += 1
            if not excluded or any(leaked(s, out) for s in k["spans"]):
                leak["detector_error"] += 1
                leak_ids["detector_error"].append(k["id"])
                err_not_excluded.append(k["id"])
            else:
                excluded_by_cat["detector_error"] += 1
            continue
        for s in k["spans"]:
            planted[s["cat"]] += 1
            if out and leaked(s, out):
                leak[s["cat"]] += 1
                leak_ids[s["cat"]].append(k["id"])
            elif excluded:
                excluded_by_cat[s["cat"]] += 1
        if kind == "drop" and not excluded:
            not_dropped[k["drop_reason"]].append(k["id"])
            if strict_drop:
                for s in k["spans"]:
                    if not leaked(s, out):
                        leak[s["cat"]] += 1
                        leak_ids[s["cat"]].append(k["id"] + "(not dropped)")
    cats = sorted(planted)
    total_planted = sum(planted.values())
    total_leak = sum(leak.values())
    print(f"== check_leaks: {label}  sessions={len(keys)} planted_spans={total_planted}")
    print(f"{'category':<14}{'planted':>8}{'leaked':>8}{'excluded':>10}")
    for c in cats:
        print(f"{c:<14}{planted[c]:>8}{leak[c]:>8}{excluded_by_cat[c]:>10}")
    ctrl = [k for k in keys if k["kind"] == "control"]
    ov_plain = [i for i, t in over if not t]
    ov_tr = [i for i, t in over if t]
    ex_plain = [i for i, t in over_excl if not t]
    ex_tr = [i for i, t in over_excl if t]
    print(
        f"controls={len(ctrl)} over-redacted={len(over)} (clean {len(ov_plain)}, tricky {len(ov_tr)}) "
        f"over-excluded={len(over_excl)} (clean {len(ex_plain)}, tricky {len(ex_tr)})"
    )
    if over or over_excl:
        print("  control ids:", ",".join(sorted(set(i for i, _ in over) | set(i for i, _ in over_excl))))
    print(
        "redacted-not-dropped (drop-expected sessions that came out): "
        + (", ".join(f"{r}={len(v)}" for r, v in sorted(not_dropped.items())) or "none")
    )
    if crashes:
        print(f"crashes/timeouts (treated as excluded): {len(crashes)} ids={','.join(crashes[:10])}")
    print(f"LEAKS TOTAL: {total_leak}  | detector-error sessions not excluded: {len(err_not_excluded)}")
    for c in cats:
        if leak_ids[c]:
            print(f"  leaked {c}: {','.join(leak_ids[c][:12])}{'...' if len(leak_ids[c])>12 else ''}")
    if json_path:
        Path(json_path).write_text(
            json.dumps(
                {
                    "label": label,
                    "sessions": len(keys),
                    "planted": planted,
                    "leaked": leak,
                    "excluded": excluded_by_cat,
                    "controls": len(ctrl),
                    "over_redacted": len(over),
                    "over_excluded": len(over_excl),
                    "not_dropped": {r: len(v) for r, v in not_dropped.items()},
                    "crashes": len(crashes),
                    "leaks_total": total_leak,
                },
                indent=2,
            )
            + "\n"
        )
        os.chmod(json_path, 0o600)
    if total_leak or err_not_excluded:
        return 1
    if fail_on_over and (over or over_excl):
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
