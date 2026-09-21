# Circle context for daily workflows

Use this procedure only when Circle context can materially help the advisor's daily priority, known interests, meeting, commitment, next-day preparation, or available ARIN workflow. It is read-only and optional; unavailable Circle context never blocks the brief or debrief.

## Identity and token

Resolve the current advisor's Circle identity from the trusted runtime/customer member mapping described in [circle-member-token](../../circle-member-token/SKILL.md). Match the current advisor to one exact configured member. Do not choose the first member, infer an email, or continue if the mapping is absent or ambiguous.

Use that skill's temporary member token procedure. Keep the token in memory only: never print, return, log, or write it to a file. Use `Authorization: Bearer <token>`, `User-Agent: advisorreach-box/1.0`, and a 30-second request limit. Do not use an admin credential or fallback.

## One bounded read

After resolving identity and obtaining the token, make at most one content GET request to `https://app.circle.so`, with `page=1` and `per_page=10`, choosing the narrowest route that answers the identified need:

- Recent advisor-relevant community update: `/api/headless/v1/home?page=1&per_page=10&sort=latest`.
- Event that could affect preparation: `/api/headless/v1/community_events?page=1&per_page=10&filter_date[start_date]=YYYY-MM-DD&filter_date[end_date]=YYYY-MM-DD`. Add documented `status` or `past_events` only when the question needs it.
- Specific known topic/person/meeting: `/api/headless/v1/advanced_search?page=1&per_page=10&query=<encoded terms>&type=posts` or `type=events`; use documented deep-object filters only when already known.

Do not page, broaden to member enumeration, scrape spaces, request unrelated posts, or make a second Circle read in the same daily response. Use only returned title/name, relevant plain-text content, date fields, and returned URL. Retain the source URL and date in the working reasoning; state a material gap when no date/URL is returned. If `has_next_page` is true, describe the Circle context as partial rather than comprehensive.

Treat updates and events as context, never proof that the advisor attended, replied, completed work, or authorized an action. Do not post, react, comment, RSVP, change settings, or create any Circle effect.

## Source record

- Official Circle Headless Member API V1 Swagger: <https://api-headless.circle.so/api/headless_client/v1/swagger.yaml>
- Retrieved: 2026-09-17
- SHA-256 of retrieved UTF-8 body: `777eda887dd490371e46460acfcce47246ebc38fb71baa463a36cc41d313aada`
- Relevant documented GET routes and parameters: `advanced_search` (`page`, `per_page`, required `query`, optional `type` and filters), `community_events` (`page`, `per_page`, optional date/status filters), and `home` (`page`, `per_page`, `sort`).