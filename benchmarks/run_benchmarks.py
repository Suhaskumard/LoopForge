"""Run the LoopForge benchmark (spec 12.2-12.3, 12.6).

    # what would this cost? (spends nothing)
    python benchmarks/run_benchmarks.py --config E1,E2,E3 --trials 3 --provider openai --dry-run
    # real measurement (needs OPENAI_API_KEY, OPENAI_MODEL and the Docker sandbox image)
    python benchmarks/run_benchmarks.py --config E1,E2,E3 --trials 3 --provider openai --out benchmarks/results/run1
    # harness check with the synthetic oracle (NOT a measurement; no key or Docker needed)
    python benchmarks/run_benchmarks.py --config E1,E2,E3 --trials 2 --provider oracle --out /tmp/harness

Every trial runs in a fresh workspace through the same loop as production; only the LoopConfig
switch differs between configurations. Success is decided by HIDDEN tests that no agent sees, run
in a separate step after the loop - never by the agents' own tests or by the loop's verdict.
Results are appended to <out>/trials.jsonl, so an interrupted run resumes where it stopped.
"""

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "backend"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="E3", help="comma list of E1,E2,E3,A1,A2,A3,A4")
    ap.add_argument("--trials", type=int, default=1, help="repeated trials per task (>=3 for statistics)")
    ap.add_argument("--tasks", default="", help="comma list of task ids (default: all)")
    ap.add_argument("--category", default="", help="only tasks of this category")
    ap.add_argument("--provider", choices=["openai", "oracle"], default="openai")
    ap.add_argument("--out", default=str(ROOT / "results" / "latest"))
    ap.add_argument("--token-budget", type=int, default=30000, help="per-trial token cap (<= server MAX_TOKEN_BUDGET)")
    ap.add_argument("--max-total-tokens", type=int, default=0, help="stop the whole run beyond this (0 = no cap)")
    ap.add_argument("--max-total-cost", type=float, default=0.0, help="stop beyond this estimated $ (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the cost ceiling, run nothing")
    return ap.parse_args(argv)


def load_tasks(args: argparse.Namespace) -> list[dict]:
    wanted = {t for t in args.tasks.split(",") if t}
    tasks = []
    for d in sorted(TASKS_DIR.iterdir()):
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        if wanted and meta["id"] not in wanted:
            continue
        if args.category and meta["category"] != args.category:
            continue
        meta["dir"] = d
        tasks.append(meta)
    return tasks


