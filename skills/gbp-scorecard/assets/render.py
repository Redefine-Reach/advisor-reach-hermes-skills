#!/opt/hermes/.venv/bin/python
"""Render a gbp-scorecard report directory to PDF.

Usage: render.py <report-dir> <out.pdf> [--publish]

With --publish, copy the PDF to $ARTIFACT_DIR/<24 hex chars>.pdf and print
`render.py: link $ARTIFACT_BASE_URL/<name>`. If either env var is unset, print
`render.py: publish skipped (no ARTIFACT_DIR)` and exit 0. Always prints `pages=<n>`.

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
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import jinja2
import jsonschema

SECTIONS = [
    "meta", "tiles", "verdict", "bio", "production", "how_scored",
    "channels", "channels_note", "gbp", "plan", "targets", "donts", "sources", "research_log",
]
HERE = Path(__file__).resolve().parent
_PAGE_OBJS = re.compile(rb"/Type\s*/Page\b")
_PUBLISH_ATTEMPTS = 5


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


def parse_args(argv: list[str]) -> tuple[Path, Path, bool]:
    args = list(argv)
    publish = False
    if args and args[-1] == "--publish":
        publish = True
        args = args[:-1]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    return Path(args[0]), Path(args[1]), publish


def page_count(pdf: Path) -> int:
    # `/Type /Page` is a leaf; `/Type /Pages` does not match the trailing word boundary.
    n = len(_PAGE_OBJS.findall(pdf.read_bytes()))
    if n < 1:
        print("render.py: could not count pages", file=sys.stderr)
        sys.exit(2)
    return n


def publish_pdf(src: Path) -> None:
    artifact_dir = os.environ.get("ARTIFACT_DIR", "").strip()
    base_url = os.environ.get("ARTIFACT_BASE_URL", "").strip().rstrip("/")
    if not artifact_dir or not base_url:
        print("render.py: publish skipped (no ARTIFACT_DIR)")
        return
    data = src.read_bytes()
    root = Path(artifact_dir)
    for _ in range(_PUBLISH_ATTEMPTS):
        name = f"{secrets.token_hex(12)}.pdf"
        try:
            with open(root / name, "xb") as fh:
                fh.write(data)
        except FileExistsError:
            continue
        print(f"render.py: link {base_url}/{name}")
        return
    print("render.py: publish failed (artifact name already exists)", file=sys.stderr)
    sys.exit(1)


def emit_result(out_pdf: Path, publish: bool) -> None:
    print(f"render.py: wrote {out_pdf}")
    print(f"pages={page_count(out_pdf)}")
    if publish:
        publish_pdf(out_pdf)


def main() -> None:
    report_dir, out_pdf, publish = parse_args(sys.argv[1:])
    report = load_report(report_dir)

    schema = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError as e:
        path = "/" + "/".join(str(p) for p in e.absolute_path)
        print(f"render.py: report invalid at {path}: {e.message}", file=sys.stderr)
        sys.exit(2)

    joined = json.dumps(report, ensure_ascii=False)
    for m in re.finditer(r"[≈~]\s*\$\s?[\d.,]+\s*[MK]?", joined):
        window = joined[max(0, m.start() - 120): m.end() + 120]
        if not re.search(r"\(\s*\d+\s+(sales|transactions|listings|closings)\b", window):
            print(f"render.py: derived total {m.group(0)!r} has no '(N sales)' count within 120 chars — show the addend count or drop the figure", file=sys.stderr)
            sys.exit(2)

    # Found-but-dropped guard: every research_log entry the agent marked found:true must be
    # cited somewhere in the report body (its domain must appear in some cell, the bio, or
    # sources). Measured 2026-09-12: runs found the trade-press finalist page and then omitted it.
    body = json.dumps({k: v for k, v in report.items() if k != "research_log"}, ensure_ascii=False).lower()
    uncited = []
    for entry in report["research_log"]:
        if entry.get("found") and entry.get("url"):
            host = urlparse(entry["url"]).netloc.lower().removeprefix("www.")
            if host and host not in body:
                uncited.append(f'{entry["step"]} -> {host}')
    if uncited:
        print("render.py: found:true sources never cited in the report (add each domain to a table cell, the bio, or `sources`): "
              + "; ".join(uncited), file=sys.stderr)
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
    emit_result(out_pdf, publish)


if __name__ == "__main__":
    main()
