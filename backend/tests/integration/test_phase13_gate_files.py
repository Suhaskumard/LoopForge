# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: the deliverables that are files (compose security properties, CI jobs, env docs, scripts)."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


class _ComposeLoader(yaml.SafeLoader):
    """Docker Compose adds tags like `!override` / `!reset`; for these checks the value under the tag is what matters."""


def _untag(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _untag)


def _yaml(name: str) -> dict:
    return yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)  # noqa: S506 - SafeLoader subclass


# ---- the opt-in containerised worker --------------------------------------------------------------------


def test_the_worker_container_never_gets_the_docker_socket_only_the_proxy_does():
    doc = _yaml("docker-compose.worker-docker.yml")["services"]
    worker, proxy = doc["worker-docker"], doc["docker-proxy"]
    assert not any("docker.sock" in str(v) for v in worker["volumes"])
    assert worker["environment"]["DOCKER_HOST"] == "tcp://docker-proxy:2375"
    assert any("/var/run/docker.sock" in v and v.endswith(":ro") for v in proxy["volumes"])
    assert "ports" not in proxy and proxy["expose"] == ["2375"]  # never published to the host


def test_the_proxy_allows_containers_only():
    env = _yaml("docker-compose.worker-docker.yml")["services"]["docker-proxy"]["environment"]
    assert env == {"CONTAINERS": "1", "POST": "1", "INFO": "1"}
    for dangerous in (
        "IMAGES",
        "EXEC",
        "VOLUMES",
        "NETWORKS",
        "BUILD",
        "SWARM",
        "SERVICES",
        "SECRETS",
        "COMMIT",
    ):
        assert dangerous not in env  # left at the proxy's default: denied


def test_both_sides_share_one_host_bind_and_the_translation_is_configured():
    doc = _yaml("docker-compose.worker-docker.yml")["services"]
    for name in ("backend", "worker-docker"):
        vols = doc[name]["volumes"]
        assert any(
            v.endswith(":/data/workspaces") and "LF_HOST_WORKSPACES" in v for v in vols
        ), name
        assert not any(
            re.match(r"^workspaces:", v) for v in vols
        ), "a named volume has no host path"
    env = doc["worker-docker"]["environment"]
    assert "LF_HOST_WORKSPACES" in env["SANDBOX_HOST_WORKSPACE_ROOT"]
    assert env["SANDBOX_BACKEND"] == "docker" and env["RUN_MODE"] == "queue"
    assert (
        doc["backend"]["environment"]["RUN_MODE"] == "queue"
    )  # the API must enqueue, not run in-process


def test_the_worker_image_is_the_backend_image_plus_the_cli_and_runs_unprivileged():
    text = (ROOT / "backend" / "Dockerfile.worker-docker").read_text(encoding="utf-8")
    assert "FROM backendimage" in text and "FROM docker:27-cli" in text
    assert text.rstrip().splitlines()[-1] == "USER loopforge"  # back to the unprivileged user
    build = _yaml("docker-compose.worker-docker.yml")["services"]["worker-docker"]["build"]
    assert build["additional_contexts"] == {"backendimage": "service:backend"}


def test_the_default_compose_file_is_unchanged_in_spirit():
    """The raw socket and the Docker CLI appear only in the opt-in file, never in the default stack."""
    default = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert (
        "docker.sock" not in default
        and "docker-proxy" not in default
        and "Dockerfile.worker-docker" not in default
    )


# ---- test infrastructure --------------------------------------------------------------------------------


def test_the_throwaway_infrastructure_is_local_only_and_ephemeral():
    doc = _yaml("docker-compose.test.yml")["services"]
    db, kc = doc["test-db"], doc["keycloak"]
    assert db["ports"] == ["127.0.0.1:5433:5432"] and db["tmpfs"] == ["/var/lib/postgresql/data"]
    assert kc["ports"] == ["127.0.0.1:8180:8080"] and kc["profiles"] == ["oidc"]
    assert re.search(r":\d+\.\d+\.\d+$", kc["image"]), "Keycloak must be pinned to an exact version"
    assert "start-dev" in kc["command"]  # dev mode: for tests only


