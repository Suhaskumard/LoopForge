"""Phase 17: the control mapping and the SLO document cannot drift away from the code they cite."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"


def _text(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _cited_artifacts(md: str) -> list[tuple[str, str | None]]:
    """Every `path` or `path::test_name` in backticks that looks like a repository path."""
    out = []
    for raw in re.findall(r"`([^`]+)`", md):
        for item in raw.split(";"):
            item = item.strip()
            m = re.fullmatch(r"([\w./-]+\.(?:py|sh|md|json|yml|yaml))(?:::(\w+))?", item)
            if m and "/" in m.group(1):
                out.append((m.group(1), m.group(2)))
    return out


def test_every_artifact_the_control_mapping_cites_exists():
    md = _text("docs", "compliance_controls.md")
    cited = _cited_artifacts(md)
    assert len(cited) >= 30  # the table is substantial, not a stub
    missing = [p for p, _ in cited if not (ROOT / p).exists()]
    assert missing == [], f"control mapping cites files that do not exist: {missing}"


def test_every_test_the_control_mapping_cites_exists():
    cited = [(p, t) for p, t in _cited_artifacts(_text("docs", "compliance_controls.md")) if t]
    assert len(cited) >= 10
    for path, name in cited:
        assert re.search(
            rf"^def {name}\(", (ROOT / path).read_text(encoding="utf-8"), re.M
        ), f"{path}::{name} does not exist"


def test_the_control_mapping_does_not_claim_an_audit_or_pentest():
    md = _text("docs", "compliance_controls.md")
    assert "not an attestation" in md and "no audit has been performed" in md
    assert "none has been done" in md


def test_slo_alerts_documented_are_defined_and_vice_versa():
    doc = _text("docs", "slo.md")
    rules = yaml.safe_load(_text("deploy", "observability", "alerts.yml"))["groups"]
    slo_group = next(g for g in rules if g["name"] == "loopforge-slo")
    defined = {r["alert"] for r in slo_group["rules"]}
    documented = set(re.findall(r"`(LoopForge\w+)`", doc))
    slo_documented = {
        a
        for a in documented
        if a.startswith(("LoopForgeAvailability", "LoopForgeLatency", "LoopForgeQueueBackpressure"))
    }
    assert slo_documented == defined


def test_burn_rate_thresholds_follow_from_the_budget():
    rules = {
        r["alert"]: r["expr"]
        for g in yaml.safe_load(_text("deploy", "observability", "alerts.yml"))["groups"]
        for r in g["rules"]
    }
    budget = 1 - 0.995
    assert (
        abs(14.4 * budget - 0.072) < 1e-9
        and "0.072" in rules["LoopForgeAvailabilityBudgetFastBurn"]
    )
    assert abs(6 * budget - 0.03) < 1e-9 and "0.03" in rules["LoopForgeAvailabilityBudgetSlowBurn"]
    assert "0.005" in rules["LoopForgeAvailabilityBudgetTicket"]
    assert (
        abs(14.4 * (1 - 0.99) - 0.144) < 1e-9 and "0.144" in rules["LoopForgeLatencyBudgetFastBurn"]
    )


def test_slo_document_states_targets_are_not_measurements():
    doc = _text("docs", "slo.md")
    for needle in (
        "not measurements of production",
        "To be measured",
        "docs/dr_drill_result.json",
        "docs/load_postgres_result.json",
    ):
        assert needle in doc, needle
    assert "Not yet known (to be measured)" in doc or "to be measured" in doc.lower()


def test_recorded_drill_and_load_results_are_well_formed_and_meet_the_documented_targets():
    import json

    dr = json.loads(_text("docs", "dr_drill_result.json"))
    assert all(dr["checks"].values()) and dr["rows_lost"] >= 0
    assert dr["rto_seconds"] < 15 * 60  # S4: RTO <= 15 minutes
    assert "NOT a production topology" in dr["what"]
    load = json.loads(_text("docs", "load_postgres_result.json"))
    assert load["server_errors"] == 0 and load["problems"] == []
    assert load["latency_seconds"]["p95"] < 2.5  # S2 threshold
