"""GLOBIN's command line: the one entry point, and what it will answer.

Two ways in and one implementation. ``globin`` is the console script
``pyproject.toml`` declares; ``python -m globin`` reaches the same
:func:`main` through :mod:`globin.__main__`. Neither wrapper holds logic, so
there is no path by which the two could answer differently — a property
``tests/contract/test_bootstrap_contract.py`` asserts rather than assumes.

**The parser is written out.** ``argparse`` would do this, and ADR-0019 rejected
it as disproportionate for the quality entrypoint; the same argument holds here,
and the repository has none of it anywhere, which is a consistency worth keeping
until something actually needs it. The rules it enforces are the ones every other
GLOBIN command line enforces: an unrecognised word is refused rather than
ignored, no abbreviation is accepted, and the default is the subcommand that
changes nothing.

**Under ``--json``, standard output carries JSON and nothing else.** Human text
goes to standard error. A caller piping this into a parser gets a document; a
person watching the terminal still sees what happened.

**Both renderings come from one report.** The human table and the JSON document
are two views of the same :class:`~globin.domain.bootstrap.BootstrapReport`, so a
check cannot appear in one and not the other — which is what a second doctor
implementation would eventually produce.

This module performs no work when imported. Nothing below the function
definitions runs, no environment is read, no file is opened and no directory is
created, which is ``ENGINEERING_CONTRACT.md`` invariant 5 and the reason
``globin --help`` cannot fail because of a machine it never looked at.
"""

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from globin.adapters.bootstrap import build
from globin.domain.bootstrap import BootstrapOutcome, CheckStatus, ExitCode
from globin.errors import GlobinError
from globin.project_contract import PROJECT_NAME
from globin.runtime.composition import Bootstrap, build_bootstrap, project_identity

DOCTOR: Final[str] = "doctor"
BOOTSTRAP: Final[str] = "bootstrap"
CHECK: Final[str] = "check"
EVIDENCE: Final[str] = "evidence"
VERSION: Final[str] = "--version"
JSON_FLAG: Final[str] = "--json"
HELP_WORDS: Final[tuple[str, ...]] = ("-h", "--help")
"""Both spellings of the help request.

A tuple rather than a :class:`frozenset` for the reason
:data:`~globin.domain.bootstrap.CREATED_PATHS` gives: ``frozenset(...)`` is a
call, and a layer package performs none at import.
"""

BOOTSTRAP_SUBCOMMANDS: Final[tuple[str, ...]] = (CHECK, EVIDENCE)
"""What may follow ``bootstrap``. ``check`` is the default and changes nothing."""

USAGE: Final[str] = """usage: globin [--version] [doctor|bootstrap] [check|evidence] [--json]

GLOBIN's local entry point. It performs no network access of any kind: no
exchange is contacted, no credential is read and no order is placed. See
docs/engineering/BOOTSTRAP.md.

Commands:
  doctor              Report on this host, and keep going past a problem.
  bootstrap check     Refuse to start unless every check passes. Stops at the
                      first refusal. This is the gate a launcher runs.
  bootstrap evidence  Run the gate and write .globin/bootstrap/bootstrap-manifest.json.

Options:
  --json              Write the machine-readable document to standard output,
                      and nothing else. Human text goes to standard error.
  --version           Print the version and exit.
  -h, --help          Print this and exit.

Exit codes:
   0  every check passed
   1  the run could not be completed
   2  the command line was not understood
   3  a check could not be measured, which is never a pass
  10  this host is not a supported one
  11  this interpreter is not the declared one
  12  this is not the project's own environment
  13  a declared dependency is missing or unlocked
  14  the configuration did not validate
  15  a required secret reference did not resolve
  16  the project root or its runtime tree is unusable
  17  the bootstrap failed in a way it does not account for
  18  this GLOBIN could not state its own name and version
"""


class UsageError(Exception):
    """The command line was not understood.

    Not a :class:`~globin.errors.GlobinError`: nothing about GLOBIN failed, and
    the taxonomy is about faults rather than about typing mistakes.
    """