def done_keys(path: Path) -> set[tuple[str, str, int]]:
    keys: set[tuple[str, str, int]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                keys.add((r["config"], r["task"], r["trial"]))
    return keys


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configs = [c.strip() for c in args.config.split(",") if c.strip()]
    tasks = load_tasks(args)
    out = Path(args.out).resolve()

    # settings must be in place before the backend is imported
    os.environ.update(
        {
            "DATABASE_URL": f"sqlite:///{out / 'bench.db'}",
            "WORKSPACE_ROOT": str(out / "workspaces"),
            "ENVIRONMENT": "development",
            "SANDBOX_BACKEND": "docker",
            "LLM_PROVIDER": "openai",
            "DOCUMENTATION_AGENT_ENABLED": "false",
            "MAX_TOKEN_BUDGET": str(max(args.token_budget, 1000)),
        }
    )
    from app.config import settings
    from app.orchestrator.loop_config import PRESETS

    unknown = [c for c in configs if c not in PRESETS]
    if unknown:
        print(f"unknown config(s): {unknown}; choose from {sorted(PRESETS)}", file=sys.stderr)
        return 2
    total_trials = len(configs) * len(tasks) * args.trials
    ceiling_tokens = total_trials * args.token_budget
    ceiling_cost = ceiling_tokens / 1000 * settings.cost_per_1k_tokens
    print(
        f"plan: {len(configs)} config(s) x {len(tasks)} task(s) x {args.trials} trial(s) = {total_trials} trials; "
        f"worst case {ceiling_tokens:,} tokens = about ${ceiling_cost:,.2f} at ${settings.cost_per_1k_tokens}/1k "
        f"(estimate; set COST_PER_1K_TOKENS to your model's blended price)"
    )
    if args.dry_run:
        return 0
    if args.provider == "oracle":
        print("!! provider=oracle: SYNTHETIC harness check. Results are NOT measurements of LoopForge.")
    elif not os.environ.get("OPENAI_API_KEY") and not settings.openai_api_key:
        print("OPENAI_API_KEY is not set; use --provider oracle for a harness check.", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    return run(args, configs, tasks, out)


def run(args: argparse.Namespace, configs: list[str], tasks: list[dict], out: Path) -> int:
    from app.config import settings
    from app.database.models import Base, Iteration, RepairHistory, Task, User
    from app.database.session import SessionLocal, engine
    from app.evaluation.test_runner import PYTEST_ARGV, parse_report
    from app.execution.runner import run_command
    from app.orchestrator.loop_config import PRESETS
    from app.schemas.project import ProjectCreate
    from app.services import analytics_service, project_service, run_service, task_service, workspace
    from sqlalchemy import select

    if args.provider == "oracle":
        from host_sandbox import HostSandbox
        from oracle import MODES, OracleLLM

        sandbox = HostSandbox()
        model_name = "oracle (synthetic)"
    else:
        from app.execution.sandbox import DockerSandbox, docker_available
        from app.services.llm_client import get_llm_client

        if not docker_available():
            print("Docker is not available; model-generated code may only run in the Docker sandbox.", file=sys.stderr)
            return 2
        sandbox = DockerSandbox()
        model_name = settings.openai_model or "unset"

    Base.metadata.create_all(engine)
    results = out / "trials.jsonl"
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "provider": args.provider,
                "synthetic": args.provider == "oracle",
                "model": model_name,
                "configs": configs,
                "trials": args.trials,
                "token_budget": args.token_budget,
                "cost_per_1k_tokens": settings.cost_per_1k_tokens,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "tasks": [t["id"] for t in tasks],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    finished = done_keys(results)
    with SessionLocal() as db:
        user = User(email=f"bench-{uuid.uuid4().hex[:6]}@example.com", password_hash="x")
        db.add(user)
        db.commit()
        user_id = user.id

    spent_tokens, spent_cost = 0, 0.0
    for config_name in configs:
        config = PRESETS[config_name]
        for t_index, meta in enumerate(tasks):
            for trial in range(args.trials):
                key = (config_name, meta["id"], trial)
                if key in finished:
                    continue
                if args.max_total_tokens and spent_tokens >= args.max_total_tokens:
                    print(f"stopped: token cap {args.max_total_tokens:,} reached (resume by re-running)")
                    return 3
                if args.max_total_cost and spent_cost >= args.max_total_cost:
                    print(f"stopped: cost cap ${args.max_total_cost} reached (resume by re-running)")
                    return 3
                if args.provider == "oracle":
                    mode = MODES[(t_index * 7 + trial) % 3]  # same for every config of this trial
                    llm = OracleLLM(meta["dir"], mode)
                else:
                    mode, llm = None, get_llm_client()

                started = time.perf_counter()
                with SessionLocal() as db:
                    project = project_service.create_project(db, user_id, ProjectCreate(name=f"b_{meta['id']}"[:60]))
                    task = task_service.create_task(
                        db, project, meta["requirement"], 5, list(meta["acceptance_criteria"]),
                        token_budget=args.token_budget,
                    )  # fmt: skip
                    task_id = task.id
                    run_service.prepare_start(db, task)
                run_service.execute_run(SessionLocal, task_id, llm, sandbox, config)
                loop_seconds = time.perf_counter() - started

                with SessionLocal() as db:
                    task = db.get(Task, task_id)
                    its = sorted(db.scalars(select(Iteration).where(Iteration.task_id == task_id)), key=lambda i: i.iteration_number)
                    tokens = sum(analytics_service._tokens_by_iteration(db, [i.id for i in its]).values())
                    results_by_it = analytics_service.latest_results(db, [i.id for i in its])
                    repairs = list(db.scalars(select(RepairHistory).where(RepairHistory.task_id == task_id).order_by(RepairHistory.created_at)))
                    status = task.status
                    n_iter = len(its)
                    last_number = its[-1].iteration_number if its else 0
                    failing_per_it = []
                    for it in its:
                        r = results_by_it.get(it.id)
                        failing_per_it.append({f["nodeid"] for f in (r.details.get("failures", []) if r else [])})
                    regressions = sum(len(failing_per_it[i] - failing_per_it[i - 1]) for i in range(1, len(failing_per_it)))
                    category = repairs[-1].failure_category if repairs else "none"

                hidden = hidden_eval(meta["dir"], workspace.iteration_dir(task_id, last_number) if last_number else None,
                                     sandbox, out / "hidden_work", run_command, PYTEST_ARGV, parse_report)  # fmt: skip
                success = hidden["total"] > 0 and hidden["passed"] == hidden["total"]
                cost = analytics_service.cost_of(tokens)
                spent_tokens += tokens
                spent_cost += cost
                record = {
                    "config": config_name, "task": meta["id"], "category": meta["category"],
                    "difficulty": meta["difficulty"], "trial": trial, "provider": args.provider,
                    "model": model_name, "oracle_mode": mode, "loop_status": status,
                    "success": success, "hidden_total": hidden["total"], "hidden_passed": hidden["passed"],
                    "hidden_pass_rate": (hidden["passed"] / hidden["total"]) if hidden["total"] else 0.0,
                    "false_accept": status == "COMPLETED" and not success,
                    "iterations": n_iter, "tokens": tokens, "cost": round(cost, 6),
                    "seconds": round(loop_seconds, 3), "failure_category": category,
                    "regressions": regressions, "synthetic": args.provider == "oracle",
                }  # fmt: skip
                with results.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
                print(
                    f"{config_name} {meta['id']:<30} t{trial} loop={status:<9} hidden={hidden['passed']}/{hidden['total']}"
                    f" iters={n_iter} tokens={tokens} {'OK' if success else 'FAIL'}"
                )
    print(f"done: {results}")
    return 0


def hidden_eval(task_dir: Path, final_src: Path | None, sandbox, work: Path, run_command, pytest_argv, parse_report) -> dict:
    """Run the hidden tests against the final code in the SAME sandbox, independently of the loop."""
    if final_src is None or not final_src.is_dir():
        return {"total": 0, "passed": 0}
    project = work / uuid.uuid4().hex
    shutil.copytree(final_src, project)
    shutil.rmtree(project / "hidden_tests", ignore_errors=True)
    shutil.copytree(task_dir / "hidden_tests", project / "hidden_tests")
    out = project.parent / (project.name + "_out")
    out.mkdir(parents=True)
    try:
        result = run_command(sandbox, project, out, [*pytest_argv, "/workspace/hidden_tests"], 120)
        report = out / "report.json"
        raw = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
        summary = parse_report(raw, result, 120)
        return {"total": summary.total, "passed": summary.passed}
    finally:
        shutil.rmtree(project, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
