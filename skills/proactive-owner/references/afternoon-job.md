# Afternoon follow-up job

This file is the job shape. It is not installed by this repo. Do not add it to the sms-box chart, a Helm value, or an environment variable. A later change on a named box, after that box has a real IANA `timezone` in `config.yaml` and after `proactivity/config.json` has `"enabled": true`, creates it with `hermes cron` only when the owner has explicitly asked.

- name: `afternoon-follow-up`
- schedule: `0 15 * * 1-5` as local wall time. Do not convert the expression to UTC. The box zone has to be set first, or 15:00 is 15:00 UTC.
- deliver: origin, the owner thread. Never a client number, never `sms-send-confirmed`.
- failure_deliver: `local`
- skills: `proactive-owner`
- pre-script: `python3 /opt/data/skills/proactive-owner/scripts/proactive.py gate --kind nudge --pre-script`
- The pre-script prints `{"wakeAgent": false}` (with a reason) when the file is off, quiet is set, quiet hours apply, the daily cap is spent, or the zone is missing. That skips the model.
- Prompt, self-contained:

```
User timezone: <IANA from config.yaml>
Load proactive-owner. Build the candidates file from bounded FUB/GHL, unanswered known-client email, and today's calendar. Run nudge. Your entire final response is the text field. If it is [SILENT], output exactly [SILENT] and nothing else. Do not text a client. Do not call sms-send-confirmed. Do not stage a draft. Prepare, never send or write.
```

The morning brief does not need a second job. Its existing Brief Job should gain the same kind of pre-script with `--kind brief`, and `proactive-owner` on its skills list, so the daily cap and quiet hours apply before the model runs. "Who needs you today" is a section inside that brief, not a separate text.

Do not create either change from this repository.
