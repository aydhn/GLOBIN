"""The command line for the runtime gate.

Hand-written, like every other sub-command here. There are two subcommands and two
options, so :mod:`argparse` would be more machinery than the problem has — and this
repository has no argparse anywhere, which is a consistency worth keeping until
something actually needs it.

Every unrecognised word is refused rather than ignored. A typo that silently ran
the default command would be bad enough on a gate that only reports; on one that
can remove a directory, it is the difference between a diagnosis and a deletion.

**The options only mean anything with ``bootstrap``, and passing them to ``check``
is an error rather than a no-op.** ``check --recreate`` reads like a request to
rebuild something, and accepting it while doing nothing of the sort would be worse
than refusing it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from tools.quality.runtime.gate import EXIT_UNMEASURED, run_runtime

EXIT_USAGE: Final[int] = 2
"""Distinct from every verdict code, so that "you typed it wrong" is never
mistaken for "the host is in trouble"."""

CHECK: Final[str] = "check"
BOOTSTRAP: Final[str] = "bootstrap"

SUBCOMMANDS: Final[frozenset[str]] = frozenset({CHECK, BOOTSTRAP})

RECREATE: Final[str] = "--recreate"
INSTALL_PYTHON: Final[str] = "--install-python"
FROM_PINS: Final[str] = "--from-pins"

OPTIONS: Final[frozenset[str]] = frozenset({RECREATE, INSTALL_PYTHON, FROM_PINS})

USAGE: Final[str] = """\
usage: python -m tools.quality.runtime [check|bootstrap]
           [--recreate] [--install-python] [--from-pins]

  check       Compare this host against docs/engineering/runtime-contract.toml
              and write the manifest. Changes nothing: no directory is created,
              no package is installed, no host setting is touched. The default.

  bootstrap   Everything check does, and build the project environment as well:
              create .venv from the running interpreter and install the toolchain
              recorded in pylock.dev.toml, hash-checked.

  --recreate        Remove an existing .venv before creating it. Refused unless
                    the target is exactly .venv at the repository root and is not
                    a link. bootstrap only.
  --install-python  Permit installing a missing runtime through the Python
                    install manager. Opt-in because it changes the host, and a
                    no-op where no manager is present. bootstrap only.
  --from-pins       Install the exact versions .github/workflows/ pins instead of
                    the lock. The documented recovery path for a lock that cannot
                    be installed from, and it installs the seven direct tools
                    rather than all forty-nine. bootstrap only.

Run check through the environment's own interpreter, or it measures the wrong one:

  .venv\\Scripts\\python.exe -m tools.quality.runtime

Neither subcommand edits the registry, the PATH, the execution policy or any
runtime outside .venv. Where a host setting is wrong, the gate says so and names
the official remedy rather than applying one.

Exit codes:
  0  every check passed
  1  a check failed
  2  the command line was not understood
  3  a check could not be measured, which is never a pass
"""


class UsageError(Exception):
    """The command line was not understood."""


@dataclass(frozen=True, slots=True)
class Invocation:
    """What the command line asked for.

    Args:
        bootstrap: Whether to build the environment as well as check it.
        recreate: Whether an existing environment may be removed first.
        install_python: Whether a missing runtime may be installed.
        from_pins: Whether to install the workflow pins rather than the lock.
    """

    bootstrap: bool = False
    recreate: bool = False
    install_python: bool = False
    from_pins: bool = False


def parse(argv: Sequence[str]) -> Invocation:
    """Read the command line.

    Args:
        argv: The arguments after the module name.

    Returns:
        What was asked for.

    Raises:
        UsageError: If a word is not recognised, a subcommand or option is
            repeated, or an option is passed to ``check``.

    ``check`` is accepted as well as omitted, so that the explicit spelling works
    for anybody who prefers it, and so that adding ``bootstrap`` did not change
    what existing callers must type.
    """
    chosen: str | None = None
    seen: set[str] = set()

    for word in argv:
        if word in SUBCOMMANDS and chosen is None:
            chosen = word
        elif word in OPTIONS and word not in seen:
            seen.add(word)
        else:
            msg = f"unrecognised argument: {word!r}"
            raise UsageError(msg)

    bootstrap = chosen == BOOTSTRAP
    if seen and not bootstrap:
        offered = ", ".join(sorted(seen))
        msg = f"{offered} only means something with `bootstrap`"
        raise UsageError(msg)

    return Invocation(
        bootstrap=bootstrap,
        recreate=RECREATE in seen,
        install_python=INSTALL_PYTHON in seen,
        from_pins=FROM_PINS in seen,
    )


def main(argv: Sequence[str]) -> int:
    """Run the gate.

    Args:
        argv: The arguments after the module name.

    Returns:
        The gate's exit code, or :data:`EXIT_USAGE` when the command line was not
        understood.
    """
    try:
        invocation = parse(argv)
    except UsageError as fault:
        print(f"runtime: {fault}")
        print(USAGE)
        return EXIT_USAGE
    try:
        return run_runtime(
            bootstrap=invocation.bootstrap,
            recreate=invocation.recreate,
            install_python=invocation.install_python,
            from_pins=invocation.from_pins,
        )
    except OSError as fault:
        print(f"runtime: the gate could not write its artefacts: {fault}")
        return EXIT_UNMEASURED
