"""Inspect task: ARIN milestone-zero fixture checks."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, scorer, accuracy, mean
from inspect_ai.solver import Generate, Solver, solver

from checks import run_checks
from hermes_bridge import HERMES_PIN, prove_wrap, run_fixture

ROOT = Path(__file__).resolve().parent


def load_cases(limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with (ROOT / "cases.jsonl").open(encoding="utf-8") as handle:
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