@dataclass(frozen=True, slots=True)
class Invocation:
    """A parsed command line.

    Args:
        command: One of ``doctor``, ``bootstrap check``, ``bootstrap evidence``,
            ``--version`` or the help word.
        as_json: Whether the machine-readable document was asked for.
    """

    command: str
    as_json: bool = False


def parse(argv: Sequence[str]) -> Invocation:
    """Read a command line.

    Args:
        argv: The arguments after the program name.

    Returns:
        What was asked for.

    Raises:
        UsageError: If a word is unrecognised, repeated, or means nothing where
            it appears. Refused rather than ignored: a flag that silently does
            nothing is how a caller ends up believing it asked for something.
    """
    words = list(argv)
    if not words:
        msg = "no command was given"
        raise UsageError(msg)

    head = words[0]
    if head in HELP_WORDS:
        _no_more(words[1:], head)
        return Invocation(command=head)
    if head == VERSION:
        _no_more(words[1:], head)
        return Invocation(command=VERSION)
    if head == DOCTOR:
        return Invocation(command=DOCTOR, as_json=_json_only(words[1:], DOCTOR))
    if head == BOOTSTRAP:
        return _parse_bootstrap(words[1:])
    msg = f"unrecognised argument: {head!r}"
    raise UsageError(msg)


def _parse_bootstrap(rest: Sequence[str]) -> Invocation:
    """Read what follows ``bootstrap``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, or ``--json`` is asked of
            ``evidence``, whose output is a file rather than a stream.
    """
    words = list(rest)
    subcommand = CHECK
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in BOOTSTRAP_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    as_json = _json_only(words, f"{BOOTSTRAP} {subcommand}")
    if as_json and subcommand == EVIDENCE:
        msg = (
            f"{JSON_FLAG} means nothing with {EVIDENCE}, which writes a file; "
            f"use `{BOOTSTRAP} {CHECK} {JSON_FLAG}` to read the same document on standard output"
        )
        raise UsageError(msg)
    return Invocation(command=f"{BOOTSTRAP} {subcommand}", as_json=as_json)


def _json_only(words: Sequence[str], context: str) -> bool:
    """Accept ``--json`` and nothing else.

    Args:
        words: The remaining words.
        context: What they followed, for the message.

    Returns:
        Whether ``--json`` was given.

    Raises:
        UsageError: If anything else appears, or ``--json`` appears twice.
    """
    seen = False
    for word in words:
        if word != JSON_FLAG:
            msg = f"unrecognised argument after {context}: {word!r}"
            raise UsageError(msg)
        if seen:
            msg = f"{JSON_FLAG} was given twice"
            raise UsageError(msg)
        seen = True
    return seen


def _no_more(words: Sequence[str], head: str) -> None:
    """Refuse anything after a word that takes nothing.

    Args:
        words: The remaining words.
        head: What they followed, for the message.

    Raises:
        UsageError: If there is anything left.
    """
    if words:
        msg = f"{head} takes no arguments, and was given {words[0]!r}"
        raise UsageError(msg)


def render_human(outcome: BootstrapOutcome) -> str:
    """The report as a person reads it.

    Args:
        outcome: What the run concluded.

    Returns:
        One line per check, then the remediation for anything that did not pass.

    The column width is computed from the identifiers actually present rather
    than fixed, so a check added by a later phase cannot push the table out of
    alignment or be silently truncated.
    """
    checks = outcome.report.outcomes
    if not checks:
        return "no check ran.\n"
    width = max(len(check.identifier) for check in checks)
    lines = [
        f"  {check.status.value.upper():<10} {check.identifier:<{width}}  {check.summary}"
        for check in checks
    ]
    problems = [check for check in checks if check.status is not CheckStatus.PASS]
    if problems:
        lines.append("")
        lines.extend(f"  {check.identifier}: {check.remediation}" for check in problems)
    lines.append("")
    lines.append(
        f"{PROJECT_NAME} is ready." if outcome.ready else f"{PROJECT_NAME} will not start."
    )
    return "\n".join(lines) + "\n"


