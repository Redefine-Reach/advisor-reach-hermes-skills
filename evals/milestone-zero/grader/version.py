"""Versioned grader prompt artifact (RED-681 §4)."""

from __future__ import annotations

from pathlib import Path

GRADER_VERSION = "mvq-grader-v0.3.0"

_PROMPTS = Path(__file__).resolve().parent / "prompts"


def prompt_path() -> Path:
    return _PROMPTS / f"{GRADER_VERSION}.md"


def load_prompt() -> str:
    path = prompt_path()
    if not path.is_file():
        raise FileNotFoundError(f"grader prompt missing: {path}")
    return path.read_text(encoding="utf-8")
