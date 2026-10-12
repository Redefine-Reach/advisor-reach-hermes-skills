---
name: advisorreach-site
description: "Edit and publish advisorreach.ai, the AdvisorReach website (team ARIN only): sign in to GitHub through WTTC's OAuth Client, change public/ pages on an arin/* branch, push it, and confirm the release went live. Never pushes production."
---

# advisorreach-site · the ARIN Lane

You can change the public AdvisorReach website, `https://advisorreach.ai`, yourself. Its source is the
GitHub repository `Redefine-Reach/advisorreach-site`; the site is static HTML under `public/`. You push
a branch; GitHub validates it, promotes it to `production` and deploys it (the repo's
`.github/workflows/arin-promote.yml`). You never push `production` yourself.

Use your code tool (Python) for every step; run git with `subprocess.run([...], check=True,
capture_output=True, text=True)` and read `stdout`/`stderr`.

GitHub sign-in: git asks `scripts/git-credential-wttc-oauth.py` (in this skill) for a token on every
HTTPS operation. The helper gets it from the WTTC workspace's GitHub OAuth Client
(`Component Installs/OAuth/GitHub`), signed in as the team machine user `ar-team-arin`, through this
box's OmegaAI connection. Nothing is stored. `ar-team-arin` can push branches to this one site repo and
`advisor-reach-content`, never `production` and never `.github/workflows/`. Never run the helper
yourself and never print its output: its answer is the token.

## 0. Can this box do it?
Check the sign-in first. This prints `username=x-access-token` and `password=(hidden)`; the token is never shown:
```python
import os, subprocess
HELPER = "!python3 /opt/data/skills/advisorreach-site/scripts/git-credential-wttc-oauth.py"
CRED = ["-c", "credential.https://github.com.helper=", "-c", "credential.https://github.com.helper=" + HELPER]
check = subprocess.run(["git", *CRED, "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True)
ok = check.returncode == 0 and "username=x-access-token" in check.stdout
reason = "" if ok else check.stderr.strip().splitlines()[-1] if check.stderr.strip() else "no answer"
```
If `ok` is False, stop and reply with `reason`:
- `git-credential-wttc-oauth: oauth/NotConnected`, `oauth/TokenExpired` or `oauth/BadState`: WTTC's GitHub
  sign-in needs Ryan. Say so; he signs in as `ar-team-arin` from the OAuth Client's `get-auth-url` link.
- `git-credential-wttc-oauth: omega/mcp/NoKey`: this ARIN is not connected to OmegaAI, so it cannot edit
  advisorreach.ai.
- anything else: give the team the line as it is.
Do not look for another key or token.

## 1. Get a clean branch from production
Name the change first. `TOPIC` is today's date (UTC, YYYYMMDD) and two to four lowercase words joined by
hyphens; `MESSAGE` is one line saying what changed and why. Set both before running anything below:
```python
import subprocess, os, time
TOPIC = time.strftime("%Y%m%d", time.gmtime()) + "-scorecard-eyebrow"   # your words after the date
MESSAGE = "Scorecard page: eyebrow reads Free for real estate advisors (team request)"   # your one line
BRANCH = "arin/" + TOPIC
REPO = "/opt/data/repos/advisorreach-site"
URL = "https://github.com/Redefine-Reach/advisorreach-site.git"
def git(*args):
    return subprocess.run(["git", *CRED, "-C", REPO, *args], check=True, capture_output=True, text=True).stdout.strip()
if not os.path.isdir(os.path.join(REPO, ".git")):
    os.makedirs("/opt/data/repos", exist_ok=True)
    subprocess.run(["git", *CRED, "clone", URL, REPO], check=True, capture_output=True, text=True)
git("fetch", URL, "+refs/heads/production:refs/remotes/origin/production")
git("checkout", "-B", BRANCH, "refs/remotes/origin/production")
```

## 2. Read the rules, then edit only public/
Before changing any words, read `AGENTS.md`, `PRODUCT.md` and `DESIGN.md` in the repo. They bind you
exactly as they bind every other writer. The ones that most often matter:
- ARIN is always written ARIN. Never write "Aaron". Never write HERMES or REDEFINE on a public page.
- No promise of leads, rankings or revenue. Sample numbers are labeled illustrative.
- Prices appear only on `/pricing/` and `/terms/`.
- Change files under `public/` only. A branch that touches anything else is refused before validation.
- A Lead Magnet page (your `lead-magnets` skill) goes at `public/m/<name>/index.html`, one folder per
  magnet. `tests/brand-system.test.mjs` accepts every page under `public/m/` on its own, so it needs no
  route edit. Any other new page needs its route added to a list in `tests/brand-system.test.mjs`. That
  file is outside `public/`, so ask the team to add that route (the ARIN Lane cannot change it).

## 3. Check locally, commit, push the branch
```python
subprocess.run(["node", "--test", "tests/internal-public-links.test.mjs", "tests/public-copy-contract.test.mjs"],
               cwd=REPO, check=True, capture_output=True, text=True)
git("add", "--all", "public")
git("-c", "user.name=ARIN (team)", "-c", "user.email=arin@advisorreach.ai", "commit", "-m", MESSAGE)
sha = git("rev-parse", "HEAD")
git("push", URL, "HEAD:refs/heads/" + BRANCH)
```
If the node check fails, read its output, fix the page and run it again. Do not push a failing branch.

## 4. Confirm it went live (this takes 15–40 minutes)
Validation runs the repository's full check (`scripts/validate.sh`). Then production moves to your
commit and the site deploys. Confirm both, in this order, checking every 2 minutes for up to 45 minutes:
```python
import json, time, urllib.request
def production_sha():
    out = subprocess.run(["git", *CRED, "ls-remote", URL, "refs/heads/production"], check=True, capture_output=True, text=True).stdout
    return out.split()[0] if out else ""
def live_sha():
    with urllib.request.urlopen("https://advisorreach.ai/release-identity.json", timeout=20) as r:
        return json.load(r).get("commitSha", "")
```
- `production_sha() == sha` means validation passed and production moved.
- `live_sha() == sha` means the new site is serving. Only then tell the team it is live.
- If production has not moved after 45 minutes, say the promotion did not complete and give the team
  `https://github.com/Redefine-Reach/advisorreach-site/actions/workflows/arin-promote.yml`. Do not push again
  until someone has read why.

## 5. Undo
To take a change back, start a new branch from production (step 1, with `TOPIC` = today's date + `-revert-` + the old topic's words), run
`git("revert", "--no-edit", sha)`, and go through steps 3 and 4 again.

## Rules
- Never push `production`, never force-push, never delete a branch you did not create. GitHub refuses
  `production` and `.github/workflows/` from `ar-team-arin` anyway (repository rulesets).
- Never run `git-credential-wttc-oauth.py` or `get-token` yourself, and never print a token.
- Never put a secret, a customer's name or customer data on a public page.
- Never tell anyone a change is live before `live_sha() == sha`.
