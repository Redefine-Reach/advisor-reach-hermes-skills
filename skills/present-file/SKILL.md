---
name: present-file
description: Turn a file the agent already has into a shareable public link when the user asks to send, share, or get the file, or when established delivery authority explicitly calls for a public artifact. Do not invoke solely because an SMS reply is long; answer concisely or split safely for the channel. If you already have a public URL for the thing, just return that URL — do not re-host it.
---

# Present File

Give the user a link to a file. The runtime tells you two things through the environment:

- `ARTIFACT_DIR` — a writable directory. Files you place here are served publicly.
- `ARTIFACT_BASE_URL` — the public URL prefix those files are reachable at.

Both are provided to you in your operating context (see your `SOUL.md`). If you cannot find them, tell the user you cannot share files right now — do not guess a URL.

## Procedure

1. Make sure the file exists on disk. If you generated content (e.g. an HTML one-pager), write it to a file first using your file tools.
2. Choose an opaque random filename and retain the original extension. Do not put a client, property, lead, or other sensitive identifier in the filename. Never overwrite an existing artifact; choose a fresh name.
3. Copy the file into `ARTIFACT_DIR` under that name, using your file tools.
4. Reply to the user with exactly the link: `ARTIFACT_BASE_URL` + `/` + the file name. Nothing after the link needs the file path or the directory.

## Long text responses

Keep SMS replies concise. When necessary, let the transport split a focused longer
response safely. Use a public artifact when it suits the requested delivery and
public-sharing authority is already established. Ask only if that authority is
missing. Length alone does not justify creating or publishing a file.

## Rules

- Never expose `ARTIFACT_DIR` or any local path to the user — only the `ARTIFACT_BASE_URL` link.
- One file, one opaque filename, one link. Do not list the directory or expose local paths. The artifact directory is publicly served; use it only when public-sharing authority is established. Never overwrite an existing file.
- If the user already gave you a URL, return that URL unchanged instead of re-hosting.
