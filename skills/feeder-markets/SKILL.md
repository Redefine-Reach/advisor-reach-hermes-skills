---
name: feeder-markets
description: "Feeder markets: migration report, scored ZIPs, agent CSV. Use when asked where movers to a market come from, for a feeder-market or migration report, feeder ZIP codes, or a list/CSV of referral agents in those markets (OmegaAI-connected boxes only)."
required_environment_variables:
  - MCP_QUERY_OMEGA_API_KEY
---

# Feeder markets (migration report → scored ZIPs → referral-agent CSV)

Referral partners are real-estate agents in the markets that SEND movers to the user's market.
When one of their clients relocates, the agent refers the client to the user for a fee. Agents in
the user's own market are competitors — never pull them.

This skill has three parts. Parts 1 and 2 run here on this box. Part 3, the agent list, is pulled
by **Cas**, the OmegaAI in-app agent, inside this box's OmegaAI workspace — you hand her the job
with one script and collect her link. Everything goes through scripts with these exact absolute
paths (`$HERMES_HOME` is scrubbed from the sandbox; `/opt/data` is its value on every box). Every
script prints ONE JSON object.

**Run each command below as ONE plain command** — in your terminal, or as a subprocess from
code execution, whichever you have. Never wrap it in `$(…)`, never chain with `&&` or `;`, never
put `VAR=` in front: the terminal rejects compound commands. When a command needs a value from a
file (the ZIP line), read the file with your file tool first and type the value into the command.

## 0. The destination (one question at most)
You need the user's market as a **county and state** — the IRS publishes migration by county.
Map a city to its county yourself when it is unambiguous (Orlando → "Orange County, FL";
Phoenix → "Maricopa County, AZ"; Scottsdale → "Maricopa County, AZ"). If the user names a metro
that spans several counties and does not say which, ask ONE question: "Which county should I
use for <metro>?" Then go.

Work directory: `/opt/data/work/feeder-markets/<slug>` where `<slug>` is the county and state,
lowercase, spaces as hyphens, e.g. `orange-county-fl`.

## 1. Analyze (about 10 seconds; downloads public data the first time)

    python3 /opt/data/skills/feeder-markets/scripts/feeder_markets.py analyze --dest "Orange County, FL" --out /opt/data/work/feeder-markets/orange-county-fl --cache /opt/data/work/feeder-markets/cache

It ranks the out-of-state counties that sent the most income to the destination (IRS
county-to-county migration, 2022–2023), finds the affluent ZIP codes in each (IRS income by ZIP,
2022), scores them, and writes `summary.json`, `feeders.json`, `zips.json` and `zips-ab.txt`
(the Tier A and B ZIPs, best first, one line). Options: `--feeder-counties 20`,
`--zips-per-county 5`, `--max-zips 40`, `--min-returns 500`, `--include-in-state` (only when the
user asks for in-state movers too). If it prints `"ok": false`, tell the user the `error`
text as it is.

## 2. The report (a PDF link)

    /opt/hermes/.venv/bin/python /opt/data/skills/feeder-markets/assets/render.py /opt/data/work/feeder-markets/orange-county-fl /opt/data/work/feeder-markets/orange-county-fl/report.pdf

Then give the user the PDF with the `present-file` skill. With the link, text the top five
feeder counties and the Tier A/B/C counts from the analyze output — nothing you did not read
there. Never invent a figure and never add counties or ZIPs the script did not return.

## 3. The referral-agent CSV (Cas pulls it in OmegaAI)
Run this when the user asks for the agents, a lead list, or the CSV — or offer it after the
report ("Want the agent list for the Tier A and B ZIPs?"). The default cap is 5000 agents; use
another number only when the user gives one.

    python3 /opt/data/skills/feeder-markets/scripts/cas_pull.py start --zips "<the line from zips-ab.txt>" --max-agents 5000

→ `{"ok": true, "session": "ses_..."}`. Tell the user in one line that the list is being pulled
and takes a few minutes. Then run, and repeat while it prints `"status": "running"`:

    python3 /opt/data/skills/feeder-markets/scripts/cas_pull.py wait --session ses_...

- `"status": "done"` → reply with the `link` and the `agents` count. The link is already public:
  give it as it is, do not re-host it.
- `"status": "failed"` or `"ok": false` → tell the user the `error` text as it is. Do not pull
  the agents another way.
- Each `wait` returns within about four minutes. After six `wait` calls that still say
  `"running"`, tell the user the pull is still going and that you will send the link when it
  finishes; run `wait` again when they ask.

The CSV has one row per agent: `Query ZIP` (the ZIP that returned the agent) then Agent, Company,
Email, Name, Phone, profile link, city, state and the rest. A ZIP returns every agent in its
city, so ZIPs from the same city do not add agents twice.

## Rules
- Only out-of-market ZIPs go to Cas — never ZIPs in the user's own county or state unless they
  asked for in-state movers.
- Never show a local path, the OmegaAI key, or Cas's session id to the user.
- If a script says `MCP_QUERY_OMEGA_API_KEY is not set`, this box is not connected to OmegaAI:
  tell the user the agent list needs an OmegaAI connection; the report (parts 1–2) still works.
