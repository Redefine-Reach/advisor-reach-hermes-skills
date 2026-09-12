---
name: gbp-scorecard
description: "Use when asked for a GBP report, GBP playbook, digital + AI scorecard, visibility scorecard, or 'does her/his name come back on Google' briefing for a named real-estate advisor. Produces the Public-source briefing PDF (bio, 24-month production as published, 15 platform scores, Google Business Profile field-by-field, 90-day game plan) and returns a link via present-file."
---

# GBP Scorecard · Playbook (public-source briefing → PDF link)

You produce a four-page "Digital + AI Scorecard · GBP Playbook" for ONE named real-estate advisor, from public sources only, and hand back a link. The layout is LOCKED (`assets/template.html`); you supply the research, the scores, and the plan as small JSON files, and `assets/render.py` builds the PDF. You never edit the template.

## 1. Clarify first (one question, then go)
You need: the advisor's full name AND their market city (metro). Brokerage is optional but ask for it when the name is common.
- If the request has a name but no city or brokerage → ask ONE question and stop: "Which city/market and brokerage is <name> with?"
- If it has a name and a city → proceed. Confirm the brokerage during research.
- Never guess which person is meant. If research finds two plausible advisors, stop and ask which one.
- The state license board is the identity of record. If the board's CURRENT employer/brokerage differs from what the user told you (advisors move), do not blend the two and never write "concurrently": use the board's employer as the brokerage throughout (header, bio, NAP, GBP business name), and open the `verdict` with one plain sentence noting the move (e.g. "The license record shows a move to <board brokerage> on <date>; this briefing is written for that affiliation.").

