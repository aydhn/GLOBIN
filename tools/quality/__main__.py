"""Command-line surface for the quality entrypoint.

```bash
python -m tools.quality full
```

Argument parsing is deliberately hand-written and about twenty lines long. The
whole interface is one required word chosen from a fixed list; `argparse` would
add indirection and a dependency on its error formatting for no gain.
"""

import sys
from collections.abc import Sequence

from tools.quality.commands import COMMANDS, find
from tools.quality.runner import EXIT_USAGE, run


def usage() -> str:
    """Return the help text, listing every command and what it does."""
    width = max(len(command.name) for command in COMMANDS)
    lines = [
        "usage: python -m tools.quality <command>",
        "",
        "commands:",
        *(f"  {command.name:<{width}}  {command.summary}" for command in COMMANDS),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the named command and return its exit code."""
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in {"-h", "--help"}:
        print(usage())
        # No command is a usage error, not a success. A gate invoked wrongly
        # must never look like a gate that passed.
        return 0 if args else EXIT_USAGE

    name, *rest = args
    if rest:
        print(f"unexpected extra arguments: {' '.join(rest)}\n", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return EXIT_USAGE

    command = find(name)
    if command is None:
        print(f"unknown command: {name}\n", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return EXIT_USAGE

    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
