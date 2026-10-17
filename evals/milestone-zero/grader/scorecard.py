#!/usr/bin/env python3
"""Markdown scorecard generator (RED-681 §5)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _avg_line_scores(cases: list[dict[str, Any]]) -> list[float]:
    if not cases:
        return [0.0] * 5
    sums = [0.0] * 5
    for row in cases:
        scores = row.get("line_scores") or [0] * 5
        for i, s in enumerate(scores):
            sums[i] += float(s)
    n = len(cases)
    return [round(s / n, 2) for s in sums]


def _group_pass_rate(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[bool]] = {}
    for row in rows:
        k = str(row.get(key) or "unknown")
        buckets.setdefault(k, []).append(bool(row.get("pass")))
    out: dict[str, dict[str, float]] = {}
    for k, passes in buckets.items():
        out[k] = {
            "cases": len(passes),
            "pass_rate": round(sum(1 for p in passes if p) / len(passes), 3),
        }
    return out


def _top_failures(cases: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    fails = [c for c in cases if not c.get("pass")]
    fails.sort(key=lambda r: (r.get("total") or 0, r.get("case_id") or ""))
    return fails[:limit]


def render_scorecard(
    meta: dict[str, Any],
    cases: list[dict[str, Any]],
    qa_block: dict[str, Any] | None = None,
    david_sample: list[dict[str, Any]] | None = None,
    regression_cases: list[str] | None = None,
) -> str:
    bar = float((cases[0].get("config") or {}).get("bar", 8) if cases else meta.get("bar", 8))
    grader_version = meta.get("grader_version", "unknown")
    build = meta.get("build_image", "synthetic-fixture")
    generated = meta.get("generated_at") or datetime.now(timezone.utc).isoformat()

    totals = [float(c.get("total") or 0) for c in cases]
    avg_total = round(sum(totals) / len(totals), 2) if totals else 0.0
    pass_count = sum(1 for c in cases if c.get("pass"))
    pass_rate = round(pass_count / len(cases), 3) if cases else 0.0
    hard_fail_count = sum(1 for c in cases if any((c.get("hard_fails") or {}).values()))

    line_avgs = _avg_line_scores(cases)
    weakest_idx = min(range(5), key=lambda i: line_avgs[i])
    per_user = _group_pass_rate(cases, "user")
    per_category = _group_pass_rate(cases, "category")

    lines: list[str] = [
        "# MVQ scorecard",
        "",
        f"- **Build/image:** {build}",
        f"- **Date (UTC):** {generated}",
        f"- **Cases run:** {len(cases)}",
        f"- **Grader version:** {grader_version}",
        f"- **Bar:** {bar}/10",
        "",
        "## Overall",
        "",
        f"- Average total: **{avg_total}/10**",
        f"- Pass rate (≥ bar, no hard fail): **{pass_rate:.1%}** ({pass_count}/{len(cases)})",
        f"- Hard-fail count: **{hard_fail_count}**",
        "",
        "## Per-rubric-line average (R1–R5)",
        "",
    ]
    for i, avg in enumerate(line_avgs, start=1):
        mark = " ← weakest" if i - 1 == weakest_idx else ""
        lines.append(f"- R{i}: {avg}{mark}")
    lines.extend(["", "## Per-user pass rate", ""])
    for user, stats in sorted(per_user.items()):
        lines.append(f"- {user}: {stats['pass_rate']:.1%} ({stats['cases']} cases)")
    lines.extend(["", "## Per-category pass rate", ""])
    for cat, stats in sorted(per_category.items()):
        lines.append(f"- {cat}: {stats['pass_rate']:.1%} ({stats['cases']} cases)")
    lines.extend(
        [
            "",
            "## Per-case table",
            "",
            "| Case | User | Category | R1 | R2 | R3 | R4 | R5 | Total | Hard fail | Pass | Grader note |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in cases:
        scores = row.get("line_scores") or [0] * 5
        hard = row.get("hard_fails") or {}
        hard_txt = ",".join(k for k, v in hard.items() if v) or "—"
        note = (row.get("grader_note") or "").replace("|", "/")
        passed_cell = "yes" if row.get("pass") else "no"
        lines.append(
            "| {id} | {user} | {cat} | {r1} | {r2} | {r3} | {r4} | {r5} | {total} | {hard} | {passed} | {note} |".format(
                id=row.get("case_id"),
                user=row.get("user"),
                cat=row.get("category"),
                r1=scores[0],
                r2=scores[1],
                r3=scores[2],
                r4=scores[3],
                r5=scores[4],
                total=row.get("total"),
                hard=hard_txt,
                passed=passed_cell,
                note=note[:80],
            )
        )

    lines.extend(["", "## Top 5 failures", ""])
    for fail in _top_failures(cases, 5):
        lines.append(f"### {fail.get('case_id')}")
        lines.append(f"- **Why:** {fail.get('grader_note') or '; '.join(fail.get('line_reasons') or [])}")
        lines.append(f"- **Reply:** {fail.get('assistant_text', '')[:500]}")
        lines.append("")

    lines.extend(["", "## 10 raw replies for David", ""])
    sample = david_sample or cases[:10]
    lines.append("| Case input (redacted) | ARIN reply | Grader score | David score |")
    lines.append("|---|---|---|---|")
    for row in sample[:10]:
        owner = (row.get("owner_text") or "").replace("|", "/")
        reply = (row.get("assistant_text") or "").replace("|", "/")
        lines.append(f"| {owner[:120]} | {reply[:160]} | {row.get('total')}/10 | |")

    lines.extend(["", "## Grader check: QA sample agreement", ""])
    if qa_block:
        lines.append(f"- Lines within 1 point (target ≥80%): **{qa_block.get('line_agreement_rate', 0):.1%}**")
        lines.append(f"- Hard-fail agreement (target 100%): **{qa_block.get('hard_fail_agreement_rate', 0):.1%}**")
        if qa_block.get("disagreements"):
            lines.append("- Disagreements:")
            for d in qa_block["disagreements"][:20]:
                lines.append(f"  - {d}")
    else:
        lines.append("- _No QA sample loaded for this run._")

    cfg = (cases[0].get("config") if cases else None) or {}
    lines.extend(
        [
            "",
            "## Tuning knobs (David)",
            "",
            f"- Bar (default 8/10): `{cfg.get('bar', bar)}`",
            f"- Line weights: `{cfg.get('line_weights', [1,1,1,1,1])}`",
            f"- Enabled hard fails: `{cfg.get('enabled_hard_fails', ['H1','H2','H3','H4'])}`",
            "",
            "## Regression list",
            "",
        ]
    )
    if regression_cases:
        for cid in regression_cases:
            lines.append(f"- {cid}")
    else:
        lines.append("- _None added this run._")

    return "\n".join(lines) + "\n"
