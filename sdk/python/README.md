# loopforge-sdk (Python)

Pre-release (`1.0.0rc1`), **not published to PyPI**: install from the repository (`pip install ./sdk/python`).

```python
from loopforge_sdk import LoopForge, RateLimited

lf = LoopForge("https://loopforge.example.com", token="lfk_...")   # an org-bound API token
project = lf.create_project("billing")                              # retried safely: sends an Idempotency-Key
task = lf.create_task(project["id"], "Add an invoice export endpoint with tests")
lf.start_task(task["id"])
done = lf.wait_for_task(task["id"])
print(done["status"], lf.task_report(task["id"])["summary"])

for p in lf.projects():          # paginated iterator
    print(p["name"])
print(lf.usage_report(group_by="member")["totals"])
```

Retries: 429 (honouring `Retry-After`), 502/503/504 and network errors, exponential backoff, up to `max_retries`. A `POST` is only
retried when it carries an idempotency key; the create/start/publish methods generate one for you. Endpoints without a named method
(SCIM, MFA, notifications, ...) are reachable with `lf.request("GET", "/api/v1/...")`.

Tested only against the LoopForge server in this repository (`sdk/python/tests`, `backend/tests/integration/test_phase18_sdk.py`).
