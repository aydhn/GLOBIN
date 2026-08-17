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
from globin.adapters.health import snapshot_document
from globin.adapters.identifiers import new_run_id
from globin.adapters.observability import new_correlation_id
from globin.adapters.telemetry_otel import opentelemetry_bridge
from globin.adapters.telemetry_prometheus import LOOPBACK_ADDRESS, prometheus_publisher
from globin.domain.bootstrap import BootstrapOutcome, CheckStatus, ExitCode
from globin.domain.configuration import (
    GlobinConfig,
    config_fingerprint,
    default_layer,
    resolve,
)
from globin.domain.health import RuntimeHealthSnapshot, RuntimeHealthState
from globin.domain.metrics import declared_series, metrics
from globin.domain.runtime_state import RuntimeArea
from globin.errors import GlobinError
from globin.project_contract import PROJECT_NAME
from globin.runtime.composition import (
    BUNDLE_MANIFEST_MEMBER,
    BUNDLE_REPORT_MEMBER,
    DEFAULT_PROFILE,
    WATCHDOG_FILE,
    Bootstrap,
    RuntimeState,
    build_bootstrap,
    build_bundle_builder,
    build_configuration,
    build_health_collector,
    build_logger,
    build_runtime_state,
    bundle_candidates,
    project_identity,
)

DOCTOR: Final[str] = "doctor"
BOOTSTRAP: Final[str] = "bootstrap"
CHECK: Final[str] = "check"
EVIDENCE: Final[str] = "evidence"
DIAGNOSTICS: Final[str] = "diagnostics"
SNAPSHOT: Final[str] = "snapshot"
BUNDLE: Final[str] = "bundle"
MEMORY: Final[str] = "memory"

WATCHDOG: Final[str] = "watchdog"

TELEMETRY: Final[str] = "telemetry"
"""Report what telemetry would record and whether any of it leaves. Reads only."""
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

DIAGNOSTICS_SUBCOMMANDS: Final[tuple[str, ...]] = (
    SNAPSHOT,
    BUNDLE,
    MEMORY,
    WATCHDOG,
    TELEMETRY,
)
"""What may follow ``diagnostics``. ``snapshot`` is the default.

``memory`` is a separate word rather than a flag on ``snapshot`` because it
does something ``snapshot`` does not: it starts the interpreter's allocator
tracer, which costs the whole process on every allocation while it runs. A flag
invites somebody to add it to a script that runs every minute; a verb reads like
the deliberate act it is.
"""

