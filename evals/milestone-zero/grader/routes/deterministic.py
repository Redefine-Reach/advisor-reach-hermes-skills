#!/usr/bin/env python3
"""Deterministic (regex) MVQ grader: always runs, never calls a model.

Each line returns 0/1/2 plus a fixed reason code. Reasons are fixed strings,
never copies of case or reply text, so they are safe to keep in evidence for
real (redacted) cases.
"""

from __future__ import annotations

import re
from typing import Any

from grader.hard_fail import detect_bad_why, detect_hard_fails

_REASK_CONTACT = re.compile(r"\bwhich\s+([A-Z][a-z]+)\s*(?:did you mean)?\?", re.IGNORECASE)
_REASK_NUMBER = re.compile(
    r"\b(?:what(?:'s| is)|need|send me|share)\s+(?:([A-Z][a-z]+)(?:'s)?\s+)?(?:(?:phone\s+)?number|cell|phone|email)\b",
    re.IGNORECASE,
)
_CTX_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_CTX_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_REASK_ZONE = re.compile(
    r"(?:phoenix time again|what(?:'s| is) your (?:time ?zone|zone)|which time ?zone)",
    re.IGNORECASE,
)
_FILLER = re.compile(r"great question|here are (?:some )?(?:options|a few)|i'd be happy to|happy to help", re.I)
_OFFER_ONLY = re.compile(r"would you like me to|want me to\?|shall i\b|do you want me to", re.I)
_DID_WORK = re.compile(r"\b(drafted|draft to|draft|staged|reminder set|set for|saved|scheduled|added|found|booked|updated|here(?:'s| is) the)\b", re.I)
_PARTIAL_OFFER = re.compile(r"\bi can .+ if you", re.I)
_HONEST_GAP = re.compile(r"\bi (?:couldn't|could not|can't|cannot) find\b|\bi don't have\b", re.I)
_WHY = re.compile(r"^\s*Why:\s*\S.+$", re.IGNORECASE | re.MULTILINE)
_BULLETS = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", re.MULTILINE)


_HEDGE = re.compile(r"\b(i think|probably|should be|i believe|might be|looks like|around|roughly|approximately|if i recall)\b", re.I)
_SEND_FOOTER = re.compile(r"\b(?:say|reply|text|send)\s+SEND\b|\bSEND to send\b", re.I)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_DRAFT_HEAD = re.compile(r"^\s*(?:drafted|draft(?: email| text)?)(?:\s+(?:to|for)\b[^:\n]*)?:\s*", re.I)
_QUOTED = re.compile(r"[\"\u201c][^\"\u201d\n]{3,}[\"\u201d]")


_GENERIC_WHY = re.compile(
    r"^\s*why:\s*(?:(?:to\s+)?(?:follow(?:ing)?[\s-]*up|check(?:ing)?\s+in|touch(?:ing)?\s+base|keep(?:ing)?\s+in\s+touch|"
    r"stay(?:ing)?\s+in\s+touch|keep\s+things\s+moving|be\s+helpful)|you\s+asked(?:\s+me)?(?:\s+to)?|as\s+requested|"
    r"per\s+your\s+request|requested|n/?a|none)\s*[.!]?\s*$",
    re.I | re.M,
)


def generic_why(text: str) -> bool:
    """A Why line that gives no real reason (generic filler), e.g. 'Why: following up.'"""
    return bool(_GENERIC_WHY.search(text or ""))


def produced_draft(assistant: str) -> bool:
    low = assistant.lower()
    return bool(re.search(r"\bdraft", low) or _SEND_FOOTER.search(assistant))


def split_draft(assistant: str) -> tuple[str, str]:
    """(ARIN's own words, drafted text). Drafted text = quoted text, or what follows
    'Draft to X:' up to the Why / SEND footer lines."""
    drafted: list[str] = []
    own: list[str] = []
    in_draft = False
    for line in assistant.splitlines():
        m = _DRAFT_HEAD.match(line)
        if m:
            own.append(line[: m.end()])
            rest = line[m.end():]
            if rest.strip():
                drafted.append(rest)
            in_draft = True
            continue
        if re.match(r"^\s*why:", line, re.I) or _SEND_FOOTER.search(line):
            in_draft = False
            own.append(line)
            continue
        (drafted if in_draft else own).append(line)
    own_text = "\n".join(own)
    for q in _QUOTED.findall(own_text):
        drafted.append(q)
        own_text = own_text.replace(q, "")
    return own_text, "\n".join(drafted)


def style_sample(case: dict[str, Any]) -> list[str]:
    """Owner's own last up-to-5 turns in the case (stored sample wins)."""
    inp = case.get("input") or {}
    stored = inp.get("style_sample")
    if isinstance(stored, list) and stored:
        return [str(x) for x in stored][-5:]
    owner = [t["content"] for t in (inp.get("context_turns") or [])
             if isinstance(t, dict) and t.get("role") == "owner" and isinstance(t.get("content"), str)]
    if inp.get("owner_text"):
        owner.append(str(inp["owner_text"]))
    return owner[-5:]


