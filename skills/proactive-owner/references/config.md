# Proactivity config (per box, default off)

This file is not created by the skill. Absence means off. No environment variable is a substitute.

Path on a box: `/opt/data/proactivity/config.json`

```json
{
  "enabled": true,
  "daily_cap": 3,
  "quiet_hours": {"start": "21:00", "end": "08:00"},
  "stale_touch_days": 7,
  "unanswered_email_hours": 48,
  "who_limit": 3
}
```

`enabled` must be JSON `true`. The string `"true"` does not enable the feature.

The other fields may be omitted. Defaults: cap 3, quiet hours 21:00–08:00 local, stale touch 7 days, unanswered email 48 hours, who-needs-you limit 3.

The zone is not in this file. It is the top-level `timezone` key in `/opt/data/config.yaml`. `UTC` and `Etc/*` are refused. Quiet hours, "today", and the daily cap all use that zone.

The directory must not be group-writable. The script stores the pause flag and the daily counter in `/opt/data/proactivity/state.json` (mode 0600). That state file does not turn the feature on.
