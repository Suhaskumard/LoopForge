"""Concurrent-user load and isolation check against a running LoopForge API (stdlib only).

Each virtual user registers (their own organization), logs in, creates a project and several tasks, then reads
them back repeatedly. The run FAILS (exit 1) if any request returns an unexpected status (5xx in particular),
if a user ever sees another user's task, or if a foreign task id is not a 404. Latency percentiles are
reported, not judged: they depend entirely on the machine and the database.

  python scripts/load_test.py --url http://localhost:8000 --users 20 --tasks 3 --reads 15
"""

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "/api/v1"


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latencies: list[float] = []
        self.statuses: dict[int, int] = {}
        self.problems: list[str] = []

    def add(self, status: int, seconds: float) -> None:
        with self.lock:
            self.latencies.append(seconds)
            self.statuses[status] = self.statuses.get(status, 0) + 1

    def problem(self, text: str) -> None:
        with self.lock:
            self.problems.append(text)


def call(rec: Recorder, base: str, method: str, path: str, *, token: str | None = None,
         body: object = None, form: dict | None = None, expect: tuple[int, ...] = (200,)):  # fmt: skip
    data, headers = None, {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - operator-supplied URL
            status, payload = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        status, payload = err.code, err.read()
    except Exception as exc:  # noqa: BLE001
        rec.problem(f"{method} {path}: {type(exc).__name__}: {exc}")
        return 0, None
    rec.add(status, time.perf_counter() - start)
    if status not in expect:
        rec.problem(f"{method} {path}: HTTP {status}, expected {expect}")
    try:
        return status, json.loads(payload) if payload else None
    except ValueError:
        return status, None


def virtual_user(rec: Recorder, base: str, index: int, tasks: int, reads: int,
                 shared: dict, barrier: threading.Barrier) -> None:  # fmt: skip
    email, password = f"load-{uuid.uuid4().hex[:10]}@example.com", "loadtest123"
    call(
        rec,
        base,
        "POST",
        f"{API}/auth/register",
        body={"email": email, "password": password},
        expect=(201,),
    )
    _, tok = call(
        rec, base, "POST", f"{API}/auth/login", form={"username": email, "password": password}
    )
    if not tok:
        return
    token = tok["access_token"]
    _, project = call(
        rec, base, "POST", f"{API}/projects", token=token, body={"name": f"p{index}"}, expect=(201,)
    )
    mine = []
    for n in range(tasks):
        _, t = call(rec, base, "POST", f"{API}/tasks", token=token, expect=(201,), body={
            "project_id": project["id"], "requirement": f"Load test task {index}-{n}: build a small API."})  # fmt: skip
        if t:
            mine.append(t["id"])
    with shared["lock"]:
        shared["tasks"][index] = set(mine)
    barrier.wait(timeout=120)  # everyone has created their data: now read concurrently
    for r in range(reads):
        _, listed = call(rec, base, "GET", f"{API}/tasks", token=token)
        seen = {t["id"] for t in (listed or [])}
        if seen != set(mine):
            rec.problem(f"user {index}: sees {len(seen)} tasks, created {len(mine)} (leak or loss)")
        if mine:
            call(rec, base, "GET", f"{API}/tasks/{mine[r % len(mine)]}", token=token)
    # another user's task id must look like it does not exist
    with shared["lock"]:
        others = [next(iter(ids)) for i, ids in shared["tasks"].items() if i != index and ids]
    for foreign in others[:3]:
        call(rec, base, "GET", f"{API}/tasks/{foreign}", token=token, expect=(404,))


def run(base: str, users: int, tasks: int, reads: int) -> dict:
    rec = Recorder()
    shared = {"lock": threading.Lock(), "tasks": {}}
    barrier = threading.Barrier(users)
    threads = [threading.Thread(target=virtual_user, args=(rec, base, i, tasks, reads, shared, barrier))
               for i in range(users)]  # fmt: skip
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started
    lat = sorted(rec.latencies) or [0.0]
    pct = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))]  # noqa: E731
    return {
        "users": users, "requests": len(rec.latencies), "seconds": round(elapsed, 2),
        "requests_per_second": round(len(rec.latencies) / elapsed, 1) if elapsed else 0,
        "latency_seconds": {"p50": round(pct(0.5), 4), "p95": round(pct(0.95), 4),
                            "max": round(lat[-1], 4), "mean": round(statistics.fmean(lat), 4)},
        "statuses": dict(sorted(rec.statuses.items())),
        "server_errors": sum(n for s, n in rec.statuses.items() if s >= 500 or s == 0),
        "problems": rec.problems[:20],
    }  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--tasks", type=int, default=3)
    ap.add_argument("--reads", type=int, default=10)
    ap.add_argument("--slo-p95", type=float, default=None, help="fail if p95 latency exceeds this (s)")
    ap.add_argument("--slo-error-rate", type=float, default=None,
                    help="fail if the fraction of 5xx/transport errors exceeds this (e.g. 0.005)")  # fmt: skip
    ap.add_argument("--out", default=None, help="also write the JSON result to this file")
    args = ap.parse_args()
    result = run(args.url.rstrip("/"), args.users, args.tasks, args.reads)
    print(json.dumps(result, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    if result["server_errors"] or result["problems"]:
        print("LOAD TEST: FAIL")
        return 1
    rate = result["server_errors"] / max(result["requests"], 1)
    if args.slo_p95 is not None and result["latency_seconds"]["p95"] > args.slo_p95:
        print(f"LOAD TEST: FAIL (p95 {result['latency_seconds']['p95']}s > SLO {args.slo_p95}s)")
        return 1
    if args.slo_error_rate is not None and rate > args.slo_error_rate:
        print(f"LOAD TEST: FAIL (error rate {rate:.4f} > SLO {args.slo_error_rate})")
        return 1
    print("LOAD TEST: PASS (no server errors, no cross-user leakage; latency is informational)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
