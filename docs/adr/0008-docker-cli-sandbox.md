# ADR-0008: Docker CLI sandbox behind a `Sandbox` interface

**Status:** accepted (Phase 3)

**Context.** Generated code must never run on the FastAPI host (spec §13.1), and tests must
stay runnable without Docker.

**Decision.** `execution/sandbox.py` defines a `Sandbox` protocol. `DockerSandbox` shells out to
the `docker` CLI with a fixed argv (no shell, no SDK, no socket mounted into containers). Tests
use `FakeSandbox`; real-container checks are `@pytest.mark.docker` and skip without a daemon.
Source is mounted read-only; reports go to a separate writable `/out` mount. A wall-clock timeout
is enforced from outside (`docker kill`) and the container is always removed.

**Consequences.** Simple and auditable; limited to the isolation Docker provides. gVisor/Firecracker
can later be added as another `Sandbox` implementation (e.g. via `--runtime=runsc`) without
touching callers.
