# AdvisorReach Hermes Skills

Public, portable skills in the open `SKILL.md` format — usable by Hermes, Claude Code,
Codex, Cursor, and any SKILL.md-compatible agent.

## Install
```
npx skills add Redefine-Reach/advisor-reach-hermes-skills
```
Or add as a Claude Code plugin marketplace: `/plugin marketplace add Redefine-Reach/advisor-reach-hermes-skills`.

## Skills
### present-file
Turns a file the agent already has into a shareable public link. The host runtime injects
two env vars the skill reads:
- `ARTIFACT_DIR` — writable dir whose contents are served publicly.
- `ARTIFACT_BASE_URL` — public URL prefix for those files.
The skill copies the file into `ARTIFACT_DIR` under a random name and returns `ARTIFACT_BASE_URL/<name>`.
