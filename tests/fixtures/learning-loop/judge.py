"""Test judge. The product script has no word list; this file does."""

import re

SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
ACCOUNT = re.compile(r"\b\d{8,17}\b")


def judge(candidate, rules):
    del rules
    text = str(candidate or "")
    folded = text.casefold()
    if any(word in folded for word in ("surgery", "diagnosis", "prescription", "medical")):
        return {"block": True, "category": "health"}
    if "social security" in folded or "ssn" in folded or SSN.search(text):
        return {"block": True, "category": "ssn"}
    if "account number" in folded or "routing number" in folded or ACCOUNT.search(text):
        return {"block": True, "category": "account"}
    if folded.startswith("block-rule"):
        return {"block": True, "category": "business"}
    return {"block": False, "category": "business"}
