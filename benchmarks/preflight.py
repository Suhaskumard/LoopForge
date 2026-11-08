"""Preflight for the REAL benchmark run (Phase 12): find every blocker before spending anything.

    python benchmarks/preflight.py --config E1,E2,E3 --trials 3 --max-total-cost 25
    python benchmarks/preflight.py --provider oracle     # harness check: the real-run checks are SKIPped

It checks what a real run needs (API key, model, an explicit price per 1k tokens, a spending cap, a reachable Docker
daemon, the sandbox images, the task set, disk space), prints the worst-case cost, and exits 1 listing EVERY blocker,
not just the first. A SKIP is never counted as a pass. The key itself is never printed.
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
MIN_FREE_BYTES = 1_000_000_000
SANDBOX_IMAGE = "loopforge-sandbox"


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str


@dataclass
class Env:
    """Everything the checks look at, injectable so tests need no Docker, key or network."""

    environ: dict[str, str]
    docker_reachable: bool
    images: set[str]
    task_dirs: list[Path]
    free_bytes: int
    out_writable: bool


def real_env(out: Path) -> Env:
    def docker_info() -> bool:
        try:
            return subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    reachable = docker_info()
    images: set[str] = set()
    if reachable:
        for name in (SANDBOX_IMAGE, "loopforge-sandbox-node"):
            r = subprocess.run(["docker", "image", "inspect", name], capture_output=True, check=False)
            if r.returncode == 0:
                images.add(name)
    out.mkdir(parents=True, exist_ok=True)
    try:
        probe = out / ".preflight"
        probe.write_text("ok")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    return Env(
        environ=dict(os.environ),
        docker_reachable=reachable,
        images=images,
        task_dirs=[d for d in sorted(TASKS_DIR.iterdir()) if d.is_dir()] if TASKS_DIR.is_dir() else [],
        free_bytes=shutil.disk_usage(out).free,
        out_writable=writable,
    )


def _dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip("\"'")
    return out


def run_checks(
    env: Env,
    *,
    provider: str,
    n_configs: int,
    n_tasks: int,
    trials: int,
    token_budget: int,
    max_total_cost: float,
    max_total_tokens: int,
) -> tuple[list[Check], float]:
    """Return (checks, worst-case cost in USD for the planned run)."""
    e = env.environ
    price = e.get("COST_PER_1K_TOKENS", "")
    ceiling_tokens = n_configs * n_tasks * trials * token_budget
    try:
        ceiling_cost = ceiling_tokens / 1000 * float(price) if price else 0.0
    except ValueError:
        ceiling_cost = 0.0
    checks: list[Check] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append(Check(name, "SKIP" if ok is None else ("PASS" if ok else "FAIL"), detail))

    real = provider != "oracle"
    skip_reason = "provider=oracle is a synthetic harness check; not needed"

    def need(name: str, ok: bool, detail_ok: str, detail_bad: str) -> None:
        add(name, ok if real else None, detail_ok if ok else (detail_bad if real else skip_reason))

    need("OPENAI_API_KEY is set", bool(e.get("OPENAI_API_KEY")), "set", "set OPENAI_API_KEY (it is never printed)")
    need("OPENAI_MODEL is set", bool(e.get("OPENAI_MODEL")), e.get("OPENAI_MODEL", ""), "set OPENAI_MODEL to the model under test")
    try:
        priced = float(price) > 0
    except ValueError:
        priced = False
    need(
        "COST_PER_1K_TOKENS is set explicitly",
        priced,
        f"${price}/1k tokens",
        "set COST_PER_1K_TOKENS to your model's blended price; the built-in default is a placeholder, so cost figures would be wrong",
    )
    capped = max_total_cost > 0 or max_total_tokens > 0
    need(
        "a spending cap is set",
        capped,
        f"--max-total-cost {max_total_cost} / --max-total-tokens {max_total_tokens}",
        "pass --max-total-cost (and/or --max-total-tokens): a run without a cap can spend the worst case below",
    )
    if real and capped and max_total_cost > 0 and priced and ceiling_cost > max_total_cost:
        add("the cap covers the worst case", None, f"cap ${max_total_cost} < worst case ${ceiling_cost:,.2f}: the run may stop early (it resumes)")
    need("Docker daemon is reachable", env.docker_reachable, "docker info ok", "start Docker: model-generated code may only run in the sandbox")
    need(
        f"sandbox image '{SANDBOX_IMAGE}' exists",
        SANDBOX_IMAGE in env.images,
        "present",
        f"docker build -t {SANDBOX_IMAGE} backend/sandbox",
    )
    add(
        "task set present (30 tasks)",
        len(env.task_dirs) >= 30,
        f"{len(env.task_dirs)} task directories (full validation: make bench-validate)"
        if len(env.task_dirs) >= 30
        else f"only {len(env.task_dirs)} task directories found in benchmarks/tasks",
    )
    add("output directory is writable", env.out_writable, "ok" if env.out_writable else "cannot write to --out")
    add(
        "at least 1 GB free disk",
        env.free_bytes >= MIN_FREE_BYTES,
        f"{env.free_bytes / 1e9:.1f} GB free" if env.free_bytes >= MIN_FREE_BYTES else f"only {env.free_bytes / 1e9:.2f} GB free",
    )
    return checks, ceiling_cost


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", choices=["openai", "oracle"], default="openai")
    ap.add_argument("--config", default="E1,E2,E3")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--token-budget", type=int, default=30000)
    ap.add_argument("--max-total-cost", type=float, default=0.0)
    ap.add_argument("--max-total-tokens", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "results" / "latest"))
    args = ap.parse_args(argv)

    out = Path(args.out)
    env = real_env(out)
    # a .env in the repository root counts, exactly as it does for the backend settings
    for k, v in _dotenv(ROOT.parent / ".env").items():
        env.environ.setdefault(k, v)
    n_tasks = len(env.task_dirs)
    checks, ceiling = run_checks(
        env,
        provider=args.provider,
        n_configs=len([c for c in args.config.split(",") if c.strip()]),
        n_tasks=n_tasks,
        trials=args.trials,
        token_budget=args.token_budget,
        max_total_cost=args.max_total_cost,
        max_total_tokens=args.max_total_tokens,
    )
    for c in checks:
        print(f"  [{c.status}] {c.name}: {c.detail}")
    failed = [c for c in checks if c.status == "FAIL"]
    skipped = [c for c in checks if c.status == "SKIP"]
    if args.provider != "oracle":
        print(f"\nworst-case spend for this plan: ${ceiling:,.2f} "
              f"({args.config} x {n_tasks} tasks x {args.trials} trials x {args.token_budget:,} tokens)")
    if failed:
        print(f"\nPREFLIGHT: FAIL ({len(failed)} blocker(s); nothing was spent)")
        return 1
    print(f"\nPREFLIGHT: PASS ({len(skipped)} check(s) skipped, not counted as passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
