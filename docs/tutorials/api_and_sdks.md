# Use the API and the SDKs

The contract is [`openapi.json`](../openapi.json) (also at `/openapi.json` and `/docs` on a running server); the rules (versioning, deprecation, limits) are in the
[API policy](../api_policy.md).

## Authenticate
Create an org-bound API token (shown once) as an admin: `POST /api/v1/orgs/{org}/tokens` with `{"name": "ci", "scope": "developer"}`. Send it as `Authorization: Bearer lfk_...`.
A token can never exceed its scope (viewer < developer < approver) and works in one organization only.

## Python
```python
from loopforge_sdk import LoopForge, RateLimited
lf = LoopForge("https://loopforge.example.com", token="lfk_...")
project = lf.create_project("billing")
task = lf.create_task(project["id"], "Add an invoice export endpoint with tests")
lf.start_task(task["id"])
print(lf.wait_for_task(task["id"])["status"])
for t in lf.tasks():                       # follows pagination for you
    print(t["id"], t["status"])
```
Install from the repository (`pip install ./sdk/python`); the SDK is not on PyPI. More: `sdk/python/README.md`.

## TypeScript
```ts
import { LoopForge } from "./sdk/typescript/src/index.ts";
const lf = new LoopForge("https://loopforge.example.com", { token: "lfk_..." });
const project = await lf.createProject("billing");
const task = await lf.createTask(project.id, "Add an invoice export endpoint with tests");
await lf.startTask(task.id);
for await (const t of lf.tasks()) console.log(t.id, t.status);
```
Zero runtime dependencies (global `fetch`); not on npm.

## Behaviour to design for
* **Retries**: the SDKs retry 429 (waiting `Retry-After`), 502/503/504 and network errors. They send an `Idempotency-Key` on create/start/publish so a retry never creates twice.
  Doing it by hand: send your own `Idempotency-Key` header and re-send the identical request.
* **Rate limits**: 600 requests/minute per API token by default; watch `X-RateLimit-Remaining`.
* **Pagination**: `?limit=&offset=`; the total is in `X-Total-Count`, the next page in the `Link` header.
* **Errors**: `{"error": {"code", "message", "request_id"}}`; include `request_id` when reporting a problem.
* **Webhooks**: register one (`POST /orgs/{org}/webhooks`); verify `X-LoopForge-Signature` (`t=<ts>,v1=<hmac>`) with the secret shown at creation. Rotation briefly sends two `v1=` values.

## Usage and cost
`GET /api/v1/orgs/{org}/usage/report?group_by=project|member|agent|model|day&from=YYYY-MM-DD&to=YYYY-MM-DD` (admin) and the same as `.csv`. Cost is an *estimate* from token counts and your price
map, not billing data.
