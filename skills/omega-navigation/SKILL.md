---
name: omega-navigation
description: Use when you have the query-omega OmegaAI MCP tools and need to find your bearings in a workspace — establishes the standard entry convention (list workspaces, pick the active one, ls the root, read the root README and follow its links).
---

# Omega Navigation

## When to use

Whenever you have the `query-omega` MCP tools (`list_workspaces`, `ls`, `get`, `read`, `write`, etc.) available and need to orient yourself in an OmegaAI workspace — at the start of a session, when you're unsure what a workspace contains, or when you've lost context on where things live.

## The entry convention

1. **List workspaces.** Call `list_workspaces` to see the workspaces you have access to and which one is currently active.
2. **Pick the active workspace**, unless the user has clearly asked you to work in a different one.
3. **List the root.** Call `ls` with no `page_path` (i.e. at the workspace root) to see the top-level pages.
4. **Read the root README.** Open the `README` page at the workspace root (`read "README"`). This is the canonical operator entry point and index — every workspace keeps one, and it links out to everything else (guides, notes, per-area "Skills" pages). If there is genuinely no root `README`, fall back to a `Notes/README` or the first child under `Notes`.
5. **Follow its links.** From the root `README`, follow the links and structure it describes, using `ls` and `read` to reach guides, `Skills/…` pages, and data.

## Conventions

OmegaAI workspaces are trees of pages addressed by slash-delimited paths (e.g. `Notes/README`, `Component Installs/some-package`). A few conventions hold across most workspaces:

- **Folder pages** contain sub-pages — `ls` on a folder page lists its children.
- **Database pages** hold rows. Before you `describe` or `query` a database page, check its `primary-key` so you understand how rows are identified.
- **The operator entry point is the root `README`**, which links to `Notes/` and any `Skills/…` guide pages. Documentation and notes live under `Notes/`; operator guides for a specific area live under `Skills/<area>/`.
- **Structured data** lives under dedicated database pages, not under `Notes/`.
- **Component installs** live under `Component Installs/`.

These are conventions, not guarantees — always confirm with `ls`/`get` rather than assuming a path exists.

## Hard rules

- **Read before you write.** Never write to or modify a page you have not first read or listed.
- **Never fabricate a page path.** If you don't know whether a path exists, `ls` the parent to discover it — don't guess.
- **One workspace at a time**, unless the user explicitly tells you to work across multiple workspaces.