def render_json(outcome: BootstrapOutcome) -> str:
    """The report as a machine reads it.

    Args:
        outcome: What the run concluded.

    Returns:
        The same document the evidence file carries, so that reading the stream
        and reading the artefact cannot disagree.
    """
    return json.dumps(build(outcome), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    start: Path | None = None,
) -> int:
    """Run one command.

    Args:
        argv: The arguments after the program name. Defaults to
            :data:`sys.argv`'s tail, which is what the console script wrapper
            gives it — it calls ``main()`` with nothing.
        stdout: Where the answer goes. Defaults to :data:`sys.stdout`, read here
            rather than captured as a default argument, which would bind it at
            import.
        stderr: Where human text goes under ``--json``. Defaults to
            :data:`sys.stderr`.
        start: Where to begin the search for the project root. Defaults to the
            working directory.

    Returns:
        The exit code. This function never raises: every fault becomes a code and
        a sentence, because a traceback is not a user interface.
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    try:
        invocation = parse(sys.argv[1:] if argv is None else argv)
    except UsageError as fault:
        print(f"globin: {fault}", file=err)
        print(USAGE, file=err)
        return int(ExitCode.USAGE)

    if invocation.command in HELP_WORDS:
        print(USAGE, file=out)
        return int(ExitCode.OK)
    if invocation.command == VERSION:
        return _version(out, err)

    try:
        return _bootstrap(invocation, out=out, err=err, start=start)
    except (GlobinError, OSError) as fault:
        print(f"globin: the bootstrap could not be completed: {fault}", file=err)
        return int(ExitCode.INTERNAL)


def _version(out: TextIO, err: TextIO) -> int:
    """Print the version.

    Args:
        out: Where it goes.
        err: Where a failure is reported.

    Returns:
        The exit code.

    Read from installed metadata, falling back to the imported package. There is
    no second version string anywhere: ``pyproject.toml`` declares the version
    dynamic and points at ``src/globin/__init__.py``, which is the one source
    ADR-0049 requires.
    """
    identity = project_identity()
    if identity is None:
        print("globin: this GLOBIN could not state its own version", file=err)
        return int(ExitCode.PROJECT_UNIDENTIFIED)
    print(identity.version, file=out)
    return int(ExitCode.OK)


def _bootstrap(invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None) -> int:
    """Run the pipeline and report it.

    Args:
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the search for the project root.

    Returns:
        The exit code.

    Raises:
        GlobinError: If the bootstrap failed in a way it does not account for.
            Caught by :func:`main`, which is the only place that decides a
            traceback is not shown.
        OSError: If evidence could not be written.
    """
    wanted_evidence = invocation.command.endswith(EVIDENCE)
    bootstrap = build_bootstrap(Path.cwd() if start is None else start)
    outcome = bootstrap.run(stop_at_first_refusal=invocation.command != DOCTOR)

    if invocation.as_json:
        print(render_json(outcome), file=out)
        print(render_human(outcome), end="", file=err)
    else:
        print(render_human(outcome), end="", file=out)

    if wanted_evidence:
        _record(bootstrap, outcome, out=out, err=err, as_json=invocation.as_json)
    return int(outcome.exit_code)


def _record(
    bootstrap: Bootstrap,
    outcome: BootstrapOutcome,
    *,
    out: TextIO,
    err: TextIO,
    as_json: bool,
) -> None:
    """Write the evidence and say where it went.

    Args:
        bootstrap: The wired bootstrap, which knows the root.
        outcome: What the run concluded.
        out: Where the confirmation goes.
        err: Where it goes instead under ``--json``.
        as_json: Whether standard output is reserved for the document.

    Raises:
        BootstrapManifestError: If the run does not render deterministically, or
            there is no project root to write inside.
        OSError: If the file could not be written.

    A refused run still writes its evidence. A gate that failed silently and left
    no artefact is indistinguishable from a gate that never ran, which is the
    reasoning ``tools/quality/runtime`` gives for the same choice.
    """
    written = bootstrap.record(outcome)
    where = written.path or "outside the project"
    print(f"evidence: {where}", file=err if as_json else out)
