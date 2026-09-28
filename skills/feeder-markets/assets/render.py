#!/opt/hermes/.venv/bin/python
"""Render a feeder-markets analysis directory to a PDF report.

Usage: render.py <analysis-dir> <out.pdf>

<analysis-dir> is what `feeder_markets.py analyze --out` wrote: summary.json, feeders.json,
zips.json. Fills template.html (jinja2 3.1 — in the box venv) and runs /usr/bin/weasyprint
(baked in the box image, google-cloud-gke-customer-boxes docker/sms-box/Dockerfile). Prints ONE
JSON object. Exit 0 ok, 2 missing/invalid input, 1 render failure.
"""
import datetime
import json
import subprocess
import sys
from pathlib import Path

import jinja2

HERE = Path(__file__).resolve().parent


def fail(code, message):
    print(json.dumps({"ok": False, "error": message}))
    sys.exit(code)


def main():
    if len(sys.argv) != 3:
        fail(2, "usage: render.py <analysis-dir> <out.pdf>")
    src, out_pdf = Path(sys.argv[1]), Path(sys.argv[2])
    data = {}
    for name in ("summary", "feeders", "zips"):
        f = src / (name + ".json")
        if not f.exists():
            fail(2, "missing " + f.name + " — run feeder_markets.py analyze first")
        data[name] = json.loads(f.read_text(encoding="utf-8"))
    data["date_long"] = datetime.date.today().strftime("%-d %B %Y")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(HERE)), autoescape=True)
    env.filters["money"] = lambda v: "—" if v is None else "${:,.0f}".format(v)
    env.filters["count"] = lambda v: "{:,}".format(v)
    html = env.get_template("template.html").render(**data)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    r = subprocess.run(["/usr/bin/weasyprint", str(html_path), str(out_pdf)], capture_output=True, text=True)
    if r.returncode != 0 or not out_pdf.exists():
        fail(1, "weasyprint failed: " + (r.stderr or "")[-500:])
    print(json.dumps({"ok": True, "pdf": str(out_pdf), "html": str(html_path)}))


if __name__ == "__main__":
    main()
