# Bugbot review rules: advisor-reach-hermes-skills

Flag as blocking:

- Removal or bypass of the `sms-send-confirmed` SEND gate. That includes treating a vague "yes", "go ahead", or "send it" as `SEND` or `/approve`, sending without the staged authorization line, sending more than one message per confirm, or any path that auto-sends.
- Real phone numbers, email addresses, or customer names in code or fixtures. Contacts in tests and examples must be synthetic.
- Secrets in code, including API keys, tokens, and runtime env files.
- New outbound network calls to services this repository does not already use.
- Gmail, Follow Up Boss, or GoHighLevel writes that skip the confirmation step that skill already requires: Composio explicit authorization for that action and account, Follow Up Boss `--confirm-write` only after a yes and only on the allowlist, and a yes before any GoHighLevel `POST`, `PUT`, `PATCH`, or `DELETE`.
- SmartLead campaign creates, schedules, or starts, or email-outreach orders, that skip the explicit yes those skills require.
