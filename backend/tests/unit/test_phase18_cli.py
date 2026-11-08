"""Phase 18: CLI version, shell completions generated from the parser, server-side delegation."""

import json
import re
from pathlib import Path

import pytest

from app import cli, cli_completion, keys_cli, ops_cli
from app.version import __version__

ROOT = Path(__file__).resolve().parents[3]


def test_version_flag_prints_the_single_source_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.strip() == f"loopforge {__version__}"


@pytest.mark.parametrize("shell", cli.SHELLS)
def test_every_subcommand_and_option_appears_in_every_shells_completion(shell, capsys):
    assert cli.main(["completion", shell]) == 0
    script = capsys.readouterr().out
    top, subs = cli_completion.tree(cli.build_parser())
    assert set(subs) == {"run", "publish", "completion", "keys", "ops"}
    for name, words in subs.items():
        assert re.search(rf"\b{name}\b", script), f"{shell}: command {name} missing"
        for word in words:
            if word not in ("-h", "--help"):
                needle = word.lstrip("-") if shell == "fish" else word  # fish: `-l name`
                assert needle in script, f"{shell}: {word} (of {name}) missing"
    for opt in ("version", "url"):
        assert (opt if shell == "fish" else f"--{opt}") in script


def test_bash_completion_is_syntactically_plausible(capsys):
    cli.main(["completion", "bash"])
    script = capsys.readouterr().out
    assert script.count("{") == script.count("}") and "complete -F _loopforge loopforge" in script
    assert script.count("case ") == 1 and script.count("esac") == 1


def test_unknown_shell_is_rejected():
    with pytest.raises(SystemExit):
        cli.main(["completion", "powershell"])
    with pytest.raises(ValueError):
        cli_completion.completion_script("powershell", cli.build_parser())


def test_keys_and_ops_delegate_to_the_server_side_modules(monkeypatch):
    seen = {}
    monkeypatch.setattr(keys_cli, "main", lambda rest: seen.setdefault("keys", rest) and 0)
    monkeypatch.setattr(ops_cli, "main", lambda rest: seen.setdefault("ops", rest) and 3)
    assert cli.main(["keys", "rotate", "--dry-run"]) == 0
    assert seen["keys"] == ["rotate", "--dry-run"]
    assert cli.main(["ops", "set-plan", "acme", "free"]) == 3
    assert seen["ops"] == ["set-plan", "acme", "free"]


def test_remote_commands_still_need_a_token(monkeypatch, capsys):
    monkeypatch.delenv("LOOPFORGE_TOKEN", raising=False)
    assert cli.main(["publish", "t1", "--repo", "o/r"]) == 2
    assert "LOOPFORGE_TOKEN" in capsys.readouterr().err


def test_package_metadata_points_at_the_cli_and_the_single_version():
    text = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'loopforge = "app.cli:main"' in text
    assert 'version = {attr = "app.version.__version__"}' in text
    assert 'dependencies = ["httpx>=0.27"]' in text  # the client needs nothing else
    sdk = (ROOT / "sdk" / "python" / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__.replace("-", "")}"' in sdk
    ts = json.loads((ROOT / "sdk" / "typescript" / "package.json").read_text(encoding="utf-8"))
    assert ts["version"].replace("-rc.", "rc") == __version__.replace("-", "")