## 2. Research protocol (Exa web search + web extract; browser only if a page will not extract)
Work through this checklist IN ORDER. For every item record: found / not found, the URL, the retrieval date (today), and the facts. A missing source is a finding ("not found on <source>, <date>"), never an invented fact.
1. **State real-estate license board** — the identity of record; do this FIRST and do not proceed until it resolves or you have three failed queries. Run these in order until one returns a board page: (a) `site:<board-domain> "<First>" "<Last>" license` (Arizona: `site:services.azre.gov`; California: `site:dre.ca.gov`; Texas: `site:trec.texas.gov`; Florida: `site:myfloridalicense.com`; otherwise search `"<state>" real estate license lookup` to learn the domain first); (b) `"<First> <Last>" real estate license <state> "<license-prefix>"` (Arizona uses SA/BR); (c) `"<First> <Last>" "<brokerage>" license <state>`. A board result is often the EMPLOYER's entity page listing the advisor in an employee table — that row still gives license number, type, hire date and expiry; then `web_extract` the individual license page if linked. Capture: license number, type, original/issue date, expiry, current employer legal name + DBA, hire date, designated broker, discipline. Search: `"<name>" real estate license <state>`.
2. **Brokerage site + advisor directory** — the shop's own page for the advisor (bio, photo, phone, office addresses). Search: `"<name>" "<brokerage>" <city>`.
3. **Shop-level cards — search by BROKERAGE NAME, not the advisor's name**: (a) `"<brokerage>" <city> site:ratemyagent.com` → sold count LTM, volume, actives; (b) `"<brokerage>" <city> google reviews rating` → the shop's Google/Birdeye rating and review count and every address variant in circulation; (c) `"<brokerage>" <city> instagram "top producer"` and `"<brokerage>" <city> instagram "<Last>"` → shop posts that tag the advisor (awards, handles); (d) `"<brokerage>" <city> advisor directory` → the shop's own agent list (confirms affiliation and reveals same-name colleagues); (e) franchise rankings: `"<brokerage>" "T3 Sixty" OR "RealTrends 500"`.
4. **Recognition**: shop Instagram/Facebook posts naming the advisor (Top Producer, awards), local trade press (e.g. "<city> Agent Magazine" rookie/finalist lists). Search: `"<name>" top producer <brokerage>`, `"<name>" "rookie of the year" <city>`.
5. **Listings**: capture 1–2 concrete addresses with list price. Queries: `"listed by <First> <Last>"`, `"<First> <Last>" listing site:zillow.com`, `"<First> <Last>" site:realtor.com`, `"<First> <Last>" site:homes.com`, `"<First> <Last>" "<brokerage>" MLS listing <city>`. If none surfaces, the row says "no public listing found (Exa, <date>)".
6. **Portal agent cards**: Zillow, Realtor.com, Homes.com agent profile — reviews count, rating, sales count if shown.
7. **Rankings**: RealTrends Verified / America's Best card under the name. Search: `"<name>" realtrends`.
8. **Social**: Instagram, YouTube, TikTok, Facebook, X, LinkedIn handles under the name + brokerage. Note follower/post cadence only if visible in results.
9. **Reviews**: personal Google reviews (Maps card under the advisor's name), Zillow reviews, any client testimonial on a colleague/brokerage page.
10. **Homonym check**: search the bare name (`"<name>"`) and note any Wikipedia/IMDb/other-profession collisions on the first page, and any same-name person at the same brokerage.
11. **Website**: a personal or brokerage microsite under the name (search `"<name>" realtor site:<brokerage-domain>` and `"<name>" <city> real estate website`).
12. **Press**: local newspaper / luxury magazine / TV mentions in the advisor's name.

Do all searches with the built-in web search (Exa). Use web extract on a result only when you need a specific field (license dates, review counts). If a page blocks extraction, record "page did not extract" and move on — do not open the browser unless a single decisive fact (license number) is otherwise unobtainable.

## 3. Score (0–10) — the rubric
Each row is scored against **what produces a first-call recommendation for luxury in <market> in <current year>**:
- **10** = Google and AI assistants name this advisor first for luxury in this market.
- **8** = strong, owned, current; needs maintenance not building.
- **5** = exists and is doing part of the job.
- **3** = the channel exists or could exist; it is not doing the job yet.
- **1** = nothing found.
- Use halves (e.g. 3.5). **Anything 8.0 or below gets a comment AND a place on the calendar** in §5.
Two rows cannot be observed from here — **Google category search** and **AI assistants** (you cannot run a live Google Maps pack query or ask three chatbots). Score them by INFERENCE from the citable corpus you found (a named page that ranks, a review body, structured bios, press) and write `exists` as an inference ("no citable corpus in her name → an assistant has nothing to quote"), never as an observation ("ChatGPT does not return her"). The same applies to Maps pack presence. Score against first-call power, not page existence: a personal website that does not appear on page one for the bare name is ≤ 4.0; a LinkedIn with no posting cadence is ≤ 3.5; a portal card with zero reviews is ≤ 3.0; an Instagram account that the shop tags but that is not itself an authority feed is 4.0–5.0, not 2.0.
Score these 15 channels, in this order and with these names (the template expects exactly 15 rows):
Google branded search (their name) · Google category search (luxury realtor <city>) · Google Business / Maps — personal · Google Business — shop listings · AI assistants · Instagram · YouTube · TikTok / Reels discovery · Facebook · X / Twitter · LinkedIn · Zillow / Realtor.com / Homes.com · Website / microsite · PR / print / local media · Review density.
For each: `exists` = what you actually found (one or two sentences, name the source), `means` = what that implies for a buyer who asks "who should I call?" (one or two sentences).
Then score these GBP fields, in this order (exactly these 16 rows; use "N/A" where noted):
Personal profile claimed · Shop listings claimed · Business name · Categories · Description / About · NAP · Hours · Photos / video · Services · Posts (the GBP "blog") · Q&A · Reviews — rating · Reviews — volume · Owner replies · Google Screened (always "N/A" — home-service trades only) · Products (always "N/A" — houses may not be listed as Products).
For each: `see` = what is visible today, `lift` = the concrete fix (numbers where possible: photo counts, post cadence, review targets). Keep every table cell to at most two sentences and 220 characters (`exists`, `means`, `see`, `lift`, `record`, `read`, `today`, `day90`) — the briefing is four pages, not six. Bio paragraphs ≤ 90 words each.
Tiles: `overall` = unweighted mean of the 15 channel scores, one decimal; `known_name` = the Google branded search score; `open_demand` = the Google category search score; `ai_citation` = the AI assistants score. In `channels_note`, also give the weighted read (weight open-demand, video, AI, reviews) in one sentence.

## 4. Write like the briefing
Short declaratives. Distinguish shop vs personal in every row. Date-stamp retrievals. Name what is NOT published (the "Honest line on volume" paragraph must say whether closed sides / dollar volume for 24 months are public, and how the broker could close that gap). End `sources` with "Scores are analyst judgments on public evidence." Never invent a number.

## 5. Plan — everything at 8 or below
`plan.intro`: one paragraph — 90 days, the advisor is the voice, a coordinator runs the calendar, presence is built in five rooms (named webpage, personal GBP, reviews, short video, one reporter), do not open every channel at once.
`week0` (one working day), `weeks1_2`, `weeks3_6`, `weeks7_12`: 4–6 bullets each, every bullet derived from a sub-8 row above, with numbers (photo counts, post cadence, review targets, film lengths). Week 0 must include: stand up the named personal webpage (schema, license, markets, one sold/listed story); create/verify the personal GBP; ask the broker to freeze the shop NAP to ≤ 2 live addresses and claim RateMyAgent; claim Zillow/Realtor/Homes.com agent records; pull the 24-month MLS closed export from the broker. Weeks 1–2 must include the photo/video day, GBP photo upload + 12 Q&As, the YouTube channel, the review QR/text ask, and the Instagram cadence. Weeks 3–6 must include GBP Posts 2×/week, a YouTube film every other week cut into Shorts, LinkedIn 1×/week, shop Facebook boosts into the market's ZIPs, and monthly review asks with Zillow in parallel. Weeks 7–12 must include a monthly 700-word market note on the webpage, one press pitch to a named local outlet, best-of/award submissions, and a day-45 audit.
`targets`: 5–8 rows of Signal / Today / Day-90 target (reviews, personal GBP, named webpage, YouTube, known-name score, open-demand score, 24-month volume on the public web).
`donts`: 3–5 bullets — always include: do not buy reviews; do not list houses as GBP Products; do not merge the advisor into the shop listing; do not chase 20-year incumbents on "best luxury agent <city>" first; if there is a homonym, how to separate from it.

## 6. Emit the report as SECTION FILES (never one big JSON)
Create `$HERMES_HOME/work/gbp/<first-last>/` (`<first-last>` = the advisor's first and last name, lowercase, joined by one hyphen, ASCII only — e.g. `jane-doe`) and write these 13 files with your file tool, one at a time (small files render reliably; one giant JSON does not):
`meta.json` {name, brokerage, market, market_short, date_long, headline, subline} · `tiles.json` {overall, known_name, open_demand, ai_citation} · `verdict.json` "…" · `bio.json` ["…","…"] · `production.json` {rows:[{signal,record,read}…], honest_line} · `how_scored.json` "…" · `channels.json` [{name,score,exists,means}×15] · `channels_note.json` "…" · `gbp.json` {intro, rows:[{field,score,see,lift}×16]} · `plan.json` {intro, week0:[], weeks1_2:[], weeks3_6:[], weeks7_12:[]} · `targets.json` [{signal,today,day90}…] · `donts.json` [] · `sources.json` "…".
`meta.headline` is a question in the form "When a luxury buyer asks who to call in <city>, does <her/his> name come back?"; `meta.subline` says what the briefing contains; `meta.market_short` is like "Scottsdale luxury"; `meta.date_long` is like "11 September 2026".
The exact shapes are in `assets/schema.json` (read it). `assets/fixture/` holds a complete example set with fictional data — copy its SHAPE, never its content.

## 7. Render
Run: `/opt/hermes/.venv/bin/python <this-skill-dir>/assets/render.py "$HERMES_HOME/work/gbp/<first-last>" "$HERMES_HOME/work/gbp/<first-last>/report.pdf"`
(`<this-skill-dir>` is the directory this SKILL.md lives in — `$HERMES_HOME/skills/gbp-scorecard`.)
If it prints `render.py: report invalid at /<path>: …` — fix THAT section file and rerun. If it prints `missing section file(s)` — write the missing file. Never edit `template.html` or `schema.json`.
Verify: `pdfinfo "$HERMES_HOME/work/gbp/<first-last>/report.pdf" | grep Pages` shows 3–5 pages.

## 8. Deliver — ALWAYS via the present-file skill
Invoke the `present-file` skill on `$HERMES_HOME/work/gbp/<first-last>/report.pdf`, named `<First>-<Last>-<Brokerage-Short>-Scorecard-Playbook.pdf`, and reply with just the link plus the four tile numbers in one line. If present-file reports it cannot share files right now, say so and give the four tile numbers and the top three Week-0 actions instead.
