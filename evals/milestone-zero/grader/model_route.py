#!/usr/bin/env python3
"""Pluggable grader model routes (env name only; fail closed)."""

from __future__ import annotations

import importlib
import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

from grader.version import GRADER_VERSION, load_prompt

ENV_ROUTE = "ARIN_MVQ_GRADER_MODEL_ROUTE"
ENV_HTTP_URL = "ARIN_MVQ_GRADER_HTTP_URL"


class GraderRouteError(RuntimeError):
    pass


class GraderRoute(Protocol):
    def grade(self, case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]: ...


def require_route_name() -> str:
    name = (os.environ.get(ENV_ROUTE) or "").strip()
    if not name:
        raise GraderRouteError(
            f"{ENV_ROUTE} is not set; grader model route is required (fail closed)"
        )
    return name


def load_route(name: str | None = None) -> GraderRoute:
    route_name = (name or require_route_name()).strip()
    if route_name == "fixture":
        from grader.routes.fixture import FixtureRoute

        return FixtureRoute()
    if route_name == "http":
        return HttpRoute()
    module_path = f"grader.routes.{route_name}"
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise GraderRouteError(f"unknown grader route '{route_name}': {exc}") from exc
    factory = getattr(module, "build_route", None)
    if not callable(factory):
        raise GraderRouteError(f"route module {module_path} missing build_route()")
    return factory()


class HttpRoute:
    """POST redacted payload to operator-provided URL (no API keys in repo)."""

    def grade(self, case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        url = (os.environ.get(ENV_HTTP_URL) or "").strip()
        if not url:
            raise GraderRouteError(f"{ENV_HTTP_URL} required when route is http")
        payload = {
            "grader_version": GRADER_VERSION,
            "prompt": load_prompt(),
            "case": _redacted_case_slice(case),
            "assistant_text": run.get("assistant_text") or "",
            "tool_calls": run.get("tool_calls") or [],
            "outbound_log": run.get("outbound_log") or [],
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise GraderRouteError(f"http grader request failed: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GraderRouteError(f"http grader returned non-JSON: {exc}") from exc
        return _normalize_model_payload(data)


def _redacted_case_slice(case: dict[str, Any]) -> dict[str, Any]:
    inp = case.get("input") or {}
    return {
        "id": case.get("id"),
        "user": case.get("user"),
        "category": case.get("category"),
        "owner_text": inp.get("owner_text"),
        "context_available": inp.get("context_available"),
        "synthetic": case.get("synthetic", False),
    }


def _normalize_model_payload(data: dict[str, Any]) -> dict[str, Any]:
    scores = data.get("line_scores")
    reasons = data.get("line_reasons")
    hard = data.get("hard_fails")
    if not isinstance(scores, list) or len(scores) != 5:
        raise GraderRouteError("model output line_scores must be length 5")
    if not isinstance(reasons, list) or len(reasons) != 5:
        raise GraderRouteError("model output line_reasons must be length 5")
    if not isinstance(hard, dict):
        raise GraderRouteError("model output hard_fails must be an object")
    norm_scores = [None if s is None else max(0, min(2, int(s))) for s in scores]
    norm_hard = {k: bool(hard.get(k)) for k in ("H1", "H2", "H3", "H4")}
    return {
        "line_scores": norm_scores,
        "line_reasons": [str(r)[:240] for r in reasons],
        "hard_fails": norm_hard,
        "grader_note": str(data.get("grader_note") or "")[:500],
        "route": "model",
    }
