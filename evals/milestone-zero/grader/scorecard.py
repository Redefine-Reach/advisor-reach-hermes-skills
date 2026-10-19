#!/usr/bin/env python3
"""Markdown scorecard generator (RED-681 §5)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _avg_line_scores(cases: list[dict[str, Any]]) -> list[float | None]:
    """Per-line average over cases where the line applies (line 5: draft_expected cases)."""
    sums = [0.0] * 5
    ns = [0] * 5
    for row in cases:
        for i, s in enumerate(row.get("line_scores") or [None] * 5):
            if s is not None:
                sums[i] += float(s)
                ns[i] += 1
    return [round(sums[i] / ns[i], 2) if ns[i] else None for i in range(5)]


def _overall(cases: list[dict[str, Any]]) -> tuple[float, int, float, int]:
    vals = [float(c.get("total") or 0) for c in cases]
    avg = round(sum(vals) / len(vals), 2) if vals else 0.0
    passed = sum(1 for c in cases if c.get("pass"))
    rate = round(passed / len(cases), 3) if cases else 0.0
    hard = sum(1 for c in cases if any((c.get("hard_fails") or {}).values()))
    return avg, passed, rate, hard


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
    unscored: int = 0,
) -> str:
    bar = float((cases[0].get("config") or {}).get("bar", 8) if cases else meta.get("bar", 8))
    grader_version = meta.get("grader_version", "unknown")
    build = meta.get("build_image", "synthetic-fixture")
    generated = meta.get("generated_at") or datetime.now(timezone.utc).isoformat()

    avg_total, pass_count, pass_rate, hard_fail_count = _overall(cases)
    real_cases = [c for c in cases if not c.get("synthetic")]
    r_avg, r_pass, r_rate, r_hard = _overall(real_cases)
    line_avgs = _avg_line_scores(cases)
    present = [i for i in range(5) if line_avgs[i] is not None]
    weakest_idx = min(present, key=lambda i: line_avgs[i]) if present else -1
    per_user = _group_pass_rate([dict(c, user="synthetic") if c.get("synthetic") else c for c in cases], "user")
    per_category = _group_pass_rate(cases, "category")
    set_report = meta.get("set_report") or {}
    struggled = set_report.get("struggled_real", sum(1 for c in real_cases if c.get("struggled")))
    struggled_target = set_report.get("struggled_target", 8)
    weights = (cases[0].get("config") or {}).get("line_weights", [1, 1, 1, 1, 1]) if cases else [1, 1, 1, 1, 1]

    lines: list[str] = [
        "# MVQ scorecard",
        "",
        f"- **Build/image:** {build}",
        f"- **Date (UTC):** {generated}",
        f"- **Cases run:** {len(cases) + unscored} (real {meta.get('cases_real', len(real_cases))} / synthetic "
        f"{meta.get('cases_synthetic', len(cases) - len(real_cases))}); scored {len(cases)}; unscored {unscored} "
        "(excluded from averages and pass rate)",
        f"- **Grader version:** {grader_version}",
        f"- **Bar:** {bar}/10 per case, and no hard fail",
        f"- **Line weights:** {weights}",
        f"- **Selection sha256:** {meta.get('selection_sha256', 'n/a')}",
        "",
        "## Overall",
        "",
        f"- All scored: average **{avg_total}/10**; pass rate **{pass_rate:.1%}** ({pass_count}/{len(cases)}); hard fails **{hard_fail_count}**",
        (f"- Real only: average **{r_avg}/10**; pass rate **{r_rate:.1%}** ({r_pass}/{len(real_cases)}); hard fails **{r_hard}**"
         if real_cases else "- Real only: n/a (no real cases scored)"),
        f"- struggled (real): {struggled} of {struggled_target} target",
        "",
        "## Real-case coverage by category (synthetic not counted)",
        "",
    ]
    for cat, cov in (set_report.get("coverage_real") or {}).items():
        mark = "" if cov["have"] >= cov["need"] else " (short)"
        lines.append(f"- {cat}: {cov['have']} of {cov['need']}{mark}")
    if set_report.get("users_over_cap"):
        lines.append(f"- Real users over the 10-case cap: {', '.join(set_report['users_over_cap'])}")
    lines.extend(["", "## Per-rubric-line average (R1–R5; R5 over draft_expected cases only)", ""])
    for i, avg in enumerate(line_avgs, start=1):
        mark = " ← weakest" if i - 1 == weakest_idx else ""
        lines.append(f"- R{i}: {'n/a' if avg is None else avg}{mark}")
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
        scores = ["n/a" if x is None else x for x in (row.get("line_scores") or [0] * 5)]
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