def test_the_keycloak_realm_fixture_has_the_users_the_tests_rely_on():
    realm = json.loads(
        (ROOT / "backend" / "tests" / "fixtures" / "keycloak" / "loopforge-realm.json").read_text()
    )
    users = {u["username"]: u for u in realm["users"]}
    assert users["alice"]["emailVerified"] is True and users["bob"]["emailVerified"] is False
    assert users["carol"]["email"].endswith("@other.example")
    client = realm["clients"][0]
    assert client["publicClient"] is False and client["directAccessGrantsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"


def test_the_runner_scripts_fail_instead_of_skipping_without_docker():
    for name in (
        "test_postgres.sh",
        "test_keycloak.sh",
        "docker_worker_smoke.sh",
        "phase13_gate.sh",
    ):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "docker info" in text and ("FAIL" in text) and "exit 1" in text, name
    gate = (ROOT / "scripts" / "phase13_gate.sh").read_text(encoding="utf-8")
    for step in ("phase12_gate.sh", "npm audit --omit=dev", "pip_audit", "test_postgres.sh", "test_keycloak.sh",
                 "docker_worker_smoke.sh", "-m docker", "acceptance item 4"):  # fmt: skip
        assert step in gate, step


# ---- CI, frontend, docs ---------------------------------------------------------------------------------


def test_ci_runs_the_real_infrastructure_jobs_with_pinned_images():
    ci = _yaml(".github/workflows/ci.yml")
    jobs = ci["jobs"]
    assert {"postgres", "docker", "oidc"} <= set(jobs)
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert (
        "test_postgres.sh" in text
        and "test_keycloak.sh" in text
        and "docker_worker_smoke.sh" in text
    )
    assert "pytest -m docker" in text or "-m docker" in text
    assert ci["permissions"] == {"contents": "read"}


def test_the_frontend_uses_react_router_v7_and_not_the_vulnerable_dom_package():
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert "react-router-dom" not in pkg["dependencies"]
    major, minor, patch = (int(x) for x in pkg["dependencies"]["react-router"].split("."))
    assert (major, minor, patch) >= (7, 18, 5) and major == 7  # v8 needs React 19
    for path in (ROOT / "frontend" / "src").rglob("*.ts*"):
        assert "react-router-dom" not in path.read_text(encoding="utf-8"), path.name


def test_new_settings_are_documented_in_the_env_example():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("MODEL_PRICES_JSON", "WORKER_METRICS_TOKEN", "SANDBOX_HOST_WORKSPACE_ROOT", "LF_HOST_WORKSPACES",
                "BACKUP_PASSPHRASE_FILE", "PG_CONTAINER"):  # fmt: skip
        assert key in env, key


def test_the_audit_truncate_guard_exists_in_both_the_migration_and_the_model():
    migration = (
        ROOT / "backend" / "migrations" / "versions" / "0009_audit_truncate_guard.py"
    ).read_text(encoding="utf-8")
    model = (ROOT / "backend" / "app" / "database" / "models.py").read_text(encoding="utf-8")
    assert (
        "BEFORE TRUNCATE" in migration
        and "BEFORE TRUNCATE" in model
        and "FOR EACH STATEMENT" in model
    )


def test_adr_and_operations_guide_state_the_limits():
    adr = (ROOT / "docs" / "adr" / "0020-real-infrastructure-and-gap-closing.md").read_text(
        encoding="utf-8"
    )
    for needle in (
        "TRUNCATE",
        "jwt_secret",
        "socket proxy filters by endpoint",
        "Keycloak is one real provider",
        "Phase 14",
    ):
        assert needle in adr, needle
    ops = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    assert "workers-docker" in ops and "test_postgres.sh" in ops and "BACKUP_PASSPHRASE_FILE" in ops