def build_route():
    return DeterministicRoute()


class DeterministicRoute:
    name = "deterministic"

    def grade(self, case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        assistant = run.get("assistant_text") or ""
        inp = case.get("input") or {}
        owner = inp.get("owner_text") or ""
        prior = "\n".join(t.get("content", "") for t in (inp.get("context_turns") or []) if isinstance(t, dict))
        context = f"{inp.get('context_available') or ''}\n{prior}\n{owner}"
        hard = detect_hard_fails(case, run)
        flags: list[str] = []

        if not assistant.strip():
            return {
                "line_scores": [0, 0, 0, 0, 0],
                "line_reasons": ["no_reply"] * 5,
                "hard_fails": hard,
                "grader_note": "no assistant reply",
                "route": self.name,
                "flags": ["no_reply"],
            }

        scores: list[int | None] = [2, 2, 2, 2, 2]
        reasons = ["ok"] * 5
        own, drafted = split_draft(assistant)
        questions = own.count("?")

        # R1 (always scored): re-ask of known context = 0; >1 question = 1; else 2.
        m = _REASK_CONTACT.search(own)
        if m and m.group(1).lower() in context.lower():
            scores[0], reasons[0] = 0, "reask_contact_in_context"
        elif (n := _REASK_NUMBER.search(own)) and (
            (re.search(r"email", n.group(0), re.I) and _CTX_EMAIL.search(context))
            or (not re.search(r"email", n.group(0), re.I) and _CTX_PHONE.search(context)
                and (not n.group(1) or n.group(1).lower() in context.lower()))
        ):
            scores[0], reasons[0] = 0, "reask_contact_detail_in_context"
        elif _REASK_ZONE.search(own) and re.search(r"\b(phoenix|mst|az|arizona|time ?zone)\b", context, re.I):
            scores[0], reasons[0] = 0, "reask_zone_in_context"
        elif questions >= 2:
            scores[0], reasons[0] = 1, "more_than_one_question"
        elif not prior.strip() and not (inp.get("context_available") or "").strip():
            reasons[0] = "no_context_no_reask"

        # R2: length of ARIN's OWN text (drafted text exempt), filler/menus, owner voice of drafts.
        n = len(own.strip())
        sample = style_sample(case)
        if n > 400 or _FILLER.search(own) or len(_BULLETS.findall(own)) >= 3:
            scores[1], reasons[1] = 0, "long_or_filler_or_menu"
        elif n > 220:
            scores[1], reasons[1] = 1, "over_220_chars"
        elif drafted and _EMOJI.search(drafted) and not any(_EMOJI.search(x) for x in sample):
            scores[1], reasons[1] = 1, "draft_emoji_not_in_owner_style"

        # R3: does or advances; one needed question or a staged draft with SEND footer counts.
        if _OFFER_ONLY.search(own) and not (_DID_WORK.search(assistant) or _SEND_FOOTER.search(assistant)):
            scores[2], reasons[2] = 0, "offer_only"
        elif _PARTIAL_OFFER.search(own):
            scores[2], reasons[2] = 1, "partial_offer"
        elif questions == 1 and not _OFFER_ONLY.search(own):
            reasons[2] = "one_needed_question"
        elif _SEND_FOOTER.search(assistant):
            reasons[2] = "draft_staged_send"

        # Jerry 5:05 AM: a re-ask of known context scores line 1 = 0 AND line 3 = 1 (both apply).
        if scores[0] == 0:
            scores[2], reasons[2] = 1, "reask_known_context"

        # R4: invented fact (H1) = 0; hedged/loosely supported = 1.
        if hard["H1"]:
            scores[3], reasons[3] = 0, "invented_fact_h1"
        elif _HEDGE.search(own):
            scores[3], reasons[3] = 1, "hedged_claim"
        elif _HONEST_GAP.search(assistant):
            reasons[3] = "honest_gap"

        # R5: only when draft_expected. None/missing = legacy auto (scored iff a draft appears).
        de = case.get("draft_expected")
        applies = de is True or (de is None and produced_draft(assistant))
        if not applies:
            scores[4], reasons[4] = None, "n/a"
        elif not produced_draft(assistant):
            scores[4], reasons[4] = 0, "draft_expected_none_produced"
        elif not _WHY.search(assistant):
            scores[4], reasons[4] = 0, "draft_missing_why"
        elif detect_bad_why(assistant, owner):
            scores[4], reasons[4] = 0, "why_restates_trigger"
        elif generic_why(assistant):
            scores[4], reasons[4] = 0, "why_generic"
        else:
            reasons[4] = "why_present"
        if de is None:
            flags.append("draft_expected_unset")

        return {
            "line_scores": scores,
            "line_reasons": reasons,
            "hard_fails": hard,
            "grader_note": "deterministic",
            "route": self.name,
            "flags": flags,
        }
