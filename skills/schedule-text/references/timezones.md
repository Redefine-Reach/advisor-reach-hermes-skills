# Local time → UTC cron (US zones)

The box's scheduler runs in UTC. Convert the customer's local clock time to UTC before writing a
cron expression: **UTC hour = local hour + offset** (offsets below are positive numbers; the zone
is *behind* UTC). If the result is 24 or more, subtract 24 and move the day-of-week list one day
later (`1-5` → `2-6`, `1` → `2`, `0` → `1`, `6` → `0`).

Daylight time runs from the second Sunday of March to the first Sunday of November:
2026-03-08 → 2026-11-01, 2027-03-14 → 2027-11-07 (switches at 2:00 AM local).

| Zone (IANA) | What people say | Standard offset (Nov–Mar) | Daylight offset (Mar–Nov) | Area-code hints |
|---|---|---|---|---|
| America/New_York | Eastern, ET, EST/EDT, New York, Florida, Boston, Atlanta | 5 | 4 | 212 917 305 404 617 |
| America/Chicago | Central, CT, CST/CDT, Chicago, Illinois, Minnesota, Texas, Minneapolis, Dallas | 6 | 5 | 312 773 708 630 847 612 651 214 713 |
| America/Denver | Mountain, MT, MST/MDT, Denver, Colorado, Utah, Salt Lake | 7 | 6 | 303 720 801 |
| America/Phoenix | Arizona (no daylight time) | 7 | 7 | 602 480 520 |
| America/Los_Angeles | Pacific, PT, PST/PDT, LA, California, Seattle, Portland, Las Vegas | 8 | 7 | 213 310 415 206 503 702 |
| America/Anchorage | Alaska | 9 | 8 | 907 |
| Pacific/Honolulu | Hawaii (no daylight time) | 10 | 10 | 808 |

Worked examples
- 7:30 AM weekdays, Chicago, in daylight time: 7 + 5 = 12 → `30 12 * * 1-5`
- 7:30 AM weekdays, Chicago, in standard time: 7 + 6 = 13 → `30 13 * * 1-5`
- 8:00 PM every day, Los Angeles, in daylight time: 20 + 7 = 27 → 3, next day → `0 3 * * *` (daily, so the day list is unchanged)
- 9:00 PM Friday, New York, in standard time: 21 + 5 = 26 → 2, day 5 → 6 → `0 2 * * 6`
- "in 20 minutes" → schedule `in 20m` (no conversion, no timezone needed)

Area-code hints are hints only — confirm with the customer once, then keep `User timezone: <IANA>`
in the job prompt so you never have to ask again.
