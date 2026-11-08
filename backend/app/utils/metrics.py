"""Minimal Prometheus-format metrics (Phase 12, ADR-0019). No third-party dependency.

Counters and histograms are kept in process memory: **each process (API, every worker) has its
own registry and must be scraped separately**. Gauges that describe shared state (tasks by
status, queue depth, active leases) are computed from the database at scrape time by
`refresh_db_gauges`, so they are the same whichever API replica answers.

Label values are escaped per the text exposition format. Label *cardinality* is the caller's
job: use route templates (`/tasks/{task_id}`), never raw paths or ids.
"""

import threading
from collections.abc import Iterable, Sequence
from typing import Any

Labels = tuple[tuple[str, str], ...]

_DEFAULT_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt(labels: Labels, extra: Sequence[tuple[str, str]] = ()) -> str:
    pairs = [*labels, *extra]
    if not pairs:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in pairs) + "}"


def _number(value: float) -> str:
    if value == float("inf"):
        return "+Inf"
    return repr(int(value)) if float(value).is_integer() else repr(float(value))


class _Metric:
    kind = ""

    def __init__(self, name: str, help_text: str, labelnames: Sequence[str] = ()) -> None:
        self.name, self.help, self.labelnames = name, help_text, tuple(labelnames)
        self._lock = threading.Lock()

    def _key(self, labels: dict[str, str]) -> Labels:
        if set(labels) != set(self.labelnames):
            raise ValueError(f"{self.name} takes labels {self.labelnames}, got {sorted(labels)}")
        return tuple((n, str(labels[n])) for n in self.labelnames)

    def samples(self) -> Iterable[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def render(self) -> str:
        header = f"# HELP {self.name} {self.help}\n# TYPE {self.name} {self.kind}\n"
        return header + "".join(f"{line}\n" for line in self.samples())


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name: str, help_text: str, labelnames: Sequence[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self._values: dict[Labels, float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("a counter only goes up")
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def samples(self) -> Iterable[str]:
        with self._lock:
            items = sorted(self._values.items())
        return [f"{self.name}{_fmt(k)} {_number(v)}" for k, v in items]


class Gauge(_Metric):
    kind = "gauge"

    def __init__(self, name: str, help_text: str, labelnames: Sequence[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self._values: dict[Labels, float] = {}

    def set(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = float(value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def samples(self) -> Iterable[str]:
        with self._lock:
            items = sorted(self._values.items())
        return [f"{self.name}{_fmt(k)} {_number(v)}" for k, v in items]


class Histogram(_Metric):
    kind = "histogram"

    def __init__(
        self,
        name: str,
        help_text: str,
        labelnames: Sequence[str] = (),
        buckets: Sequence[float] = _DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, labelnames)
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[Labels, list[int]] = {}
        self._sum: dict[Labels, float] = {}
        self._total: dict[Labels, int] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            counts = self._counts.setdefault(key, [0] * len(self.buckets))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[i] += 1
            self._sum[key] = self._sum.get(key, 0.0) + value
            self._total[key] = self._total.get(key, 0) + 1

    def count(self, **labels: str) -> int:
        return self._total.get(self._key(labels), 0)

    def samples(self) -> Iterable[str]:
        lines: list[str] = []
        with self._lock:
            for key in sorted(self._counts):
                cumulative = self._counts[key]
                for bound, n in zip(self.buckets, cumulative, strict=True):
                    lines.append(f"{self.name}_bucket{_fmt(key, [('le', _number(bound))])} {n}")
                total = self._total.get(key, 0)
                lines.append(f"{self.name}_bucket{_fmt(key, [('le', '+Inf')])} {total}")
                lines.append(f"{self.name}_sum{_fmt(key)} {_number(self._sum.get(key, 0.0))}")
                lines.append(f"{self.name}_count{_fmt(key)} {total}")
        return lines


class Registry:
    def __init__(self) -> None:
        self._metrics: dict[str, _Metric] = {}

    def _add(self, metric: Any) -> Any:
        if metric.name in self._metrics:
            raise ValueError(f"metric {metric.name} is already registered")
        self._metrics[metric.name] = metric
        return metric

    def counter(self, name: str, help_text: str, labelnames: Sequence[str] = ()) -> Counter:
        return self._add(Counter(name, help_text, labelnames))  # type: ignore[no-any-return]

    def gauge(self, name: str, help_text: str, labelnames: Sequence[str] = ()) -> Gauge:
        return self._add(Gauge(name, help_text, labelnames))  # type: ignore[no-any-return]

    def histogram(
        self,
        name: str,
        help_text: str,
        labelnames: Sequence[str] = (),
        buckets: Sequence[float] = _DEFAULT_BUCKETS,
    ) -> Histogram:
        return self._add(Histogram(name, help_text, labelnames, buckets))  # type: ignore[no-any-return]

    def names(self) -> set[str]:
        """Names a scraper can query (histograms also expose _bucket/_sum/_count)."""
        out: set[str] = set()
        for m in self._metrics.values():
            out.add(m.name)
            if m.kind == "histogram":
                out.update(f"{m.name}{suffix}" for suffix in ("_bucket", "_sum", "_count"))
        return out

    def render(self) -> str:
        return "".join(self._metrics[n].render() for n in sorted(self._metrics))


REGISTRY = Registry()

# ---- in-process series ---------------------------------------------------------------------
HTTP_REQUESTS = REGISTRY.counter(
    "loopforge_http_requests_total", "HTTP requests handled.", ["method", "route", "status_class"]
)
HTTP_DURATION = REGISTRY.histogram(
    "loopforge_http_request_duration_seconds", "HTTP request latency.", ["route"]
)
LLM_CALLS = REGISTRY.counter(
    "loopforge_llm_calls_total",
    "Agent calls to the model (one per agent invocation).",
    ["agent", "outcome"],
)
LLM_TOKENS = REGISTRY.counter("loopforge_llm_tokens_total", "Model tokens used.", ["agent"])
SANDBOX_RUNS = REGISTRY.counter("loopforge_sandbox_runs_total", "Sandbox executions.", ["outcome"])
SANDBOX_DURATION = REGISTRY.histogram(
    "loopforge_sandbox_run_duration_seconds", "Sandbox execution time.", []
)
LEASE_TAKEOVERS = REGISTRY.counter(
    "loopforge_lease_takeovers_total", "Run leases taken over from an expired owner."
)
JOBS_FINISHED = REGISTRY.counter(
    "loopforge_jobs_finished_total", "Queue jobs finished by this worker process.", ["status"]
)

# ---- shared state, refreshed from the database at scrape time --------------------------------
TASKS = REGISTRY.gauge("loopforge_tasks", "Tasks by status.", ["status"])
BACKPRESSURE = REGISTRY.counter(
    "loopforge_backpressure_total",
    "Task starts refused because the job queue was full.",
    ["scope"],
)
JOBS_QUEUED = REGISTRY.gauge("loopforge_jobs_queued", "Jobs waiting for a worker.")
JOBS_RUNNING = REGISTRY.gauge("loopforge_jobs_running", "Jobs a worker is processing.")
JOBS_OLDEST_QUEUED_AGE = REGISTRY.gauge(
    "loopforge_jobs_oldest_queued_age_seconds", "Age of the oldest queued job (0 when none)."
)
ACTIVE_LEASES = REGISTRY.gauge("loopforge_active_leases", "Unexpired task run leases.")
EXPIRED_LEASES = REGISTRY.gauge(
    "loopforge_expired_leases", "Leases whose owner stopped renewing them (stalled or dead runs)."
)
TOKENS_MONTH = REGISTRY.gauge(
    "loopforge_tokens_used_month", "Model tokens used this UTC month, all organizations."
)
BUILD_INFO = REGISTRY.gauge(
    "loopforge_build_info", "Constant 1, labelled with the version.", ["version"]
)
