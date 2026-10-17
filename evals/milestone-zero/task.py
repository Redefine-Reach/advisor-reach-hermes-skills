"""Inspect task: ARIN milestone-zero fixture checks."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, scorer, accuracy, mean
from inspect_ai.solver import Generate, Solver, solver

from checks import run_checks
from grader.config import load_grader_config
from grader.scorer import grade_case, grade_run_outbound_guard
from grader.version import GRADER_VERSION
from hermes_bridge import HERMES_PIN, prove_wrap, run_fixture
from outbound_stub import OutboundRecorder

ROOT = Path(__file__).resolve().parent


def load_cases(limit: int | None = None, cases_path: Path | None = None) -> list[dict]:
    rows: list[dict] = []
    path = cases_path or (ROOT / "cases.jsonl")
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def to_samples(limit: int | None = None) -> list[Sample]:
    samples: list[Sample] = []
    for case in load_cases(limit):
        samples.append(
            Sample(
                input=case["input"]["owner_text"],
                target="pass",
                id=case["id"],
                metadata=case,
            )
        )
    return samples


@solver
def fixture_replay() -> Solver:
    async def solve(state, generate: Generate):
        case = state.metadata
        run = run_fixture(case)
        state.output.completion = run.get("assistant_text", "")
        state.metadata["run"] = run
        return state

    return solve


@scorer(metrics=[accuracy(), mean()])
def arin_milestone_checks() -> Scorer:
    async def score(state, target):
        case = state.metadata
        run = case.get("run") or run_fixture(case)
        ok, failures = run_checks(case, run)
        proof = prove_wrap()
        meta = f"hermes_pin={HERMES_PIN}; wrap_ok={proof.ok}"
        if ok:
            return Score(value=1.0, answer="pass", explanation=meta)
        return Score(value=0.0, answer="fail", explanation="; ".join(failures) + " | " + meta)

    return score


@task
def arin_milestone_zero(limit: int = 20):
    return Task(
        dataset=to_samples(limit),
        solver=fixture_replay(),
        scorer=arin_milestone_checks(),
    )


def load_mvq_samples(limit: int | None = None) -> list[Sample]:
    samples: list[Sample] = []
    for case in load_cases(limit, ROOT / "cases_mvq_synthetic.jsonl"):
        samples.append(
            Sample(
                input=case["input"]["owner_text"],
                target="pass",
                id=case["id"],
                metadata=case,
            )
        )
    return samples


@solver
def mvq_fixture_replay() -> Solver:
    async def solve(state, generate: Generate):
        case = state.metadata
        rec = OutboundRecorder()
        run = run_fixture(case, recorder=rec)
        run["outbound_log"] = rec.snapshot()
        state.output.completion = run.get("assistant_text", "")
        state.metadata["run"] = run
        return state

    return solve


@scorer(metrics=[accuracy(), mean()])
def arin_mvq_grader() -> Scorer:
    async def score(state, target):
        case = state.metadata
        run = case.get("run") or {}
        guard_ok, guard_err = grade_run_outbound_guard([run])
        if not guard_ok:
            return Score(value=0.0, answer="fail", explanation=guard_err or "outbound guard")
        graded = grade_case(case, run, config=load_grader_config())
        if not graded.get("ok"):
            return Score(value=0.0, answer="fail", explanation=graded.get("error", "grader error"))
        passed = bool(graded.get("pass"))
        meta = f"mvq={GRADER_VERSION}; total={graded.get('total')}; hard={graded.get('hard_fails')}"
        if passed:
            return Score(value=1.0, answer="pass", explanation=meta)
        return Score(value=0.0, answer="fail", explanation=meta)

    return score


@task
def arin_milestone_mvq(limit: int = 12):
    return Task(
        dataset=load_mvq_samples(limit),
        solver=mvq_fixture_replay(),
        scorer=arin_mvq_grader(),
    )
