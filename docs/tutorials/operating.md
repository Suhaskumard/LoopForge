# Operate it

A pointer page; the detail lives in the [operations guide](../operations.md).

| Task | Where |
|---|---|
| Production settings (secrets, queue mode, proxies, pools) | [operations: configuration](../operations.md#configuration-that-matters-in-production) |
| Deploy and run migrations safely | [operations: deploy](../operations.md#deploy), [upgrade guide](../upgrade_guide.md) |
| Scale workers; what happens when one dies | [scaling](../operations.md#scaling-workers), [crash recovery](../operations.md#worker-crash-recovery) |
| Back up and restore; test it | [backup and restore](../operations.md#backup-and-restore), [DR drill](../operations.md#disaster-recovery-drill) |
| Rotate keys and webhook secrets | [key rotation](../operations.md#key-rotation) |
| Protect against overload | [queue back-pressure](../operations.md#queue-back-pressure) |
| Know whether it is healthy | [SLOs and error budgets](../slo.md), alert rules in `deploy/observability/alerts.yml` |
| Respond to an incident | [incident checklist](../operations.md#incident-checklist) |
| Cost and quotas, plans | [cost and quotas](../operations.md#cost-and-quotas); `loopforge ops set-plan` assigns a plan |
| Release and upgrade | [releasing](../releasing.md), [upgrade guide](../upgrade_guide.md), [changelog](../../CHANGELOG.md) |

Gates are the habit that keeps this honest: `make gate18` runs everything earlier gates run plus the platform checks, and prints what it does **not** prove.
