"""Token normalization for do-not-keep / forgotten phrase matching (export path only)."""

from __future__ import annotations

import re
import unicodedata

_STOP = frozenset(
    "a an the of to for in on at and or is are was were be been it its my our your his her their this that with from by as "
    "about into up out not no do did does have has had will would can could should please just also then than so if when "
    "now new next last".split()
)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")


def normalize_token(raw: str) -> str:
    """Plural/tense folding so morning/mornings/morning's share a stem."""
    t = _fold(raw)
    t = re.sub(r"['']s$", "", t)
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if len(t) > 5 and t.endswith("ing"):
        stem = t[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        t = stem
    elif len(t) > 4 and t.endswith("ed"):
        stem = t[:-2]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        t = stem
    elif len(t) > 3 and t.endswith("es"):
        t = t[:-2]
    return t


def tokenize(text: str) -> list[str]:
    return [
        normalize_token(part)
        for part in re.findall(r"[A-Za-z0-9\u2019']+", text)
        if _fold(part) not in _STOP
    ]


def phrase_hit(text: str, phrase: str, thresh: float = 0.75) -> bool:
    need = tokenize(phrase)
    if not need:
        return False
    if len(need) == 1:
        return need[0] in set(tokenize(text))
    have = set(tokenize(text))
    return sum(1 for t in need if t in have) / len(need) >= thresh
