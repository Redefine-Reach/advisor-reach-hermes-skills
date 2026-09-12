#!/opt/hermes/.venv/bin/python
"""Render a gbp-scorecard report directory to PDF.

Usage: render.py <report-dir> <out.pdf>

<report-dir> holds ONE JSON FILE PER SECTION (small files, so a text-only model never
has to emit one giant JSON blob in a single tool call):
  meta.json tiles.json verdict.json bio.json production.json how_scored.json
  channels.json channels_note.json gbp.json plan.json targets.json donts.json sources.json
Each file's top-level value is the section value named by the file (a string for the
*_note / verdict / how_scored / sources files, an array or object otherwise).

Merges them, validates against schema.json (jsonschema 4.26 — in the box venv),
fills template.html (jinja2 3.1 — in the box venv), then runs /usr/bin/weasyprint
(WeasyPrint 62.3 — baked in the box image, docker/sms-box/Dockerfile:6).
Exit 2 on validation error, printing the JSON pointer so the agent fixes the JSON,
never the template.
"""
import json
import subprocess
import sys
from pathlib import Path

import jinja2
import jsonschema

SECTIONS = [
    "meta", "tiles", "verdict", "bio", "production", "how_scored",
    "channels", "channels_note", "gbp", "plan", "targets", "donts", "sources", "research_log",
]
HERE = Path(__file__).resolve().parent


def load_report(report_dir: Path) -> dict:
    report = {}
    missing = []
    for name in SECTIONS:
        f = report_dir / f"{name}.json"
        if not f.exists():
            missing.append(f.name)
            continue
        report[name] = json.loads(f.read_text(encoding="utf-8"))
    if missing:
        print(f"render.py: missing section file(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    return report


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    report_dir, out_pdf = Path(sys.argv[1]), Path(sys.argv[2])
    report = load_report(report_dir)

    schema = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError as e:
        path = "/" + "/".join(str(p) for p in e.absolute_path)
        print(f"render.py: report invalid at {path}: {e.message}", file=sys.stderr)
        sys.exit(2)

    import re
    joined = json.dumps(report, ensure_ascii=False)
    for m in re.finditer(r"[≈~]\s*\$\s?[\d.,]+\s*[MK]?", joined):
        window = joined[max(0, m.start() - 120): m.end() + 120]
        if not re.search(r"\(\s*\d+\s+(sales|transactions|listings|closings)\b", window):
            print(f"render.py: derived total {m.group(0)!r} has no '(N sales)' count within 120 chars — show the addend count or drop the figure", file=sys.stderr)
            sys.exit(2)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(HERE)),
        autoescape=jinja2.select_autoescape(["html"]),
        undefined=jinja2.StrictUndefined,
    )
    html = env.get_template("template.html").render(**report)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    subprocess.run(["/usr/bin/weasyprint", str(html_path), str(out_pdf)], check=True)
    print(f"render.py: wrote {out_pdf}")


if __name__ == "__main__":
    main()
