---
name: listing-presentation
description: "Generate a seller's pre-listing packet as a PDF and give the user a shareable link. Use when asked to make a listing packet, pre-listing packet, listing presentation, or seller presentation for a property/address. It fills a locked branded template with the advisor + property details gathered over the conversation, renders it to PDF, and returns a link via the present-file skill."
---

# Listing Presentation (pre-listing packet → PDF link)

Produce the AdvisorReach pre-listing packet as a PDF and hand the user a link. The packet's copy and design are LOCKED — you only supply the per-client details. Never rewrite the packet's body.

## 1. Gather the details (ask only for what's missing)
- Advisor: name, phone, email, Calendly link, brokerage/brand name.
- Client / sellers: name(s).
- Property: full address.
- Property story: 2–3 sentences (home type, price segment, standout features, location character).
- 4 buyer personas (property-specific, e.g. "Ski-in/ski-out second-home buyer").
- 5–6 niche buyer channels (e.g. luxury, waterfront, physician, C-suite, golf).
- (Stat block defaults to 4 buyer profiles / 9 CMA comps / 3 direct-mail letters / 6 niche channels — leave unless told otherwise.)

## 2. Fill the template
Read `assets/pre-listing-packet.html` (it lives next to this skill). Write a filled copy to `$HERMES_HOME/work/packet.html` (`$HERMES_HOME` is your home dir; create the `work` dir), substituting EXACTLY these tokens and nothing else:
- `{{brand}}` — the advisor's team/brand (e.g. "Ray Lopez Team").
- `{{advisor_name}}`, `{{advisor_phone}}`, `{{advisor_email}}`, `{{advisor_calendly}}`.
- `{{client_names}}`, `{{property_address}}`.
- `{{buyer_descriptor}}` — a short phrase for the buyer types this home attracts, derived from the property story + the 4 personas (e.g. "the luxury lakefront relocation and move-up buyers").
- `{{niche_channels}}` — the niche channels as a short comma-list (e.g. "Luxury, waterfront, physician, C-suite & equestrian").
Do not change any other text, structure, or styling, and leave no `{{token}}` unfilled — if a detail is unknown, ask rather than invent.

## 3. Render to PDF
Run: `weasyprint "$HERMES_HOME/work/packet.html" "$HERMES_HOME/work/packet.pdf"`
If it errors, read the error and fix the HTML you wrote (usually an unclosed tag) — do not alter the template's design.

## 4. Deliver — ALWAYS via the present-file skill
Do NOT hand the user a local path, and do NOT name or serve the file yourself. **Invoke the `present-file` skill** (in this same skills set) on `$HERMES_HOME/work/packet.pdf` — it names the file (e.g. `Pre-Listing-Packet-<client>.pdf`) and returns the public link. Reply with just that link.
