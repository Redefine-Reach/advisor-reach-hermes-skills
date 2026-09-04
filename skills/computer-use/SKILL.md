---
name: computer-use
description: Use when a task needs to control a desktop GUI directly — take a screenshot of the screen, move or click the mouse, type on the keyboard, or drive a native (non-web) application. Prefer the browser tools for anything on a web page; use this only for the actual desktop/GUI.
---

# Computer Use

You can control a **local virtual desktop** on this box via the `computer_use` tool (backed by `cua-driver`
against an X11 display running here). It is **local**, not a cloud service. It can take screenshots, move and
click the mouse, type, and press keys — the same actions a person at a screen would take.

## When to use it (and when NOT to)

- Use `computer_use` ONLY for the actual desktop: screenshot the screen, click/type in a native app window,
  drive a GUI that is not a web page.
- For anything on a **web page** (open a URL, read a site, log in, fill a web form), use your **browser**
  tools instead — they are faster and more reliable than driving a browser through the desktop.
- Never try to control the desktop with `execute_code` / shell / X commands directly — `computer_use` is the
  sanctioned and only path.

## Procedure

1. **Capture** first to see the current screen — never act blind. Prefer `action='capture'` with
   `mode='som'`: it returns numbered overlays on every interactable element plus the accessibility tree, so
   you can **click by element index** rather than guessing coordinates.
2. Decide the single next action and target it by **element index** (preferred) or, if none is available, a
   pixel coordinate.
3. Do ONE action, then capture again to confirm the result before the next action.

## Rules

- The desktop is **local and virtual** (a headless X server + a minimal XFCE session on this box). It shows
  the XFCE shell (panel + wallpaper) but **no application windows until one is launched** — launch an app
  (e.g. from the panel or a terminal) before expecting to drive it. Do not assume a full desktop of apps.
- **Drive by element index / accessibility tree, not by "looking" at the picture.** This box's model may be
  text-only: the screenshot is still captured and control works, but you cannot rely on visually reading the
  image. Use `mode='som'` (numbered elements) or `mode='ax'` (tree only) and act on element indices.
- **On a tool error, STOP — do not improvise.** You get at most ONE corrected retry, and only when the error
  names a field you clearly omitted. Never retry the same call repeatedly, never vary arguments to see what
  sticks, never fall back to `execute_code`/shell/X to do it another way, and never probe the platform to
  diagnose it. If `computer_use` will not work, a HUMAN must fix the setup — report the exact error text and
  stop. If you have made more than 3 tool calls without forward progress, stop even if nothing errored.
