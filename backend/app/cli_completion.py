"""Shell completion scripts generated from the CLI's own argparse tree (Phase 18).

Because they are derived from the parser, a new subcommand or option is completed automatically and
``test_phase18_cli`` checks that every subcommand appears in every shell's script.
"""

import argparse


def tree(parser: argparse.ArgumentParser) -> tuple[list[str], dict[str, list[str]]]:
    """Top-level options, and for each subcommand its options and fixed choices."""
    top = [o for a in parser._actions for o in a.option_strings]
    subs: dict[str, list[str]] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sp in action.choices.items():
                words = [o for a in sp._actions for o in a.option_strings]
                for a in sp._actions:
                    if a.choices:
                        words.extend(str(c) for c in a.choices)
                subs[name] = words
    return top, subs


def completion_script(shell: str, parser: argparse.ArgumentParser) -> str:
    top, subs = tree(parser)
    commands = " ".join(subs)
    if shell == "bash":
        cases = "\n".join(f'    {n}) opts="{" ".join(w)}" ;;' for n, w in subs.items())
        return (
            "_loopforge() {\n"
            "  local cur=${COMP_WORDS[COMP_CWORD]} cmd=${COMP_WORDS[1]} opts\n"
            '  if [ "$COMP_CWORD" -eq 1 ]; then\n'
            f'    COMPREPLY=($(compgen -W "{commands} {" ".join(top)}" -- "$cur"))\n'
            "    return\n"
            "  fi\n"
            "  case $cmd in\n"
            f'{cases}\n    *) opts="" ;;\n'
            "  esac\n"
            '  COMPREPLY=($(compgen -W "$opts" -- "$cur"))\n'
            "}\n"
            "complete -F _loopforge loopforge\n"
        )
    if shell == "zsh":
        cases = "\n".join(f"    {n}) _values 'option' {' '.join(w)} ;;" for n, w in subs.items())
        return (
            "#compdef loopforge\n"
            "_loopforge() {\n"
            "  if (( CURRENT == 2 )); then\n"
            f"    _values 'command' {commands} {' '.join(top)}\n"
            "    return\n"
            "  fi\n"
            "  case $words[2] in\n"
            f"{cases}\n"
            "  esac\n"
            "}\n"
            '_loopforge "$@"\n'
        )
    if shell == "fish":
        lines = [f"complete -c loopforge -f -n '__fish_use_subcommand' -a '{commands}'"]
        for opt in top:
            if opt.startswith("--"):
                lines.append(f"complete -c loopforge -l {opt[2:]}")
        for n, w in subs.items():
            lines.append(
                f"complete -c loopforge -f -n '__fish_seen_subcommand_from {n}' -a '{' '.join(w)}'"
            )
        return "\n".join(lines) + "\n"
    raise ValueError(f"unsupported shell: {shell}")
