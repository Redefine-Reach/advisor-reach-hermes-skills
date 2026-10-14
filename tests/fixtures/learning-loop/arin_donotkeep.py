"""Test double for /opt/box/arin_donotkeep.py on_pre_tool_call.

This is not the box gate. Unit tests point ARIN_DONOTKEEP_PY here so the
learning-loop script exercises the same call it makes on a box: a memory
add, a judge verdict, and a block message that prevents the write.
"""


class Gate:
    def __init__(self, message, kind):
        self.message = message
        self.kind = kind


BUILTIN = {
    "health": "I won't save health details.",
    "ssn": "I won't save Social Security numbers.",
    "account": "I won't save financial account numbers.",
}
COULD_NOT_SAVE = "I couldn't save that right now."
NOT_SAVED = "Not saved: this matches a do-not-keep rule."
ON = {"1", "true", "yes", "on"}


def on_pre_tool_call(tool_name, args=None, *, env=None, model=None, home=None):
    del home
    src = env or {}
    if str(src.get("BOX_DONOTKEEP") or "").strip().lower() not in ON:
        return Gate(None, "allow")
    if tool_name != "memory" or not isinstance(args, dict):
        return Gate(COULD_NOT_SAVE, "error")
    if str(args.get("action") or "") != "add":
        return Gate(COULD_NOT_SAVE, "error")
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        return Gate(COULD_NOT_SAVE, "error")
    if model is None:
        return Gate(COULD_NOT_SAVE, "error")
    try:
        verdict = model(content, [])
    except Exception:
        return Gate(COULD_NOT_SAVE, "error")
    if not isinstance(verdict, dict) or set(verdict) != {"block", "category"}:
        return Gate(COULD_NOT_SAVE, "error")
    block = verdict.get("block")
    category = verdict.get("category")
    if not isinstance(block, bool) or not isinstance(category, str):
        return Gate(COULD_NOT_SAVE, "error")
    label = category.strip().lower()
    if label in BUILTIN:
        return Gate(BUILTIN[label], "rule")
    if block:
        return Gate(NOT_SAVED, "rule")
    return Gate(None, "allow")
