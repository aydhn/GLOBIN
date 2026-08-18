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
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from globin.adapters.bootstrap import (
    RUNTIME_CONTRACT_PATH,
    SystemEnvironmentProbe,
    TomlRuntimeBaselineSource,
    build,
    find_project_root,
)
from globin.adapters.config_evidence import build as build_config_manifest
from globin.adapters.config_evidence import publish_snapshot, read_snapshot
from globin.adapters.config_evidence import write as write_config_manifest
from globin.adapters.configuration import parse_overrides
from globin.adapters.environment import (
    DECLARED_TOOLCHAIN,
    PathToolchainProbe,
    windows_system_api,
)
from globin.adapters.health import snapshot_document
from globin.adapters.identifiers import new_run_id
from globin.adapters.observability import new_correlation_id
from globin.adapters.telemetry_otel import opentelemetry_bridge
from globin.adapters.telemetry_prometheus import prometheus_publisher
from globin.application.secrets import (
    ENTRY_REMEDIATION,
    REMEDIATION,
    resolve,
    rotate_from_entry,
    set_from_entry,
)
from globin.domain.bootstrap import BootstrapOutcome, CheckStatus, ExitCode, RuntimePaths
from globin.domain.config_evidence import (
    ConfigProvenance,
    compare,
    effective_values,
    evidence_fingerprint,
    provenance_of,
    snapshot_of,
)
from globin.domain.configuration import (
    DiagnosticsHttpConfig,
    GlobinConfig,
    as_config,
    config_fingerprint,
    default_layer,
)
from globin.domain.configuration import resolve as resolve_layers
from globin.domain.diagnostics_http import SCHEMA as ENDPOINT_SCHEMA
from globin.domain.diagnostics_http import SCHEMA_VERSION as ENDPOINT_SCHEMA_VERSION
from globin.domain.diagnostics_http import (
    DiagnosticsRoute,
    ExpositionFormat,
    address_problems,
    content_type_for,
    policy_problems,
    route_paths,
)
from globin.domain.entitlements import (
    GrantDeclaration,
    GrantSet,
    declaration_for,
)
from globin.domain.environment import (
    CapabilityReason,
    EnvironmentCapabilitySnapshot,
    EnvironmentCompatibility,
    compatibility_fingerprint,
)
from globin.domain.health import RuntimeHealthSnapshot, RuntimeHealthState
from globin.domain.identifiers import EnvironmentId
from globin.domain.metrics import declared_series, metrics
from globin.domain.observability import redact
from globin.domain.preflight import PreflightOutcome
from globin.domain.runtime_state import RuntimeArea
from globin.domain.secrets import (
    SecretKind,
    SecretLocator,
    SecretProviderKind,
    SecretReference,
    provider_writable,
)
from globin.errors import ConfigurationError, GlobinError, InternalError, ValidationError
from globin.ports.entitlements import GrantRegister
from globin.ports.secret_entry import SecretEntry
from globin.ports.secrets import SecretStore
from globin.project_contract import PROJECT_NAME
from globin.runtime.composition import (
    BUNDLE_MANIFEST_MEMBER,
    BUNDLE_REPORT_MEMBER,
    WATCHDOG_FILE,
    Bootstrap,
    RuntimeState,
    build_bootstrap,
    build_bundle_builder,
    build_config_sources,
    build_grant_register,
    build_health_collector,
    build_logger,
    build_runtime_state,
    build_secret_entry,
    build_secret_providers,
    build_secret_store,
    bundle_candidates,
    project_identity,
    resolve_run_profile,
    resolve_settings,
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

ENDPOINT: Final[str] = "endpoint"
"""Report the diagnostics surface's configuration and bounds. Binds nothing.

**It does not start a server**, which is why it can be run beside a running GLOBIN
and why `doctor` may reach the same report. A command that bound a socket in order
to describe one would compete with the process it was asked to describe, and could
fail for the single reason — the port is already taken — that means everything is
working.
"""

ENVIRONMENT: Final[str] = "environment"
"""Report what this host is capable of, and whether that is enough. Reads only.

Distinct from ``doctor``, which judges this host against the whole start-up
contract and reports eighteen checks. This reports the capability half in full —
the process and native architectures, the emulation state, every declared tool,
and the compatibility fingerprint — which ``doctor`` reduces to one line.
"""

SECRETS: Final[str] = "secrets"
"""Manage the local credential store. Six verbs and no seventh.

``SECRET_STORE_CONTRACT.md`` section 5 permits exactly: set (interactive entry
only), verify presence (returning a boolean), list (names, environments, kinds
and existence only), delete, rotate, and a backend health check. A contract test
compares :data:`SECRETS_SUBCOMMANDS` against that list, so a seventh verb cannot
arrive without the contract being changed first.
"""

SET: Final[str] = "set"
VERIFY: Final[str] = "verify"
LIST: Final[str] = "list"
DELETE: Final[str] = "delete"
ROTATE: Final[str] = "rotate"
HEALTH: Final[str] = "health"

VERSION: Final[str] = "--version"
JSON_FLAG: Final[str] = "--json"
ENVIRONMENT_FLAG: Final[str] = "--environment"
"""Which deployment target a credential belongs to.

**Never defaulted from** ``--profile``. A profile names a configuration
*document*; an environment names a deployment target, and Phase 035 is where
what an environment guarantees gets decided. Deriving one from the other would
answer that six phases early.
"""

KIND_FLAG: Final[str] = "--kind"
NAME_FLAG: Final[str] = "--name"

PROVIDER_FLAG: Final[str] = "--provider"
"""Which mechanism holds the credential being addressed.

Added by Phase 031, and permitted by ``SECRET_STORE_CONTRACT.md`` §5 on the same
reading that permits ``--environment`` and ``--kind``: the prohibition is on an
option that would place *material* on a command line, and a mechanism name is
ordinary data. Without it an operator cannot address a vault secret at all, and
``secrets health`` could not say which mechanism it checked.
"""

PROFILE_FLAG: Final[str] = "--profile"
"""Which configuration profile this run uses.

The launcher half of Phase 027's selection, and the strongest of the three sources:
above `GLOBIN_PROFILE`, which is above the declared default. Accepted by every
command that resolves configuration, because a report about a profile other than the
one a launcher would use would be a report about a different process.
"""
CONFIG_FLAG: Final[str] = "--config"
"""An explicit configuration document, above the four this layout computes.

**A source selection rather than a field.** It says *which document to read*, not
what any setting is, so it never appears in the provenance as a value and the
answer to "why is this setting what it is" still names the document rather than
the flag that pointed at it.

Unlike the four computed documents, **its absence is fatal.** A missing
``config/local/globin.toml`` means the operator wrote none; a missing
``--config`` means they named one that is not there, and starting anyway on
values they did not choose is the failure this flag exists to make impossible.
The path is resolved to an absolute one before it is read, so two invocations
naming the same document from different working directories are the same
invocation.
"""

SET_FLAG: Final[str] = "--set"
"""One configuration value, for this invocation only. Repeatable.

The strongest source in the chain, and the narrowest act an operator can perform:
a committed document applies to every run, a variable to a shell session, and this
to one. **The typed field registry it is checked against is**
:func:`~globin.domain.configuration.known_keys`, derived from the dataclasses, so
there is no arbitrary path to accept and a key that is not a setting is refused
before its value is looked at.
"""

HELP_WORDS: Final[tuple[str, ...]] = ("-h", "--help")
"""Both spellings of the help request.

A tuple rather than a :class:`frozenset` for the reason
:data:`~globin.domain.bootstrap.CREATED_PATHS` gives: ``frozenset(...)`` is a
call, and a layer package performs none at import.
"""

SECRETS_DOCTOR: Final[str] = "doctor"
"""Report what each mechanism can do, without reading anything an operator stored.

The seventh verb, added by Phase 031 alongside the second and third mechanisms.
``SECRET_STORE_CONTRACT.md`` §5 permits it as "a per-mechanism capability report"
and explains why it is not ``health`` with a wider remit: ``health`` answers
whether *a* backend can be reached, and this answers which of several this host
has. It emits no value and reads no operator secret.
"""

SECRETS_SUBCOMMANDS: Final[tuple[str, ...]] = (
    SET,
    VERIFY,
    LIST,
    DELETE,
    ROTATE,
    HEALTH,
    SECRETS_DOCTOR,
)
"""What may follow ``secrets``. There is no default: two of these write and one
deletes, and guessing which was meant would be guessing about a credential."""

SECRETS_WRITING: Final[tuple[str, ...]] = (SET, ROTATE)
"""The verbs whose primary act is an interactive prompt.

``--json`` is refused for both, exactly as it is for ``bootstrap evidence`` and
``diagnostics bundle``: there is no document for standard output, and offering
one invites somebody to script a prompt.
"""

CONFIG: Final[str] = "config"
"""Ask the configuration about itself. Resolves; changes nothing.

Five verbs, and every one of them reads. ``tomllib`` cannot write, so GLOBIN is
structurally incapable of editing a document an operator wrote — which is the
argument ``CONFIGURATION_LAYOUT.md`` makes for the parser, arriving here as a
property of the command group rather than as a rule somebody has to keep.
"""

VALIDATE: Final[str] = "validate"
EXPLAIN: Final[str] = "explain"
DUMP: Final[str] = "dump"
FINGERPRINT: Final[str] = "fingerprint"

CONFIG_SUBCOMMANDS: Final[tuple[str, ...]] = (VALIDATE, EXPLAIN, DUMP, FINGERPRINT, EVIDENCE)
"""What may follow ``config``. ``validate`` is the default and changes nothing."""

PREFLIGHT: Final[str] = "preflight"
"""Run every check, gate on the result, and say how long the verdict lasts.

**The third combination of two switches that already existed, not a fourth
pipeline.** ``bootstrap check`` stops at the first refusal and gates; ``doctor``
runs everything and reports. A launcher about to start a long-running process
needs both halves — every fault in one pass, and a refusal — and it needs the
one thing neither can say: which of the answers were true only when taken.
"""

BOOTSTRAP_SUBCOMMANDS: Final[tuple[str, ...]] = (CHECK, EVIDENCE, PREFLIGHT)
"""What may follow ``bootstrap``. ``check`` is the default and changes nothing."""

DIAGNOSTICS_SUBCOMMANDS: Final[tuple[str, ...]] = (
    SNAPSHOT,
    BUNDLE,
    MEMORY,
    WATCHDOG,
    TELEMETRY,
    ENDPOINT,
    ENVIRONMENT,
)
"""What may follow ``diagnostics``. ``snapshot`` is the default.

``memory`` is a separate word rather than a flag on ``snapshot`` because it
does something ``snapshot`` does not: it starts the interpreter's allocator
tracer, which costs the whole process on every allocation while it runs. A flag
invites somebody to add it to a script that runs every minute; a verb reads like
the deliberate act it is.
"""

USAGE: Final[str] = """usage: globin [--version] [doctor|bootstrap|config|diagnostics|secrets]
                     [subcommand] [--json] [--profile NAME]
                     [--config PATH] [--set KEY=VALUE]

GLOBIN's local entry point. It performs no network access of any kind: no
exchange is contacted and no order is placed. Since Phase 029 one command
group reads and writes the machine's own credential store, and it still
reaches no network. See docs/engineering/BOOTSTRAP.md.

Commands:
  doctor              Report on this host, and keep going past a problem.
  bootstrap check     Refuse to start unless every check passes. Stops at the
                      first refusal. This is the gate a launcher runs.
  bootstrap evidence  Run the gate and write .globin/bootstrap/bootstrap-manifest.json.
  bootstrap preflight Run every check, refuse unless all of them pass, and
                      report which answers were true only when taken. This is
                      the gate a launcher runs before a long-running process.
  diagnostics snapshot  Measure this runtime once and report its health.
  diagnostics bundle    Write a redacted support archive and print its digest.
  diagnostics memory    Snapshot with the allocator tracer on, then off again.
  diagnostics watchdog  Report the liveness policy and the last recorded stall.
  diagnostics telemetry Report what telemetry declares, and whether any of it
                        leaves this machine. Records nothing and binds nothing.
                        Reads; starts no watchdog and changes nothing.
  diagnostics endpoint  Report the loopback diagnostics surface: whether it is
                        enabled, where it would bind, which routes answer, and
                        every bound it runs inside. Binds nothing.
  config validate     Resolve every source and bind the model. Refuses on the
                      first thing that will not bind. Reads; writes nothing.
  config explain [KEY]  Say which source won, at what priority, and how many
                      weaker layers it overruled. All keys, or one.
  config dump         The effective validated configuration, redacted and in a
                      stable order. Refuses if it would not bind.
  config fingerprint  The semantic digest, and the one that includes origins.
  config evidence     Write .globin/config/config-manifest.json, and record this
                      run as the baseline the next drift report compares against.
  secrets set         Collect a credential at this terminal and store it.
                      Interactive only; refuses a pipe, and refuses --json.
  secrets rotate      Collect a replacement, keeping the previous value
                      resolvable until the new one has been read back.
  secrets verify      Report whether a credential is present. Reads its
                      outcome, never its value.
  secrets list        List what is declared, by name. Never a value.
  secrets delete      Remove a credential from the store.
  secrets health      Report whether the store can be reached at all.
  secrets doctor      Report what each mechanism on this host can do.
                      Reads no stored value.

  --provider NAME     Which mechanism holds the credential. One of
                      credential_manager, dpapi_vault, environment. Omitted,
                      the credential manager is used.
  diagnostics environment  Report this host's capabilities: process and native
                        architecture, emulation, declared toolchain, and the
                        compatibility fingerprint. Publishes no path.

Options:
  --json              Write the machine-readable document to standard output,
                      and nothing else. Human text goes to standard error.
  --environment NAME  Which deployment target a credential belongs to. Never
                      defaulted from --profile: a profile names a document, and
                      what an environment guarantees is Phase 035's question.
  --kind KIND         api_key, api_secret or private_key.
  --name NAME         The credential's logical name.
  --config PATH       An explicit configuration document, above the four this
                      layout computes and below the environment. Unlike those
                      four its absence is fatal. Resolved to an absolute path,
                      so the working directory cannot change what is read.
  --set KEY=VALUE     One setting, for this invocation only. Repeatable, and
                      the strongest source there is. The key must be a declared
                      setting; anything else is refused before its value is read.
  --profile NAME      Which configuration profile to resolve. Outranks
                      GLOBIN_PROFILE, which outranks the declared default.
                      A name that is not a declared profile is refused, never
                      quietly replaced by the default.
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
  24  this host satisfies the runtime contract and lacks a required capability
  25  a required credential is not permitted to do what GLOBIN asks of it
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
        profile: The profile a launcher asked for, or an empty string when it said
            nothing. Empty rather than ``None`` because "not asked for" and "asked
            for nothing" are the same thing to
            :func:`~globin.domain.config_layout.profile_from`, and a second spelling
            of absence would be a second case for every caller to handle.
    """

    command: str
    as_json: bool = False
    profile: str = ""
    environment: str = ""
    kind: str = ""
    name: str = ""
    provider: str = ""
    config: str = ""
    overrides: tuple[str, ...] = ()
    field: str = ""


@dataclass(frozen=True, slots=True)
class Options:
    """The options every configuration-resolving command accepts.

    Args:
        as_json: Whether the machine-readable document was asked for.
        profile: The profile a launcher asked for, or an empty string.
        config: An explicit document, or an empty string.
        overrides: Raw ``key=value`` arguments, in the order they were given and
            not yet validated.

    A record rather than a widening tuple. :func:`_options` returned two values
    until Phase 030 needed four, and a four-tuple is where a caller starts
    unpacking in the wrong order without the type checker noticing.
    """

    as_json: bool = False
    profile: str = ""
    config: str = ""
    overrides: tuple[str, ...] = ()


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
        return _invocation(DOCTOR, _options(words[1:], DOCTOR))
    if head == BOOTSTRAP:
        return _parse_bootstrap(words[1:])
    if head == DIAGNOSTICS:
        return _parse_diagnostics(words[1:])
    if head == CONFIG:
        return _parse_config(words[1:])
    if head == SECRETS:
        return _parse_secrets(words[1:])
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
    options = _options(words, f"{BOOTSTRAP} {subcommand}")
    if options.as_json and subcommand == EVIDENCE:
        msg = (
            f"{JSON_FLAG} means nothing with {EVIDENCE}, which writes a file; "
            f"use `{BOOTSTRAP} {CHECK} {JSON_FLAG}` to read the same document on standard output"
        )
        raise UsageError(msg)
    return _invocation(f"{BOOTSTRAP} {subcommand}", options)


def _options(words: Sequence[str], context: str) -> Options:
    """Accept the four configuration options, and nothing else.

    Args:
        words: The remaining words.
        context: What they followed, for the message.

    Returns:
        What was asked for, as an :class:`Options`.

    Raises:
        UsageError: If anything else appears, if a single-valued option appears
            twice, or if any option that takes a value is given without one.

    **No name and no override is validated here.** Whether a spelling is a
    declared profile is :func:`~globin.domain.config_layout.profile_from`'s
    question, and whether a key is a setting is
    :func:`~globin.adapters.configuration.parse_overrides`'s; answering either in
    the parser would put the register in two places. What this refuses is a
    *shape* problem: a missing value, or a value that is itself another option —
    the case that would otherwise silently swallow ``--json`` and leave the caller
    believing they asked for it.

    **``--set`` is the one option that may repeat**, because one override per
    setting is the point and refusing the second would make the flag able to
    change exactly one thing. A key repeated *across* two ``--set`` arguments is
    still refused, one layer down, where the key is known to be a key.

    **No abbreviation is accepted, here or anywhere.** Every word is compared for
    equality against a spelled constant, so ``--prof`` is an unrecognised argument
    rather than a prefix match. That is not a setting to switch on: the parser has
    no prefix logic to disable, which is the property
    ``argparse``'s ``allow_abbrev`` has to be remembered for.
    """
    remaining = list(words)
    as_json = False
    profile = ""
    config = ""
    overrides: list[str] = []
    while remaining:
        word = remaining.pop(0)
        if word == JSON_FLAG:
            if as_json:
                msg = f"{JSON_FLAG} was given twice"
                raise UsageError(msg)
            as_json = True
            continue
        if word == PROFILE_FLAG:
            profile = _valued(remaining, PROFILE_FLAG, profile)
            continue
        if word == CONFIG_FLAG:
            config = _valued(remaining, CONFIG_FLAG, config)
            continue
        if word == SET_FLAG:
            if not remaining or remaining[0].startswith("-"):
                msg = f"{SET_FLAG} needs a key=value assignment"
                raise UsageError(msg)
            overrides.append(remaining.pop(0))
            continue
        msg = f"unrecognised argument after {context}: {word!r}"
        raise UsageError(msg)
    return Options(as_json=as_json, profile=profile, config=config, overrides=tuple(overrides))


def _valued(remaining: list[str], flag: str, current: str) -> str:
    """Take one option's value off the front of the remaining words.

    Args:
        remaining: The words still to read. Mutated.
        flag: Which option is being read, for the message.
        current: What it already holds, so a repeat can be refused.

    Returns:
        The value.

    Raises:
        UsageError: If the option was already given, or has no value.
    """
    if current:
        msg = f"{flag} was given twice"
        raise UsageError(msg)
    if not remaining or remaining[0].startswith("-"):
        msg = f"{flag} needs a value"
        raise UsageError(msg)
    return remaining.pop(0)


def _explicit_document(invocation: Invocation) -> Path | None:
    """The document ``--config`` named, as an absolute path.

    Args:
        invocation: What was asked for.

    Returns:
        The resolved path, or ``None`` when no document was named.

    **Resolved here rather than left relative**, which is what makes the same
    invocation from two working directories the same invocation. Nothing checks
    that the file exists: whether an absent document is fatal belongs to the
    source that reads it, and answering it here would put the decision in two
    places.
    """
    if not invocation.config:
        return None
    return Path(invocation.config).resolve()


def _invocation(command: str, options: Options, field: str = "") -> Invocation:
    """Build an invocation from a command word and its parsed options.

    Args:
        command: The full command, subcommand included.
        options: What :func:`_options` read.
        field: The one field ``config explain`` was asked about, if any.

    Returns:
        The invocation.

    One place where options become an invocation, so that a command added later
    cannot quietly accept ``--profile`` and drop ``--set``.
    """
    return Invocation(
        command=command,
        as_json=options.as_json,
        profile=options.profile,
        config=options.config,
        overrides=options.overrides,
        field=field,
    )


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


def render_preflight_human(outcome: PreflightOutcome) -> str:
    """The preflight verdict as a person reads it.

    Args:
        outcome: What the run concluded, and the suite it was judged under.

    Returns:
        The check table, then the shelf life, then the verdict.

    **A perishable pass is marked in the table rather than only summarised
    below.** An operator scanning the column is the reader this whole
    classification exists for, and a note at the bottom is one they have to
    remember to correlate.
    """
    checks = outcome.report.outcomes
    if not checks:
        return "no check ran.\n"
    decaying = set(outcome.decaying())
    width = max(len(check.identifier) for check in checks)
    lines = [
        f"  {check.status.value.upper():<10} {check.identifier:<{width}}  "
        f"{'~' if check.identifier in decaying else ' '} {check.summary}"
        for check in checks
    ]
    problems = [check for check in checks if check.status is not CheckStatus.PASS]
    if problems:
        lines.append("")
        lines.extend(f"  {check.identifier}: {check.remediation}" for check in problems)
    lines.append("")
    shelf = outcome.shelf_life_millis()
    if shelf is None:
        lines.append("Nothing in this verdict decays, so it does not expire.")
    else:
        lines.append(
            f"~ marks {len(decaying)} answer(s) that were true when taken; "
            f"take them again every {shelf} ms."
        )
    lines.append(
        f"{PROJECT_NAME} may start." if outcome.may_start else f"{PROJECT_NAME} will not start."
    )
    return "\n".join(lines) + "\n"


def render_preflight_json(outcome: PreflightOutcome) -> str:
    """The preflight verdict as a machine reads it.

    Args:
        outcome: What the run concluded, and the suite it was judged under.

    Returns:
        :meth:`~globin.domain.preflight.PreflightOutcome.as_record`, rendered
        canonically. The domain builds it so that the stream and any later
        artefact describe one run rather than two renderings of it.
    """
    return json.dumps(outcome.as_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


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

    if invocation.command.startswith(SECRETS):
        try:
            return _secrets(invocation, out=out, err=err)
        except UsageError as fault:
            print(f"globin: {fault}", file=err)
            print(USAGE, file=err)
            return int(ExitCode.USAGE)
        except (GlobinError, OSError) as fault:
            print(f"globin: the secret operation failed: {fault}", file=err)
            return int(ExitCode.SECRETS_UNREADY)

    if invocation.command.startswith(CONFIG):
        try:
            return _config(invocation, out=out, err=err, start=start)
        except (ConfigurationError, tomllib.TOMLDecodeError) as fault:
            print(f"globin: the configuration did not validate: {fault}", file=err)
            return int(ExitCode.CONFIGURATION_INVALID)
        except (GlobinError, OSError) as fault:
            print(f"globin: the configuration could not be reported: {fault}", file=err)
            return int(ExitCode.INTERNAL)

    if invocation.command.startswith(DIAGNOSTICS):
        try:
            return _diagnostics(invocation, out=out, err=err, start=start)
        except (ConfigurationError, tomllib.TOMLDecodeError) as fault:
            # Separate from the clause below, and not merely for a nicer sentence.
            # Since Phase 027 a diagnostics command resolves configuration the way a
            # real run does, so it can now fail for a reason that has nothing to do
            # with diagnostics: an undeclared `--profile`, an unreadable document, an
            # unrecognised `GLOBIN_` variable. Reporting those as 22 would tell a
            # launcher "no health verdict could be produced" when the truth is
            # "`bootstrap check` would refuse this configuration too", which is what
            # 14 already means.
            print(f"globin: the configuration did not validate: {fault}", file=err)
            return int(ExitCode.CONFIGURATION_INVALID)
        except (GlobinError, OSError) as fault:
            print(f"globin: the diagnostic could not be produced: {fault}", file=err)
            return int(ExitCode.DIAGNOSTICS_FAILED)

    try:
        return _bootstrap(invocation, out=out, err=err, start=start)
    except tomllib.TOMLDecodeError as fault:
        # `TOMLDecodeError` is a `ValueError`, so it is neither a `GlobinError`
        # nor an `OSError` and the clause below does not see it. Before Phase 030
        # that was unreachable rather than handled: every document the chain read
        # was a committed one, and a malformed committed document fails the suite.
        # `--config` made it reachable, and a traceback is not a user interface.
        #
        # The exception is still not *wrapped*, which is what
        # `docs/CONFIGURATION_POLICY.md` asks for -- a caller below the command
        # line still sees the decoder's own type. What is added is the exit code,
        # and the message keeps the line and column that made leaving it unwrapped
        # worth doing.
        print(f"globin: the configuration did not validate: {fault}", file=err)
        return int(ExitCode.CONFIGURATION_INVALID)
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
    try:
        overrides = parse_overrides(invocation.overrides)
    except ConfigurationError as fault:
        # Handled here rather than beside the broad clause in `main`, and the
        # narrowness is the point. Since Phase 030 the chain is assembled from
        # command-line arguments, so it can be refused *before any check runs*:
        # `--set` naming no setting, or a credential-shaped key. Reporting that
        # as 17 would say "the bootstrap failed in a way it does not account
        # for" about the one class of failure it accounts for most precisely.
        #
        # Catching it around the whole of `_bootstrap` instead would also swallow
        # `Bootstrap.record`'s refusal to write evidence when there is no project
        # root -- a different fault, which has answered 17 since Phase 021 and
        # whose test noticed immediately when this clause was first written wide.
        print(f"globin: the configuration did not validate: {fault}", file=err)
        return int(ExitCode.CONFIGURATION_INVALID)
    bootstrap = build_bootstrap(
        Path.cwd() if start is None else start,
        profile=resolve_run_profile(invocation.profile or None),
        explicit=_explicit_document(invocation),
        overrides=overrides,
    )

    if invocation.command.endswith(PREFLIGHT):
        verdict = bootstrap.preflight()
        if invocation.as_json:
            print(render_preflight_json(verdict), file=out)
            print(render_preflight_human(verdict), end="", file=err)
        else:
            print(render_preflight_human(verdict), end="", file=out)
        return int(verdict.exit_code)

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
    options = _options(words, f"{DIAGNOSTICS} {subcommand}")
    if options.as_json and subcommand == BUNDLE:
        msg = (
            f"{JSON_FLAG} means nothing with {BUNDLE}, which writes an archive; "
            f"use `{DIAGNOSTICS} {SNAPSHOT} {JSON_FLAG}` to read the same document"
        )
        raise UsageError(msg)
    return _invocation(f"{DIAGNOSTICS} {subcommand}", options)


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


def _diagnostics(
    invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None = None
) -> int:
    """Take a snapshot, or build a bundle from one, or report a subsystem.

    Args:
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the search for the project root, which decides which
            configuration documents are read. Defaults to the working directory.

    Returns:
        The exit code.

    **This command starts no diagnostics subsystem and takes no lock.** It reads
    the runtime tree, probes the lock by acquiring and releasing it, and exits.
    A read-only command that took the production lock would refuse to run beside
    a running GLOBIN, which is the trap ADR-0057 already declined for ``doctor``.

    **Since Phase 027 it resolves configuration the way a real run does** — through
    the documents the resolved profile names, then the environment — rather than
    reporting the declared defaults. A diagnostic that described a configuration
    nobody is running would be worse than no diagnostic, because it would look like
    one.
    """
    state = build_runtime_state()
    profile = resolve_run_profile(invocation.profile or None)
    sources = build_config_sources(
        find_project_root(Path.cwd() if start is None else start),
        profile,
        explicit=_explicit_document(invocation),
        overrides=parse_overrides(invocation.overrides),
    )
    settings = resolve_settings(sources)
    config = as_config(settings)
    if invocation.command.endswith(WATCHDOG):
        return _watchdog(state, config, invocation, out=out, err=err)
    if invocation.command.endswith(TELEMETRY):
        return _telemetry(config, invocation, out=out, err=err)
    if invocation.command.endswith(ENDPOINT):
        return _endpoint(config, invocation, out=out, err=err)
    if invocation.command.endswith(ENVIRONMENT):
        return _environment(invocation, out=out, err=err, start=start)
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
            profile=profile,
            config_fingerprint=config_fingerprint(settings),
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

    **Exit code 26 stays free.** If a later phase wants a *gate* that fails when
    export is unhealthy, that is a different command with different semantics, and
    that is when a new code is earned.
    """
    otel = opentelemetry_bridge()
    prometheus = prometheus_publisher()
    document: dict[str, object] = {
        "enabled": config.telemetry.enabled,
        "export_enabled": config.telemetry.export_enabled,
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
        f"scrape      see `{DIAGNOSTICS} {ENDPOINT}`",
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


def _endpoint(
    config: GlobinConfig,
    invocation: Invocation,
    *,
    out: TextIO,
    err: TextIO,
) -> int:
    """Report the diagnostics surface: where it would bind, and inside what bounds.

    Args:
        config: Where the settings come from.
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.

    Returns:
        :attr:`~globin.domain.bootstrap.ExitCode.OK` when the configuration is
        usable, and
        :attr:`~globin.domain.bootstrap.ExitCode.CONFIGURATION_INVALID` when it is
        not.

    **It binds nothing and starts nothing.** Building the policy is the whole of the
    work: that is the object a server would be constructed from, so validating it
    answers "would this start" without anything starting. A command that bound the
    port to find out could fail for the one reason that means everything is working.

    **The exit code is 14 rather than a new one.** An unusable bind address or an
    out-of-range bound is a configuration that did not validate, which is exactly
    what 14 already means and what `bootstrap check` would report for the same
    document. Code 26 stays free.
    """
    surface = config.diagnostics_http
    document: dict[str, object] = {
        "schema": ENDPOINT_SCHEMA,
        "schema_version": ENDPOINT_SCHEMA_VERSION,
        "enabled": surface.enabled,
        "bind_host": surface.bind_host,
        "port": surface.port,
        "request_timeout_seconds": surface.request_timeout_seconds,
        "shutdown_timeout_seconds": surface.shutdown_timeout_seconds,
        "max_concurrent_requests": surface.max_concurrent_requests,
        "max_response_bytes": surface.max_response_bytes,
        "health_enabled": surface.health_enabled,
        "metrics_enabled": surface.metrics_enabled,
        "diagnostics_snapshot_enabled": surface.diagnostics_snapshot_enabled,
        "expositions": [
            {"format": exposition.value, "content_type": content_type_for(exposition)}
            for exposition in (ExpositionFormat.PROMETHEUS_TEXT, ExpositionFormat.OPENMETRICS_TEXT)
        ],
        "routes": [
            {"path": path, "route": route.value, "answers": _route_answers(surface, route)}
            for path, route in route_paths()
        ],
    }
    problems = address_problems(surface.bind_host) + policy_problems(
        port=surface.port,
        request_timeout_seconds=surface.request_timeout_seconds,
        shutdown_timeout_seconds=surface.shutdown_timeout_seconds,
        max_concurrent_requests=surface.max_concurrent_requests,
        max_response_bytes=surface.max_response_bytes,
    )
    document["problems"] = list(problems)
    document["usable"] = not problems
    human = _endpoint_text(document)
    if invocation.as_json:
        print(json.dumps(document, sort_keys=True, separators=(",", ":")), file=out)
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    return int(ExitCode.OK if not problems else ExitCode.CONFIGURATION_INVALID)


def _environment(
    invocation: Invocation,
    *,
    out: TextIO,
    err: TextIO,
    start: Path | None,
) -> int:
    """Report what this host is capable of, and whether that is enough.

    Args:
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the project-root search.

    Returns:
        :attr:`~globin.domain.bootstrap.ExitCode.OK` when the host is ready or
        merely degraded,
        :attr:`~globin.domain.bootstrap.ExitCode.ENVIRONMENT_INCOMPATIBLE` when a
        required capability is absent, and
        :attr:`~globin.domain.bootstrap.ExitCode.UNMEASURED` when the contract
        could not be read at all.

    **A degraded host exits ``0``.** The three verdicts do not map onto three
    codes here, for the reason ``capability_outcome`` gives: degradation is a
    host that works and should be improved, and a command that failed on it
    would fail on CI's runner every run. ``UNMEASURED`` is separate because not
    having read the contract is not a verdict about a host.

    **It publishes no path and no toolchain location.** The snapshot type has no
    field for either, so this is a property of what it is handed rather than of
    what it chooses to print.
    """
    root = find_project_root((start or Path.cwd()).resolve())
    try:
        baseline = TomlRuntimeBaselineSource(
            path=(root or (start or Path.cwd())) / RUNTIME_CONTRACT_PATH,
        ).baseline()
    except ConfigurationError as problem:
        print(f"environment  unmeasured ({problem})", file=err if invocation.as_json else out)
        return int(ExitCode.UNMEASURED)

    snapshot = SystemEnvironmentProbe(
        api=windows_system_api(),
        toolchain=PathToolchainProbe(),
        declared=DECLARED_TOOLCHAIN,
    ).snapshot(baseline)
    human = _environment_text(snapshot)
    if invocation.as_json:
        print(
            json.dumps(snapshot.as_record(), sort_keys=True, separators=(",", ":")),
            file=out,
        )
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    if snapshot.compatibility() is EnvironmentCompatibility.BLOCKED:
        return int(ExitCode.ENVIRONMENT_INCOMPATIBLE)
    return int(ExitCode.OK)


def _environment_text(snapshot: EnvironmentCapabilitySnapshot) -> str:
    """The human rendering of the environment report.

    Args:
        snapshot: What the capability probes reported.

    Returns:
        The text, ending in a newline.

    Takes the **snapshot** rather than the rendered mapping, which the other
    ``_*_text`` functions in this module take. That is a deliberate departure and
    a stronger guarantee rather than a weaker one: both renderings still derive
    from one value, and this one reads typed fields instead of indexing a
    ``dict[str, object]`` — which would need either a cast or an ``assert``, and
    ``assert`` is forbidden under ``src/`` because ``python -O`` strips it.
    """
    lines = [
        f"environment  {snapshot.compatibility().value}  "
        f"({compatibility_fingerprint(snapshot.projection())})",
        f"  machine    process {snapshot.architecture.process.value}  "
        f"native {snapshot.architecture.native.value}  "
        f"{snapshot.architecture.emulation.value}",
    ]
    lines.extend(
        f"  {check.status.value:<13} {check.identifier}"
        + ("" if check.reason is CapabilityReason.SATISFIED else f"  [{check.reason.value}]")
        for check in snapshot.checks
    )
    return "\n".join(lines) + "\n"


def _route_answers(surface: DiagnosticsHttpConfig, route: DiagnosticsRoute) -> bool:
    """Whether one route would answer under this configuration.

    Args:
        surface: The resolved settings.
        route: Which route.

    Returns:
        Whether a request to it would be served.

    The same reduction :class:`~globin.application.diagnostics_http.DiagnosticsService`
    performs, and it is deliberately *not* shared with it: this reports what a reader
    should expect, and that one decides what happens. Two callers of one predicate
    would make the report a description of itself.
    """
    if not surface.enabled:
        return False
    if route is DiagnosticsRoute.METRICS:
        return surface.metrics_enabled
    if route is DiagnosticsRoute.SNAPSHOT:
        return surface.diagnostics_snapshot_enabled
    return surface.health_enabled


def _endpoint_text(document: dict[str, object]) -> str:
    """The human rendering of the endpoint report.

    Args:
        document: What :func:`_endpoint` assembled.

    Returns:
        The text, ending in a newline.

    Built from the same mapping the JSON rendering uses, so the two cannot say
    different things — the property every rendering in this module has.
    """
    lines = [
        f"surface     {'on' if document['enabled'] else 'off'} "
        f"({document['bind_host']}:{document['port']})",
        f"  timeouts   request {document['request_timeout_seconds']}s  "
        f"shutdown {document['shutdown_timeout_seconds']}s",
        f"  bounds     {document['max_concurrent_requests']} concurrent  "
        f"{document['max_response_bytes']} bytes",
    ]
    routes = document["routes"]
    if isinstance(routes, list):
        lines.append("routes")
        for entry in routes:
            if isinstance(entry, dict):
                marker = "answers" if entry["answers"] else "off"
                lines.append(f"  {entry['path']!s:<24} {marker}")
    expositions = document["expositions"]
    if isinstance(expositions, list):
        lines.append("expositions")
        for entry in expositions:
            if isinstance(entry, dict):
                lines.append(f"  {entry['content_type']}")
    problems = document["problems"]
    if isinstance(problems, list) and problems:
        lines.append("problems")
        lines.extend(f"  {problem}" for problem in problems)
    else:
        lines.append("configuration is usable")
    return "\n".join(lines) + "\n"


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


def _parse_secrets(rest: Sequence[str]) -> Invocation:
    """Read what follows ``secrets``.

    Args:
        rest: The remaining words.

    Returns:
        What was asked for.

    Raises:
        UsageError: If the subcommand is unknown, if it is missing, or if an
            option is malformed.

    There is no default subcommand, deliberately. ``bootstrap`` defaults to
    ``check`` and ``diagnostics`` to ``snapshot`` because both are read-only; the
    verbs here include two that write and one that deletes, and a bare
    ``globin secrets`` that guessed which one was meant would be guessing about a
    credential.
    """
    words = list(rest)
    if not words:
        listed = ", ".join(SECRETS_SUBCOMMANDS)
        msg = f"{SECRETS} needs a subcommand: {listed}"
        raise UsageError(msg)
    word = words[0]
    if word not in SECRETS_SUBCOMMANDS:
        listed = ", ".join(SECRETS_SUBCOMMANDS)
        msg = f"unrecognised {SECRETS} subcommand: {word!r}. Expected one of {listed}"
        raise UsageError(msg)
    options = _secret_options(words[1:], f"{SECRETS} {word}")
    if options.as_json and word in SECRETS_WRITING:
        msg = (
            f"{JSON_FLAG} means nothing for {SECRETS} {word}, whose whole action is "
            f"an interactive prompt"
        )
        raise UsageError(msg)
    return Invocation(
        command=f"{SECRETS} {word}",
        as_json=options.as_json,
        profile=options.profile,
        environment=options.environment,
        kind=options.kind,
        name=options.name,
        provider=options.provider,
    )


@dataclass(frozen=True, slots=True)
class _SecretOptions:
    """What a secrets subcommand was given."""

    as_json: bool = False
    profile: str = ""
    environment: str = ""
    kind: str = ""
    name: str = ""
    provider: str = ""


def _secret_options(words: Sequence[str], context: str) -> _SecretOptions:
    """Accept the six options a secrets subcommand may take, and nothing else.

    Args:
        words: The remaining words.
        context: What they followed, for the message.

    Returns:
        What was asked for.

    Raises:
        UsageError: If anything else appears, if an option repeats, or if one
            that needs a value is given without one.

    A sibling of :func:`_options` rather than a replacement, because widening
    that function would let ``--environment`` be passed to ``doctor``, where it
    means nothing.

    **No option carries material, and that is enforced here rather than
    documented.** ``SECRET_STORE_CONTRACT.md`` section 5 forbids "``--secret=``
    or any other option that would place material on a command line". Every
    unrecognised word is refused, so a caller reaching for one gets a usage
    error rather than a credential in their shell history; a contract test names
    the specific spellings.
    """
    remaining = list(words)
    as_json = False
    values: dict[str, str] = {}
    valued = {
        PROFILE_FLAG: "profile",
        ENVIRONMENT_FLAG: "environment",
        KIND_FLAG: "kind",
        NAME_FLAG: "name",
        PROVIDER_FLAG: "provider",
    }
    while remaining:
        word = remaining.pop(0)
        if word == JSON_FLAG:
            if as_json:
                msg = f"{JSON_FLAG} was given twice"
                raise UsageError(msg)
            as_json = True
            continue
        field = valued.get(word)
        if field is None:
            msg = f"unrecognised argument after {context}: {word!r}"
            raise UsageError(msg)
        if values.get(field):
            msg = f"{word} was given twice"
            raise UsageError(msg)
        if not remaining or remaining[0].startswith("-"):
            msg = f"{word} needs a value"
            raise UsageError(msg)
        values[field] = remaining.pop(0)
    return _SecretOptions(
        as_json=as_json,
        profile=values.get("profile", ""),
        environment=values.get("environment", ""),
        kind=values.get("kind", ""),
        name=values.get("name", ""),
        provider=values.get("provider", ""),
    )


def _reference_from(invocation: Invocation) -> SecretReference:
    """Build the reference a secrets subcommand names.

    Args:
        invocation: What was asked for.

    Returns:
        The reference.

    Raises:
        UsageError: If any of the three parts is missing or malformed.

    **The environment is never defaulted from the profile.** Deriving one from
    the other would answer Phase 035's question -- what an environment *is* --
    six phases early, and ``CONFIGURATION_LAYOUT.md`` is explicit that a profile
    names a *document* rather than a deployment target.
    """
    if not invocation.environment:
        msg = f"{ENVIRONMENT_FLAG} is required and names a deployment target"
        raise UsageError(msg)
    if not invocation.kind:
        listed = ", ".join(kind.value for kind in SecretKind)
        msg = f"{KIND_FLAG} is required and must be one of {listed}"
        raise UsageError(msg)
    if not invocation.name:
        msg = f"{NAME_FLAG} is required and names the credential"
        raise UsageError(msg)
    try:
        kind = SecretKind(invocation.kind)
    except ValueError:
        listed = ", ".join(item.value for item in SecretKind)
        msg = f"unrecognised kind {invocation.kind!r}. Expected one of {listed}"
        raise UsageError(msg) from None
    try:
        return SecretReference(
            environment=EnvironmentId(invocation.environment),
            kind=kind,
            name=invocation.name,
        )
    except ValidationError as fault:
        msg = f"that is not a usable reference: {fault}"
        raise UsageError(msg) from None


def _provider_from(invocation: Invocation) -> SecretProviderKind | None:
    """Which mechanism was named, if any.

    Args:
        invocation: What was asked for.

    Returns:
        The mechanism, or ``None`` where none was named — which is a different
        situation from naming one and being wrong, and is why an unrecognised
        name is refused rather than defaulted.

    Raises:
        UsageError: If a mechanism was named and is not one GLOBIN has.
    """
    if not invocation.provider:
        return None
    try:
        return SecretProviderKind(invocation.provider)
    except ValueError:
        listed = ", ".join(kind.value for kind in SecretProviderKind)
        msg = f"unrecognised provider {invocation.provider!r}. Expected one of {listed}"
        raise UsageError(msg) from None


def _locators_for(
    invocation: Invocation, provider: SecretProviderKind | None
) -> tuple[SecretLocator, ...]:
    """The routing this invocation implies.

    Args:
        invocation: What was asked for.
        provider: Which mechanism was named, if any.

    Returns:
        One locator when a mechanism and a complete reference were both given,
        and nothing otherwise — in which case the reference routes to the
        composition root's default.

    Raises:
        UsageError: If the environment hand-off was named without a variable to
            read, which :class:`~globin.domain.secrets.SecretLocator` refuses at
            construction. Surfaced here as usage rather than as a traceback,
            because it is something the operator typed.

    The variable name is derived from the reference rather than taken as a
    seventh option, so that no spelling of it can reach the command line beside a
    value. `GLOBIN_`-prefixed names are refused by
    :func:`~globin.domain.secrets.variable_problems` for the reason recorded
    there: one would make every later start-up refuse.
    """
    if provider is None or not (invocation.environment and invocation.kind and invocation.name):
        return ()
    reference = _reference_from(invocation)
    variable = ""
    if provider is SecretProviderKind.ENVIRONMENT:
        variable = f"{reference.environment.text}_{reference.name}".upper()
    try:
        return (SecretLocator(provider=provider, reference=reference, variable=variable),)
    except ValidationError as fault:
        msg = f"that provider cannot address that reference: {fault}"
        raise UsageError(msg) from fault


def _secrets(
    invocation: Invocation,
    *,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run one ``secrets`` subcommand.

    Args:
        invocation: What was asked for.
        out: Where a document goes.
        err: Where human text goes.

    Returns:
        The exit code.

    No project root is searched for. Every one of these verbs works against the
    machine's credential store and the user-local state area, neither of which
    is inside a checkout -- so unlike ``doctor`` this runs the same way from any
    directory.
    """
    state = build_runtime_state()
    word = invocation.command.split(" ", 1)[1]
    provider = _provider_from(invocation)
    locators = _locators_for(invocation, provider)
    store = build_secret_store(state, locators=locators)
    register = build_grant_register(state)

    if word in SECRETS_WRITING and provider is not None and not provider_writable(provider):
        msg = (
            f"{provider.value} is a hand-off rather than a store and never accepts a "
            f"write; nothing was collected"
        )
        raise UsageError(msg)

    if word == HEALTH:
        return _secret_health(store, out=out, err=err, as_json=invocation.as_json)
    if word == SECRETS_DOCTOR:
        return _secret_doctor(state, out=out, as_json=invocation.as_json)
    if word == LIST:
        return _secret_list(register, out=out, as_json=invocation.as_json)

    reference = _reference_from(invocation)
    if word == VERIFY:
        return _secret_verify(
            store, register, reference, out=out, err=err, as_json=invocation.as_json
        )
    if word == DELETE:
        return _secret_delete(store, reference, out=out, err=err, as_json=invocation.as_json)
    entry = build_secret_entry(err)
    return _secret_write(entry, store, register, reference, word=word, out=out, err=err)


def _secret_health(store: SecretStore, *, out: TextIO, err: TextIO, as_json: bool) -> int:
    """Report whether the backing store can be reached at all."""
    fault = store.health()
    document = {"available": fault is None, "fault": None if fault is None else fault.value}
    if as_json:
        print(json.dumps(document, sort_keys=True), file=out)
    elif fault is None:
        print("the secret store is available", file=out)
    else:
        print(f"the secret store is unavailable: {fault.value}", file=out)
        print(REMEDIATION[fault], file=err)
    return int(ExitCode.OK if fault is None else ExitCode.SECRETS_UNREADY)


def _secret_doctor(state: RuntimeState, *, out: TextIO, as_json: bool) -> int:
    """Report what each secret mechanism on this host can do.

    Args:
        state: The runtime tree, for the vault's directory.
        out: Where the report goes.
        as_json: Whether to render a document.

    Returns:
        :attr:`~globin.domain.bootstrap.ExitCode.OK` always.

    **Reporting is not gating**, the same reasoning ``diagnostics telemetry``
    gives: a host with one mechanism unavailable is a host an operator may want
    to know about, and the gate for whether GLOBIN may start is
    ``bootstrap check``. Returning a refusal here would make an informational
    command fail on a machine that works.

    **It reads nothing an operator stored.** Each mechanism is asked its own
    ``health``, which is a question about reachability rather than about
    contents -- ``SECRET_STORE_CONTRACT.md`` §5 permits a health check precisely
    because it reports nothing it found.
    """
    providers = build_secret_providers(state)
    rows = []
    for kind in sorted(providers, key=lambda entry: entry.value):
        fault = providers[kind].health()
        rows.append(
            {
                "provider": kind.value,
                "available": fault is None,
                "fault": None if fault is None else fault.value,
                "writable": provider_writable(kind),
            }
        )
    if as_json:
        print(json.dumps({"providers": rows}, sort_keys=True), file=out)
        return int(ExitCode.OK)
    width = max(len(str(row["provider"])) for row in rows)
    for row in rows:
        state_word = "available" if row["available"] else f"unavailable ({row['fault']})"
        writable = "read-write" if row["writable"] else "read-only"
        print(f"  {row['provider']:<{width}}  {state_word}  {writable}", file=out)
    return int(ExitCode.OK)


def _secret_list(register: GrantRegister, *, out: TextIO, as_json: bool) -> int:
    """List what is declared, by name only.

    Never a value, and never a probe of the store: what is listed is what an
    operator declared, which is ordinary data.
    """
    declarations = register.declarations()
    document = {"declarations": [item.as_record() for item in declarations]}
    if as_json:
        print(json.dumps(document, sort_keys=True), file=out)
        return int(ExitCode.OK)
    if not declarations:
        print("no credential is declared", file=out)
        return int(ExitCode.OK)
    for declaration in declarations:
        grants = ", ".join(declaration.declared.names()) or "nothing"
        print(
            f"{declaration.reference.environment.text}/"
            f"{declaration.reference.kind.value}/"
            f"{declaration.reference.name}: {grants}",
            file=out,
        )
    return int(ExitCode.OK)


def _secret_verify(
    store: SecretStore,
    register: GrantRegister,
    reference: SecretReference,
    *,
    out: TextIO,
    err: TextIO,
    as_json: bool,
) -> int:
    """Report whether a credential exists, without reading its value.

    The resolution's *outcome* is asked for and the value is discarded
    immediately -- which is what ``SECRET_STORE_CONTRACT.md`` section 5 means by
    "verify presence (returning a boolean)".
    """
    resolution = resolve(store, reference)
    declaration = declaration_for(reference, register.declarations())
    grants = [] if declaration is None else list(declaration.declared.names())
    document = {
        "environment": reference.environment.text,
        "kind": reference.kind.value,
        "name": reference.name,
        "present": resolution.resolved,
        "fault": None if resolution.fault is None else resolution.fault.value,
        "declared": grants,
    }
    if as_json:
        print(json.dumps(document, sort_keys=True), file=out)
    elif resolution.resolved:
        print(f"{reference.name} is present; declared grants: {grants or 'none'}", file=out)
    else:
        fault = resolution.fault
        print(f"{reference.name} is not usable: {fault.value if fault else 'absent'}", file=out)
        if fault is not None:
            print(REMEDIATION[fault], file=err)
    return int(ExitCode.OK if resolution.resolved else ExitCode.SECRETS_UNREADY)


def _secret_delete(
    store: SecretStore,
    reference: SecretReference,
    *,
    out: TextIO,
    err: TextIO,
    as_json: bool,
) -> int:
    """Remove a credential from the store."""
    fault = store.delete(reference)
    document = {
        "environment": reference.environment.text,
        "kind": reference.kind.value,
        "name": reference.name,
        "deleted": fault is None,
        "fault": None if fault is None else fault.value,
    }
    if as_json:
        print(json.dumps(document, sort_keys=True), file=out)
    elif fault is None:
        print(f"{reference.name} was removed", file=out)
    else:
        print(f"{reference.name} was not removed: {fault.value}", file=out)
        print(REMEDIATION[fault], file=err)
    return int(ExitCode.OK if fault is None else ExitCode.SECRETS_UNREADY)


def _secret_write(
    entry: SecretEntry,
    store: SecretStore,
    register: GrantRegister,
    reference: SecretReference,
    *,
    word: str,
    out: TextIO,
    err: TextIO,
) -> int:
    """Collect material interactively and either set or rotate it.

    Human output only: ``--json`` is refused for both verbs by the parser,
    because a command whose primary act is a prompt has no document for standard
    output and offering one invites scripting it.
    """
    prompt = f"{reference.environment.text}/{reference.name} ({reference.kind.value}): "
    if word == SET:
        outcome = set_from_entry(entry, store, reference, prompt=prompt)
    else:
        outcome = rotate_from_entry(entry, store, reference, prompt=prompt)

    if not outcome.stored:
        if outcome.entry_fault is not None:
            print(f"nothing was stored: {outcome.entry_fault.value}", file=out)
            print(ENTRY_REMEDIATION[outcome.entry_fault], file=err)
            for problem in outcome.problems:
                print(f"  - {problem.value}", file=err)
        elif outcome.store_fault is not None:
            print(f"nothing was stored: {outcome.store_fault.value}", file=out)
            print(REMEDIATION[outcome.store_fault], file=err)
        return int(ExitCode.SECRETS_UNREADY)

    print(f"{reference.name} was stored", file=out)
    if register.declare(GrantDeclaration(reference=reference, declared=GrantSet())):
        print(
            "no grants are declared for it yet, so nothing may use it. "
            "Declaring what a key is permitted to do is Phase 039's flow.",
            file=err,
        )
    return int(ExitCode.OK)


def _parse_config(rest: Sequence[str]) -> Invocation:
    """Read what follows ``config``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, if a field is given to a
            verb that takes none, or if ``--json`` is asked of ``evidence``,
            whose output is a file rather than a stream.

    ``explain`` is the one verb taking a positional, and it is optional: with a
    key it explains that key, without one it explains all of them. A second
    positional is refused rather than ignored, because a caller who typed two key
    names is asking a question this command cannot answer and should be told so.
    """
    words = list(rest)
    subcommand = VALIDATE
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in CONFIG_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    field = ""
    if words and not words[0].startswith("-"):
        if subcommand != EXPLAIN:
            msg = f"{CONFIG} {subcommand} takes no field name, but {words[0]!r} was given"
            raise UsageError(msg)
        field = words.pop(0)
        if words and not words[0].startswith("-"):
            msg = f"{CONFIG} {EXPLAIN} explains one field at a time, but {words[0]!r} followed"
            raise UsageError(msg)
    options = _options(words, f"{CONFIG} {subcommand}")
    if options.as_json and subcommand == EVIDENCE:
        msg = (
            f"{JSON_FLAG} means nothing with {EVIDENCE}, which writes a file; "
            f"use `{CONFIG} {EXPLAIN} {JSON_FLAG}` to read the same account on standard output"
        )
        raise UsageError(msg)
    return _invocation(f"{CONFIG} {subcommand}", options, field=field)


@dataclass(frozen=True, slots=True)
class _Resolution:
    """One resolution of configuration, with everything a report needs.

    Args:
        profile: The profile that was resolved.
        provenance: Who set what, and what was overruled.
        semantic: The value-only fingerprint.
        problem: Why the model did not bind, or an empty string when it did.
        config: The bound model, or ``None`` when it did not bind.

    Assembled once per invocation so that every verb describes the same
    resolution. Two verbs each resolving for themselves would be two resolutions,
    which is the defect ``ConfigurationResolution.resolved`` was written to
    prevent one layer down.
    """

    profile: str
    provenance: ConfigProvenance
    semantic: str
    problem: str
    config: GlobinConfig | None


def _resolve_for_report(invocation: Invocation, start: Path | None) -> _Resolution:
    """Resolve configuration and account for it, without judging.

    Args:
        invocation: What was asked for.
        start: Where to begin the search for the project root.

    Returns:
        A :class:`_Resolution`.

    Raises:
        ConfigurationError: If a source could not produce a layer at all — an
            unreadable document, a document named by ``--config`` that is not
            there, an unrecognised ``GLOBIN_`` variable, a ``--set`` naming no
            setting. Those refuse the whole report, because a report about a
            resolution that did not happen would be worse than none.

    A binding failure is **caught and carried** rather than raised, because three
    of the five verbs still have something true to say about a configuration that
    will not bind — which source set the offending value being the most useful of
    them.
    """
    profile = resolve_run_profile(invocation.profile or None)
    sources = build_config_sources(
        find_project_root(Path.cwd() if start is None else start),
        profile,
        explicit=_explicit_document(invocation),
        overrides=parse_overrides(invocation.overrides),
    )
    layers = (default_layer(), *(source.layer() for source in sources))
    resolved = resolve_layers(layers)
    bound: GlobinConfig | None = None
    problem = ""
    try:
        bound = as_config(resolved)
    except (ConfigurationError, InternalError) as fault:
        problem = str(fault)
    return _Resolution(
        profile=profile,
        provenance=provenance_of(layers),
        semantic=config_fingerprint(resolved),
        problem=problem,
        config=bound,
    )


def _config(invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None) -> int:
    """Report on configuration, five ways.

    Args:
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the search for the project root.

    Returns:
        The exit code. :attr:`~globin.domain.bootstrap.ExitCode.CONFIGURATION_INVALID`
        when the model did not bind and the verb needed it to.

    Raises:
        ConfigurationError: As :func:`_resolve_for_report`, and from
            :meth:`~globin.domain.config_evidence.ConfigProvenance.field` when a
            named key resolved to nothing.
        OSError: If evidence could not be written.

    **Three of the five verbs work on a configuration that will not bind, and two
    refuse.** ``explain`` and ``fingerprint`` are diagnostics — an operator whose
    configuration is broken is exactly the one who needs to know which document
    set the offending value — while ``dump`` describes the *validated* model and
    would otherwise have to invent one. ``validate`` refuses because refusing is
    the whole verb.
    """
    resolution = _resolve_for_report(invocation, start)
    if invocation.command.endswith(EVIDENCE):
        return _config_evidence(resolution, out=out, start=start)

    needs_model = invocation.command.endswith((DUMP, VALIDATE))
    if needs_model and resolution.problem:
        print(f"globin: the configuration did not validate: {resolution.problem}", file=err)
        return int(ExitCode.CONFIGURATION_INVALID)

    document, human = _config_report(invocation, resolution)
    if invocation.as_json:
        print(
            json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            file=out,
        )
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    return int(ExitCode.OK)


def _config_report(
    invocation: Invocation, resolution: _Resolution
) -> tuple[dict[str, object], str]:
    """Build one verb's document and its human rendering.

    Args:
        invocation: What was asked for.
        resolution: The one resolution every verb describes.

    Returns:
        The machine-readable document and the human text, built from the same
        values so that the two cannot disagree.

    Raises:
        ConfigurationError: If ``explain`` named a key that resolved to nothing.
    """
    if invocation.command.endswith(FINGERPRINT):
        return _config_fingerprint(resolution)
    if invocation.command.endswith(DUMP):
        return _config_dump(resolution)
    if invocation.command.endswith(EXPLAIN):
        return _config_explain(invocation, resolution)
    return _config_validate(resolution)


def _config_fingerprint(resolution: _Resolution) -> tuple[dict[str, object], str]:
    """The two digests, and what each one ignores.

    Args:
        resolution: The resolution to digest.

    Returns:
        The document and the human text.
    """
    evidence = evidence_fingerprint(resolution.provenance)
    document: dict[str, object] = {
        "profile": resolution.profile,
        "semantic_fingerprint": resolution.semantic,
        "evidence_fingerprint": evidence,
    }
    human = (
        f"  semantic  {resolution.semantic}\n"
        f"  evidence  {evidence}\n"
        f"\nThe semantic digest ignores where a value came from; "
        f"the evidence digest does not.\n"
    )
    return document, human


def _config_dump(resolution: _Resolution) -> tuple[dict[str, object], str]:
    """The effective validated configuration, redacted and in a stable order.

    Args:
        resolution: The resolution, whose model the caller has established binds.

    Returns:
        The document and the human text.

    Sorted by key in both renderings, so two runs on one configuration produce
    the same bytes and a difference between them is a real difference.
    """
    safe = redact(effective_values(_bound(resolution)))
    document: dict[str, object] = {
        "profile": resolution.profile,
        "settings": {key: repr(value) for key, value in sorted(safe.items())},
    }
    width = max(len(key) for key in safe)
    lines = [f"  {key:<{width}}  {safe[key]!r}" for key in sorted(safe)]
    return document, "\n".join(lines) + "\n"


def _config_validate(resolution: _Resolution) -> tuple[dict[str, object], str]:
    """The verdict, once binding has already been established.

    Args:
        resolution: The resolution.

    Returns:
        The document and the human text.
    """
    document: dict[str, object] = {
        "profile": resolution.profile,
        "bound": True,
        "settings": len(resolution.provenance.keys()),
        "sources": len(resolution.provenance.layers),
    }
    human = (
        f"  profile   {resolution.profile}\n"
        f"  sources   {len(resolution.provenance.layers)} consulted\n"
        f"  settings  {len(resolution.provenance.keys())} resolved\n"
        f"\nThe configuration is valid.\n"
    )
    return document, human


def _config_explain(
    invocation: Invocation, resolution: _Resolution
) -> tuple[dict[str, object], str]:
    """Account for one field, or for all of them.

    Args:
        invocation: What was asked for.
        resolution: The one resolution every verb describes.

    Returns:
        The document and the human text.

    Raises:
        ConfigurationError: If a named key resolved to nothing.

    Ordering is by key throughout, so two runs of this command on one
    configuration produce the same bytes.
    """
    chosen = (
        (resolution.provenance.field(invocation.field),)
        if invocation.field
        else resolution.provenance.fields
    )
    document: dict[str, object] = {
        "profile": resolution.profile,
        "layers": [layer.as_record() for layer in resolution.provenance.layers],
        "fields": [field.as_record() for field in chosen],
    }
    width = max(len(field.key) for field in chosen)
    lines = [
        f"  {field.key:<{width}}  {field.display}"
        f"  <- {field.origin} (priority {field.priority}, {field.overridden} overruled)"
        f"{'' if field.known else '  [not a setting]'}"
        for field in chosen
    ]
    return document, "\n".join(lines) + "\n"


def _bound(resolution: _Resolution) -> GlobinConfig:
    """The validated model, which the caller has already established exists.

    Args:
        resolution: The resolution.

    Returns:
        The bound model.

    Raises:
        InternalError: If it is absent. ``dump`` and ``validate`` return before
            reaching here when binding failed, so this is unreachable from the
            command line and is a GLOBIN defect if it fires.
    """
    if resolution.config is None:
        msg = "a validated configuration was asked for after binding had already failed"
        raise InternalError(msg)
    return resolution.config


def _config_evidence(resolution: _Resolution, *, out: TextIO, start: Path | None) -> int:
    """Write the manifest and record this run as the drift baseline.

    Args:
        resolution: The one resolution the manifest describes.
        out: Where the confirmation goes. There is no ``--json`` for this verb,
            so there is no document competing for standard output.
        start: Where to begin the search for the project root.

    Returns:
        The exit code.

    Raises:
        ConfigurationError: If there is no project root, and therefore nowhere
            inside the project that evidence may go.
        OSError: If the manifest could not be written.

    **The comparison happens before the baseline is replaced**, which is the only
    order that works: recording first would compare this run against itself and
    report that nothing ever changes.

    **A configuration that will not bind still gets a manifest, and still exits
    non-zero.** A gate that failed silently and left no artefact is
    indistinguishable from one that never ran, which is the reasoning
    ``bootstrap evidence`` gives for the same choice.
    """
    root = find_project_root(Path.cwd() if start is None else start)
    if root is None:
        msg = "there is no project root, so there is nowhere to write evidence"
        raise ConfigurationError(msg)

    state = build_runtime_state()
    state.tree.prepare(state.layout)
    snapshot = snapshot_of(
        resolution.provenance, profile=resolution.profile, semantic=resolution.semantic
    )
    recorded = read_snapshot(state.store)
    drift = compare(recorded, snapshot)

    document = build_config_manifest(
        profile=resolution.profile,
        provenance=resolution.provenance.as_record(),
        fingerprints={
            "semantic": resolution.semantic,
            "evidence": snapshot.evidence,
            "schema_version": snapshot.schema_version,
        },
        validation={"bound": not resolution.problem, "problem": resolution.problem},
        drift=drift.as_record(),
    )
    written = write_config_manifest(document, root=root, paths=RuntimePaths())
    publish_snapshot(state.store, snapshot)
    print(f"evidence: {written.path or 'outside the project'}", file=out)
    return int(ExitCode.CONFIGURATION_INVALID if resolution.problem else ExitCode.OK)