USAGE: Final[str] = """usage: globin [--version] [doctor|bootstrap|diagnostics]
                     [subcommand] [--json]

GLOBIN's local entry point. It performs no network access of any kind: no
exchange is contacted, no credential is read and no order is placed. See
docs/engineering/BOOTSTRAP.md.

Commands:
  doctor              Report on this host, and keep going past a problem.
  bootstrap check     Refuse to start unless every check passes. Stops at the
                      first refusal. This is the gate a launcher runs.
  bootstrap evidence  Run the gate and write .globin/bootstrap/bootstrap-manifest.json.
  diagnostics snapshot  Measure this runtime once and report its health.
  diagnostics bundle    Write a redacted support archive and print its digest.
  diagnostics memory    Snapshot with the allocator tracer on, then off again.
  diagnostics watchdog  Report the liveness policy and the last recorded stall.
  diagnostics telemetry Report what telemetry declares, and whether any of it
                        leaves this machine. Records nothing and binds nothing.
                        Reads; starts no watchdog and changes nothing.

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
  19  the recorded runtime state could not be read
  20  another GLOBIN coordinator is already running on this machine
  21  the runtime state could not be written
  22  a diagnostic could not be produced, which is not a health verdict
  23  the watchdog ended this process, which did not stop when asked
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
    if head == DIAGNOSTICS:
        return _parse_diagnostics(words[1:])
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

    if invocation.command.startswith(DIAGNOSTICS):
        try:
            return _diagnostics(invocation, out=out, err=err)
        except (GlobinError, OSError) as fault:
            print(f"globin: the diagnostic could not be produced: {fault}", file=err)
            return int(ExitCode.DIAGNOSTICS_FAILED)

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


def _parse_diagnostics(rest: Sequence[str]) -> Invocation:
    """Read what follows ``diagnostics``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, or ``--json`` is asked of
            ``bundle``, whose output is an archive rather than a stream.

    ``snapshot`` is the default, for the reason ``check`` is ``bootstrap``'s: it
    is the reading a person wants when they type the noun and nothing else, and it
    changes nothing on disk.
    """
    words = list(rest)
    subcommand = SNAPSHOT
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in DIAGNOSTICS_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    as_json = _json_only(words, f"{DIAGNOSTICS} {subcommand}")
    if as_json and subcommand == BUNDLE:
        msg = (
            f"{JSON_FLAG} means nothing with {BUNDLE}, which writes an archive; "
            f"use `{DIAGNOSTICS} {SNAPSHOT} {JSON_FLAG}` to read the same document"
        )
        raise UsageError(msg)
    return Invocation(command=f"{DIAGNOSTICS} {subcommand}", as_json=as_json)


def render_snapshot_json(snapshot: RuntimeHealthSnapshot) -> str:
    """The snapshot as one line of canonical JSON.

    Args:
        snapshot: What was measured.

    Returns:
        The document, with sorted keys and no incidental whitespace.

    The same renderer the bundle uses, so the file inside an archive and the bytes
    on standard output are identical for the same snapshot. A second renderer
    would be a second thing to keep true.
    """
    return json.dumps(
        snapshot_document(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def render_snapshot_human(snapshot: RuntimeHealthSnapshot) -> str:
    """The snapshot as text a person reads.

    Args:
        snapshot: What was measured.

    Returns:
        One line per check, then the aggregate.

    Severity first on every line, so the column an eye scans is the one that says
    whether to keep reading. An unmeasured check is printed like any other rather
    than hidden, because the count of things nobody could measure is exactly what
    an operator needs when a state looks better than they expected.
    """
    lines = [
        f"GLOBIN {snapshot.version} — {snapshot.platform.implementation} "
        f"{snapshot.platform.python_version} on {snapshot.platform.system}",
        f"profile {snapshot.profile}  pid {snapshot.process.pid}  "
        f"uptime {snapshot.uptime.nanoseconds // 1_000_000_000}s",
        "",
    ]
    for result in snapshot.results:
        marker = str(result.severity).upper().ljust(7)
        lines.append(f"  {marker} {result.identifier:<24} {result.summary}")
    unmeasurable = snapshot.unmeasurable()
    lines.append("")
    lines.append(f"state: {snapshot.state}")
    if unmeasurable:
        lines.append(f"unmeasurable: {len(unmeasurable)} ({', '.join(unmeasurable)})")
    return "\n".join(lines) + "\n"


def exit_code_for_state(state: RuntimeHealthState) -> ExitCode:
    """Which code one health state produces.

    Args:
        state: What the snapshot concluded.

    Returns:
        The exit code.

    The three codes every gate under ``tools/`` already speaks, so a script that
    branches on one command branches on this one. ``DIAGNOSTICS_FAILED`` is not
    here on purpose: it means no snapshot could be produced, which is a failure to
    measure a state rather than a state.
    """
    if state is RuntimeHealthState.UNHEALTHY:
        return ExitCode.GATE_FAILED
    if state is RuntimeHealthState.DEGRADED:
        return ExitCode.UNMEASURED
    return ExitCode.OK


def _diagnostics(invocation: Invocation, *, out: TextIO, err: TextIO) -> int:
    """Take a snapshot, or build a bundle from one.

    Args:
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.

    Returns:
        The exit code.

    **This command starts no diagnostics subsystem and takes no lock.** It reads
    the runtime tree, probes the lock by acquiring and releasing it, and exits.
    A read-only command that took the production lock would refuse to run beside
    a running GLOBIN, which is the trap ADR-0057 already declined for ``doctor``.
    """
    state = build_runtime_state()
    config = build_configuration()
    if invocation.command.endswith(WATCHDOG):
        return _watchdog(state, config, invocation, out=out, err=err)
    if invocation.command.endswith(TELEMETRY):
        return _telemetry(config, invocation, out=out, err=err)
    wants_memory = invocation.command.endswith(MEMORY)
    # Standard error, always. Under `--json` standard output carries the
    # document and nothing else, and a log record printed beside it would
    # break the one contract the flag makes. Without `--json` the human table
    # goes to standard output and a record interleaved with it would be noise.
    collector = build_health_collector(
        state, config=config, logger=build_logger(stream=err, config=config)
    )
    memory_probe = collector.memory_probe
    if wants_memory:
        memory_probe.start(config.diagnostics.tracemalloc_frame_depth)
    try:
        snapshot = collector.snapshot(
            correlation_id=new_correlation_id(),
            run_id=str(new_run_id()),
            version=_version_string(),
            profile=DEFAULT_PROFILE,
            config_fingerprint=config_fingerprint(resolve((default_layer(),))),
            context_fingerprint="",
            include_memory=wants_memory,
            memory_top=config.diagnostics.tracemalloc_top,
        )
    finally:
        if wants_memory:
            memory_probe.stop()

    if invocation.command.endswith(BUNDLE):
        return _bundle(state, config, snapshot, out=out, err=err)

    if invocation.as_json:
        print(render_snapshot_json(snapshot), file=out)
        print(render_snapshot_human(snapshot), end="", file=err)
    else:
        print(render_snapshot_human(snapshot), end="", file=out)
    return int(exit_code_for_state(snapshot.state))


def _watchdog(
    state: RuntimeState,
    config: GlobinConfig,
    invocation: Invocation,
    *,
    out: TextIO,
    err: TextIO,
) -> int:
    """Report the liveness policy, and the last stall this machine recorded.

    Args:
        state: The runtime tree the incident is read from.
        config: Where the thresholds come from.
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.

    Returns:
        :attr:`~globin.domain.bootstrap.ExitCode.OK` when no stall has been
        recorded, and :attr:`~globin.domain.bootstrap.ExitCode.GATE_FAILED` when
        one has.

    **It starts no watchdog**, which is why it can be run beside a running GLOBIN.
    A command that armed one would start a thread able to end the process it was
    asked to describe.

    **A recorded incident is a failure, and that is a deliberate reading.** The
    document only exists because a run was stopped for not making progress, so a
    launcher branching on this code learns "the last run here went wrong" rather
    than "a watchdog is configured". Delete the file to clear it — nothing in
    GLOBIN removes it, because the evidence outliving the run is the point.
    """
    policy = config.watchdog.policy()
    recorded = state.store.read(RuntimeArea.STATE, WATCHDOG_FILE)
    document: dict[str, object] = {
        "enabled": config.watchdog.enabled,
        "escalation_enabled": config.watchdog.escalation_enabled,
        "interval_millis": policy.interval_millis,
        "grace_millis": policy.grace_millis,
        "stall_millis": policy.stall_millis,
        "escalate_millis": policy.escalate_millis,
        "deadline_millis": policy.stall_millis + policy.escalate_millis,
        "incident": dict(recorded) if recorded is not None else None,
    }
    human = _watchdog_text(document)
    if invocation.as_json:
        print(json.dumps(document, sort_keys=True, separators=(",", ":")), file=out)
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    return int(ExitCode.OK if recorded is None else ExitCode.GATE_FAILED)


def _telemetry(
    config: GlobinConfig,
    invocation: Invocation,
    *,
    out: TextIO,
    err: TextIO,
) -> int:
    """Report the telemetry contract, and whether anything leaves this machine.

    Args:
        config: Where the settings come from.
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.

    Returns:
        :attr:`~globin.domain.bootstrap.ExitCode.OK`, always.

    **It records nothing, starts nothing and binds nothing.** It builds no store,
    no pump and no thread; it reports what the registry declares and what the
    configuration would do. A dropped observation is a fact about the observation
    rather than about the work, so it is not a failing exit code — making it one
    would let a launcher restart a healthy process because a metric was refused.

    **Exit code 24 stays free.** If a later phase wants a *gate* that fails when
    export is unhealthy, that is a different command with different semantics, and
    that is when a new code is earned.
    """
    otel = opentelemetry_bridge()
    prometheus = prometheus_publisher()
    document: dict[str, object] = {
        "enabled": config.telemetry.enabled,
        "export_enabled": config.telemetry.export_enabled,
        "listener_enabled": config.telemetry.listener_enabled,
        "listener_address": LOOPBACK_ADDRESS,
        "listener_port": config.telemetry.listener_port,
        "queue_capacity": config.telemetry.queue_capacity,
        "batch_size": config.telemetry.batch_size,
        "flush_millis": config.telemetry.flush_millis,
        "metrics": [
            {
                "name": descriptor.name,
                "kind": descriptor.kind.value,
                "unit": descriptor.unit.value,
                "attributes": list(descriptor.keys()),
                "declared_series": declared_series(descriptor),
                "budget": descriptor.cardinality_budget,
            }
            for descriptor in metrics()
        ],
        "libraries": {
            "opentelemetry": {"available": otel.available, "reason": otel.reason},
            "prometheus_client": {"available": prometheus.available, "reason": prometheus.reason},
        },
    }
    human = _telemetry_text(document)
    if invocation.as_json:
        print(json.dumps(document, sort_keys=True, separators=(",", ":")), file=out)
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    return int(ExitCode.OK)


def _telemetry_text(document: dict[str, object]) -> str:
    """The human rendering of the telemetry report.

    Args:
        document: What :func:`_telemetry` assembled.

    Returns:
        The text, ending in a newline.

    Built from the same mapping the JSON rendering uses, so the two cannot say
    different things.
    """
    lines = [
        f"recording   {'on' if document['enabled'] else 'off'}",
        f"export      {'on' if document['export_enabled'] else 'off'}",
        f"listener    {'on' if document['listener_enabled'] else 'off'} "
        f"({document['listener_address']}:{document['listener_port']})",
    ]
    families = document["metrics"]
    if isinstance(families, list):
        lines.append(f"metrics     {len(families)} declared")
        for family in families:
            if isinstance(family, dict):
                lines.append(
                    f"  {family['name']:<44} {family['kind']:<9} "
                    f"{family['declared_series']}/{family['budget']} series"
                )
    libraries = document["libraries"]
    if isinstance(libraries, dict):
        for name, state in sorted(libraries.items()):
            if isinstance(state, dict):
                lines.append(f"  {name:<20} {'present' if state['available'] else 'absent'}")
    return chr(10).join(lines) + chr(10)


def _watchdog_text(document: dict[str, object]) -> str:
    """The human rendering of the watchdog report.

    Args:
        document: What :func:`_watchdog` assembled.

    Returns:
        The text, ending in a newline.

    Built from the same mapping the JSON rendering uses, so the two cannot say
    different things — the property both bootstrap renderings already have.
    """
    incident = document.get("incident")
    lines = [
        f"watchdog: {'enabled' if document['enabled'] else 'disabled'}",
        f"  interval   {document['interval_millis']} ms",
        f"  grace      {document['grace_millis']} ms",
        f"  stall      {document['stall_millis']} ms",
        f"  escalate   {document['escalate_millis']} ms"
        f"  (deadline {document['deadline_millis']} ms from the stall)",
        f"  hard exit  {'enabled' if document['escalation_enabled'] else 'disabled'}",
    ]
    if not isinstance(incident, dict):
        lines.append("incident: none recorded")
    else:
        lines.append(f"incident: {incident.get('incident_id', '')}")
        lines.append(f"  component  {incident.get('component', '')}")
        lines.append(f"  detected   {incident.get('detected_at', '')}")
        lines.append(f"  reason     {incident.get('reason', '')}")
        lines.append(f"  escalated  {incident.get('escalated', False)}")
    return "\n".join(lines) + "\n"


def _bundle(
    state: object,
    config: GlobinConfig,
    snapshot: RuntimeHealthSnapshot,
    *,
    out: TextIO,
    err: TextIO,
) -> int:
    """Build, validate and publish a support bundle.

    Args:
        state: The runtime tree.
        config: Resolved configuration, for the limits.
        snapshot: The snapshot to put inside it.
        out: Where the path and digest go.
        err: Where a refusal is reported.

    Returns:
        The exit code — ``0`` when published, ``22`` when it could not be.

    The health *state* deliberately does not decide this code. A bundle built from
    an unhealthy runtime is a successful bundle, and it is the one somebody most
    needs; conflating the two would make the command fail exactly when it matters.
    """
    builder, destination = build_bundle_builder(
        state,  # type: ignore[arg-type]
        config=config,
        logger=build_logger(stream=err, config=config),
    )
    payload = render_snapshot_json(snapshot).encode("utf-8")
    try:
        manifest, digest, size = builder.build(
            bundle_candidates(state, payload),  # type: ignore[arg-type]
            manifest_member=BUNDLE_MANIFEST_MEMBER,
            report_member=BUNDLE_REPORT_MEMBER,
        )
    except (GlobinError, OSError) as fault:
        print(f"globin: the support bundle was not published: {fault}", file=err)
        return int(ExitCode.DIAGNOSTICS_FAILED)
    print(f"bundle: {destination}", file=out)
    print(f"digest: {digest}", file=out)
    print(f"members: {len(manifest.entries)}  bytes: {size}", file=out)
    if manifest.exclusions:
        print(f"excluded: {len(manifest.exclusions)} (see report.txt inside)", file=out)
    return int(ExitCode.OK)


def _version_string() -> str:
    """This GLOBIN's version, or an empty string when it cannot say.

    Returns:
        The version.
    """
    identity = project_identity()
    return "" if identity is None else identity.version
