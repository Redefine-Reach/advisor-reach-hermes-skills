# Scheduler timezone checks

For a clock-time recurring job, inspect the configured scheduler timezone and its exposed schema/status before selecting the schedule form. Use the verified IANA local walltime required by that scheduler. Do not manually convert recurring rules to UTC or use a fixed offset table.

A delay remains the scheduler's own delay form, such as `in 20m`. If scheduler configuration and the requested timezone differ, assess affected jobs and obtain migration authority before a global configuration or recurring-rule change. Do not claim DST safety until the persisted schedule and timezone support it.