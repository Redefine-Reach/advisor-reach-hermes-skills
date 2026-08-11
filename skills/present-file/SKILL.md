---
name: present-file
description: Turn a file the agent already has into a shareable public link and return that link. Use when the user asks to "send", "share", or "get me" a file, PDF, image, or document over text, or whenever you have produced a file (an HTML one-pager, a PDF, an image) and need to hand the user a URL to it. If you already have a public URL for the thing, just return that URL — do not re-host it.
---

# Present File

Give the user a link to a file. The runtime tells you two things through the environment:

- `ARTIFACT_DIR` — a writable directory. Files you place here are served publicly.
- `ARTIFACT_BASE_URL` — the public URL prefix those files are reachable at.

Both are provided to you in your operating context (see your `SOUL.md`). If you cannot find them, tell the user you cannot share files right now — do not guess a URL.

## Procedure

1. Make sure the file exists on disk. If you generated content (e.g. an HTML one-pager), write it to a file first using your file tools.
2. Give the file a clear, human-readable name based on its content — hyphenate spaces so the link is clean, and keep the original extension. Example: 'Pre-Listing-Packet-Anderson.pdf'. Make it distinctive enough (include the client, property, or date) not to overwrite a different file already served.
3. Copy the file into `ARTIFACT_DIR` under that name, using your file tools.
4. Reply to the user with exactly the link: `ARTIFACT_BASE_URL` + `/` + the file name. Nothing after the link needs the file path or the directory.

## Rules

- Never expose `ARTIFACT_DIR` or any local path to the user — only the `ARTIFACT_BASE_URL` link.
- One file, one clear human-readable name, one link. Do not list the directory. Reuse of the exact same name overwrites the previous file — keep names distinctive.
- If the user already gave you a URL, return that URL unchanged instead of re-hosting.
