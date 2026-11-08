# ruff: noqa: E501
"""Phase 18: the docs site builds and its link checker really catches broken links, anchors and orphans."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("build_docs", ROOT / "scripts" / "build_docs.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_real_documentation_has_no_broken_internal_links():
    problems, graph = _load().check()
    assert problems == []
    assert len(graph) >= 45  # README, changelog, guides, tutorials and every ADR


@pytest.fixture
def mini(tmp_path, monkeypatch):
    """A tiny documentation tree with the checker pointed at it."""
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DOCS", docs)
    monkeypatch.setattr(mod, "INDEX", docs / "index.md")
    monkeypatch.setattr(mod, "SITE", docs / "_site")
    return mod, docs


def test_a_clean_tree_passes(mini):
    mod, docs = mini
    (docs / "index.md").write_text(
        "# Home\n[A](a.md) and [section](a.md#second-part)\n", encoding="utf-8"
    )
    (docs / "a.md").write_text("# A\n## Second part\n", encoding="utf-8")
    problems, _ = mod.check()
    assert problems == []


def test_missing_file_missing_anchor_and_missing_image_are_reported(mini):
    mod, docs = mini
    (docs / "index.md").write_text(
        "# Home\n[gone](nope.md) [bad anchor](a.md#not-there) ![pic](img.png) [ok](a.md#a)\n",
        encoding="utf-8",
    )
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    problems, _ = mod.check()
    text = "\n".join(problems)
    assert "missing file 'nope.md'" in text
    assert "no such heading in docs/a.md" in text and "not-there" in text
    assert "image to missing file 'img.png'" in text
    assert len(problems) == 3  # the valid anchor produced nothing


def test_an_orphan_page_nobody_links_to_is_reported(mini):
    mod, docs = mini
    (docs / "index.md").write_text("# Home\n[A](a.md)\n", encoding="utf-8")
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    (docs / "lonely.md").write_text("# Lonely\n", encoding="utf-8")
    problems, _ = mod.check()
    assert any("docs/lonely.md: not reachable" in p for p in problems)


def test_links_inside_code_are_ignored_and_external_links_are_not_checked(mini):
    mod, docs = mini
    (docs / "index.md").write_text(
        "# Home\n`[x](missing.md)`\n```\n[y](missing2.md)\n```\n[web](https://example.com/x.md)\n",
        encoding="utf-8",
    )
    assert mod.check()[0] == []


def test_duplicate_headings_get_numbered_anchors_like_the_renderer(mini):
    mod, docs = mini
    (docs / "index.md").write_text("# Home\n[second](a.md#same_1)\n", encoding="utf-8")
    (docs / "a.md").write_text("# A\n## Same\n## Same\n", encoding="utf-8")
    assert mod.check()[0] == []


def test_rendering_writes_html_with_working_cross_links(mini):
    pytest.importorskip("markdown")
    mod, docs = mini
    (docs / "index.md").write_text("# Home\n[A](a.md#part)\n", encoding="utf-8")
    (docs / "a.md").write_text("# A\n## Part\n| h |\n|---|\n| v |\n", encoding="utf-8")
    assert mod.render() >= 2
    index = (docs / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="docs_a.html#part"' in index and "<title>Home - LoopForge</title>" in index
    assert "<table>" in (docs / "_site" / "docs_a.html").read_text(encoding="utf-8")
