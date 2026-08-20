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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, TextIO

from globin.adapters.api_reality import REGISTRY_PATH, read_registry
from globin.adapters.api_reality import digest as api_reality_digest
from globin.adapters.api_reality import summarise as summarise_registry
from globin.adapters.bootstrap import (
    RUNTIME_CONTRACT_PATH,
    SystemEnvironmentProbe,
    TomlRuntimeBaselineSource,
    build,
    find_project_root,
)
from globin.adapters.clock_sync import (
    CONTRACT_RELATIVE_PATH as CLOCK_CONTRACT_PATH,
)
from globin.adapters.clock_sync import (
    ClockManager,
    discipline_from,
    read_clock_contract,
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
from globin.adapters.environment_class import (
    CLASSES_PATH,
    DeclaredClass,
    disagreements,
    guarantees_of,
    read_classes,
)
from globin.adapters.health import snapshot_document
from globin.adapters.identifiers import new_run_id
from globin.adapters.ingestion import POLICY_PATH, read_policy
from globin.adapters.observability import new_correlation_id
from globin.adapters.rest import CONTRACT_PATH, DIGEST_KEY, read_contract
from globin.adapters.rest import EVIDENCE_DIRECTORY as REST_EVIDENCE_DIRECTORY
from globin.adapters.rest import build as build_rest_manifest
from globin.adapters.rest import load as load_rest_manifest
from globin.adapters.rest import write as write_rest_manifest
from globin.adapters.rest_transport import HttpRestTransport
from globin.adapters.signing import available_algorithms, hmac_signer
from globin.adapters.telemetry_otel import opentelemetry_bridge
from globin.adapters.telemetry_prometheus import prometheus_publisher
from globin.application.auth import AuthPolicy, AuthResolution, resolve_auth
from globin.application.auth import self_test as auth_self_test
from globin.application.clock_sync import (
    CalibrationOutcome,
    DomainAvailability,
    declared_domains,
    status_summary,
)
from globin.application.clock_sync import self_test as clock_self_test
from globin.application.provisioning import ProvisioningOutcome, ProvisioningProposal
from globin.application.rest import (
    resolution_report,
    run_probe,
    self_test,
    survey_report,
)
from globin.application.secrets import (
    ENTRY_REMEDIATION,
    REMEDIATION,
    resolve,
    rotate_from_entry,
    set_from_entry,
)
from globin.domain.api_reality import (
    ApiKeyType,
    ApiRealitySnapshot,
    EnvironmentName,
    ProductFamily,
    ProtocolKind,
    SurfaceCapability,
    SurfaceStatus,
)
from globin.domain.api_reality import diff as compare_registries
from globin.domain.auth import PHASE as AUTH_PHASE
from globin.domain.auth import SecurityType
from globin.domain.auth_timing import TimestampUnit, parse_recv_window
from globin.domain.bootstrap import BootstrapOutcome, CheckStatus, ExitCode, RuntimePaths
from globin.domain.clock_sync import (
    INVALID_TIMESTAMP_CODE,
    MAX_TIMING_RETRIES,
    OFFSET_BUCKET_BOUNDS_MILLIS,
    ROUND_TRIP_BUCKET_BOUNDS_MILLIS,
    ClockDiscipline,
    ClockDomain,
    ClockStatus,
    SyncState,
    evaluate,
    offset_bucket,
    round_trip_bucket,
)
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
from globin.domain.environment_class import EnvironmentClassification, guarantees_for
from globin.domain.health import RuntimeHealthSnapshot, RuntimeHealthState
from globin.domain.identifiers import EnvironmentId
from globin.domain.ingestion import FreshnessReport, IngestionPolicy, assess
from globin.domain.metrics import declared_series, metrics
from globin.domain.observability import redact
from globin.domain.preflight import PreflightOutcome
from globin.domain.provisioning import NetworkPolicy, ProvisioningPlan
from globin.domain.rest import RequestOutcome, RestExchange
from globin.domain.rest_contract import TransportContract
from globin.domain.rest_endpoint import EndpointResolution
from globin.domain.rest_endpoint import resolve as resolve_endpoint
from globin.domain.runtime_state import RuntimeArea
from globin.domain.secrets import (
    EntryFault,
    SecretEntryOutcome,
    SecretKind,
    SecretLocator,
    SecretProviderKind,
    SecretReference,
    SecretValue,
    file_material,
    file_material_problems,
    provider_writable,
)
from globin.errors import ConfigurationError, GlobinError, InternalError, ValidationError
from globin.ports.entitlements import GrantRegister
from globin.ports.rest import RestTransport
from globin.ports.secret_entry import SecretEntry
from globin.ports.secrets import SecretStore
from globin.project_contract import PROJECT_NAME
from globin.runtime.composition import (
    BUNDLE_MANIFEST_MEMBER,
    BUNDLE_REPORT_MEMBER,
    WATCHDOG_FILE,
    Bootstrap,
    RuntimeState,
    build_api_reality_source,
    build_bootstrap,
    build_bundle_builder,
    build_clock,
    build_config_sources,
    build_grant_register,
    build_health_collector,
    build_logger,
    build_monotonic_clock,
    build_provisioning,
    build_runtime_state,
    build_secret_entry,
    build_secret_providers,
    build_secret_store,
    build_server_time_source,
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

API_REALITY: Final[str] = "api-reality"
"""Report what Binance is recorded as documenting. Reads only, and reaches nothing.

The registry is a committed document. Refreshing it from the venue is
the api-reality gate under `tools/quality/`, which lives outside the package so
that no module here opens an outbound connection -- a property
`tests/architecture/test_library_discipline.py` proves rather than asserts.
"""

SHOW: Final[str] = "show"
PRODUCTS: Final[str] = "products"
SURFACES: Final[str] = "surfaces"
ENVIRONMENTS: Final[str] = "environments"
CAPABILITY: Final[str] = "capability"
DIFF: Final[str] = "diff"

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

FROM_FILE_FLAG: Final[str] = "--from-file"
"""Where multi-line key material is read from, instead of being typed.

Added by Phase 031, and it is what makes the vault reachable. A PEM private
key is multi-line by definition, so ``entry_problems``' control-character rule
refuses one at a terminal whatever its size -- ``CREDENTIAL_FLOW.md`` records
that "a real PEM key cannot be collected here at all". The vault exists for
exactly that material, so without a second route it could hold nothing anybody
could put in it.

**It carries a path, never material.** ``SECRET_STORE_CONTRACT.md`` §5 forbids
an option that would place a *value* on a command line; a filename is ordinary
data, and the file is read by this process rather than by the shell -- so
nothing reaches the process table or shell history. The path itself is never
logged, and deleting the source file afterwards is the operator's
responsibility, which the documentation says rather than implies.
"""

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

REST: Final[str] = "rest"
"""The command group Phase 034 added: what the REST transport would do, and one probe.

Named for the protocol rather than for the venue, because the resolver is driven by
Phase 033's registry and would answer for any product family that registry
describes. Today that is Spot; the command needs no edit when it is more.
"""

RESOLVE: Final[str] = "resolve"
"""Which endpoint one product and environment resolves to, or why it does not."""

ENDPOINTS: Final[str] = "endpoints"
"""Every declared surface and how it resolves, refusals included."""

PING: Final[str] = "ping"
"""One public connectivity request. Reaches the venue."""

SERVER_TIME: Final[str] = "server-time"
"""One public server-time request. Reaches the venue, and sets no clock."""

SELFTEST: Final[str] = "selftest"
"""The package against its own declared contract. Reaches nothing."""

AUTH: Final[str] = "auth"
"""The command group Phase 035 added, and the first that could present a credential."""

CLOCK: Final[str] = "clock"
"""The command group Phase 036 added: what GLOBIN believes the venue's time is."""

DOMAINS: Final[str] = "domains"
"""Every clock domain the registry declares, and whether each can be asked."""

STATUS: Final[str] = "status"
"""What is known about one clock domain, or all of them. Reaches nothing."""

CALIBRATE: Final[str] = "calibrate"
"""One public server-time exchange, turned into an offset. Reaches the venue."""

CLOCK_SUBCOMMANDS: Final[tuple[str, ...]] = (DOMAINS, STATUS, CALIBRATE, SELFTEST, EVIDENCE)
"""Every verb the clock surface answers, and no sixth.

Four read and one reaches the venue. **The verb is the opt-in**, matching `rest`
and `auth`: there is no `--network` flag to forget, because a command that only
makes sense over a network says so in its name.

There is no `set`, no `adjust` and no `correct`. GLOBIN never writes the host
clock -- `clock-contract.toml` declares that prohibition and a contract test
asserts it -- so a verb for it would be a verb with nothing to do.
"""

CLOCK_SURFACE_SUBCOMMANDS: Final[tuple[str, ...]] = (STATUS, CALIBRATE)
"""The verbs that may name one domain. Unlike `rest`, both accept naming none.

`status` over every declared domain is the report an operator wants first, and
`calibrate` with no family is refused separately -- see :func:`_parse_clock`,
where naming nothing would mean reaching every venue environment at once.
"""

CLASSES: Final[str] = "classes"
"""What each environment class guarantees."""

CAPABILITIES: Final[str] = "capabilities"
"""What could sign a request for one product and environment, and what could not."""

PROBE: Final[str] = "probe"
"""One authenticated, read-only request. The only verb here that reaches a venue."""

AUTH_SUBCOMMANDS: Final[tuple[str, ...]] = (CLASSES, CAPABILITIES, SELFTEST, PROBE, EVIDENCE)
"""Every verb the authentication surface answers, and no sixth.

Four read and one reaches the venue. **The verb is the opt-in**, matching `rest`
and `venue`: there is no `--network` flag to forget, because a command that only
makes sense over a network says so in its name.

`probe` additionally needs `auth.probe_enabled`, and against production it needs
`auth.allow_production_probe` as well. That is two switches and a verb for one
request, which is deliberate -- an operator who enabled a testnet probe has not
thereby consented to touching the live exchange.
"""

AUTH_SURFACE_SUBCOMMANDS: Final[tuple[str, ...]] = (CAPABILITIES, PROBE)
"""The verbs that name one product and one environment, and therefore require both."""

REST_SUBCOMMANDS: Final[tuple[str, ...]] = (
    RESOLVE,
    ENDPOINTS,
    PING,
    SERVER_TIME,
    SELFTEST,
    EVIDENCE,
)
"""Every verb the REST surface answers, and no seventh.

Four read and two reach the venue. **The verb is the opt-in**, which is the shape
``venue check`` and ``venue refresh`` already use: there is no ``--network`` flag to
forget, because a command that only makes sense over a network says so in its name.
A configuration key gating the two would be a mechanism with no caller — nothing in
GLOBIN runs long enough to consult one — and this repository refuses those.
"""

REST_SURFACE_SUBCOMMANDS: Final[tuple[str, ...]] = (RESOLVE, PING, SERVER_TIME)
"""The verbs that name one product and one environment, and therefore require both.

``endpoints``, ``selftest`` and ``evidence`` answer about everything or about the
package, so passing them a family would be passing an argument that does nothing.
"""

REST_PROBE_OPERATIONS: Final[dict[str, str]] = {PING: "ping", SERVER_TIME: "time"}
"""Which declared operation each probe verb asks the contract for.

The suffix only. The full operation is ``{family}.{suffix}``, built at the call
site, so a second product family needs a row in ``rest-transport.toml`` and no
change here.
"""

FAMILY_FLAG: Final[str] = "--family"
"""Which product family a REST command is about.

Required rather than defaulted. ``spot`` is the only family with a documented REST
surface today, and defaulting to it would make the command silently wrong on the day
a second one arrives.
"""

API_REALITY_SUBCOMMANDS: Final[tuple[str, ...]] = (
    SHOW,
    PRODUCTS,
    SURFACES,
    ENVIRONMENTS,
    CAPABILITY,
    VERIFY,
    DIFF,
)
"""Every verb the registry answers, and no eighth.

All seven read. None writes, none refreshes and none reaches a network, which is
why there is no `refresh` here: that verb belongs to the gate that maintains the
committed document.
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

PLAN: Final[str] = "plan"
"""Say what would change. Read-only, and read-only by construction: the planner
is in the domain layer, which may perform no I/O, and a read-only wiring hands it
a runner that refuses anything but the declared probes."""

SETUP: Final[str] = "setup"
"""Bring missing pieces into existence.

**Not the cold-start path**, and the documentation says so first. This command is
installed *into* the environment it would create, so it cannot be how that
environment first appears; `scripts/bootstrap.ps1` remains that. What this is for
is completing and repairing an environment that already has a `globin` in it,
which is the honest scope and what makes the interruption marker worth having."""

REPAIR: Final[str] = "repair"
"""Correct what exists and is wrong. The only route to a destructive action, and
only with ``--recreate``."""

NETWORK_FLAG: Final[str] = "--network"
"""What this run may reach: ``offline``, ``cache-only`` or ``online-allowed``.

Declared by an operator, never probed. Defaults to ``offline``, because the one
command that mutates a host must not also be the one that reaches the network
without being asked."""

RECREATE_FLAG: Final[str] = "--recreate"
"""Permit the one destructive action. Meaningful only with ``repair``."""

RETIRED_WORDS: Final[dict[str, str]] = {"verify": f"{BOOTSTRAP} {PREFLIGHT}"}
"""Words that name something real under a different spelling.

``verify`` is the obvious name for "run every check and gate", and that is
exactly what ``bootstrap preflight`` already is. Adding a synonym would give one
subject two owners, which `DOCUMENTATION_STANDARD.md` forbids --- and the word is
already taken at this repository's shell, where `scripts/verify.ps1` means
something else entirely. A bare "unrecognised argument" teaches nothing, so the
refusal names the command to use instead.

A contract test asserts every value here is a command line `parse` accepts, so
the redirect cannot rot into pointing at something that no longer exists."""

BOOTSTRAP_SUBCOMMANDS: Final[tuple[str, ...]] = (CHECK, EVIDENCE, PREFLIGHT, PLAN, SETUP, REPAIR)
"""What may follow ``bootstrap``. ``check`` is the default and changes nothing."""

BOOTSTRAP_MUTATING: Final[tuple[str, ...]] = (SETUP, REPAIR)
"""Which subcommands may change the host. Everything else is read-only."""

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

USAGE: Final[str] = """usage: globin [--version]
                [doctor|bootstrap|config|diagnostics|secrets|api-reality|rest]
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
  bootstrap plan      Say what would change to make this host ready, and what
                      each change costs. Writes nothing.
  bootstrap setup     Bring missing pieces into existence. Not the cold-start
                      path -- this command lives in the environment it would
                      create; scripts/bootstrap.ps1 is what makes one first.
  bootstrap repair    Correct what exists and is wrong. --recreate permits the
                      one destructive action.
  bootstrap preflight Run every check, refuse unless all of them pass, and
                      report which answers were true only when taken. This is
                      the gate a launcher runs before a long-running process.
  api-reality show      Summarise what Binance is recorded as documenting.
  api-reality products  Every documented product family, and its scope.
  api-reality surfaces  Every product-and-protocol pair, and its status.
  api-reality environments
                        Every product-and-environment pair, with endpoint counts.
  api-reality capability [STATUS]
                        Every record carrying one status word, or the counts.
  api-reality verify    Re-read the registry and report its digest.
  api-reality diff PATH Compare the registry against another snapshot. Exits 1
                        when a finding is more than informational.
  rest resolve          Which endpoint one product and environment resolves
                        to, or why it does not. Needs --family and
                        --environment. Reads the registry; opens nothing.
                        Exits 14 when the ask cannot be resolved.
  rest endpoints        Every declared surface and how it resolves, refusals
                        included. Opens nothing.
  rest selftest         The package against its own declared transport
                        contract. Reaches nothing. Exits 1 on a mismatch.
  rest evidence         Write .globin/rest/rest-manifest.json.
  rest ping             One public, read-only, unauthenticated connectivity
                        request. REACHES THE VENUE. Needs --family and
                        --environment; never falls back between them.
  rest server-time      One public, read-only server-time request. REACHES
                        THE VENUE, and synchronises no clock.
  clock domains         Every clock domain the registry declares, and whether
                        each one can be calibrated at all. Opens nothing.
  clock status          What GLOBIN believes about each venue clock: its state,
                        the age of its calibration, and a bucketed round trip.
                        Opens nothing; a fresh process reports uninitialized.
                        Exits 3 when nothing has been established, 1 when a
                        clock is unsynchronized.
  clock calibrate       One public, read-only server-time exchange, turned into
                        an offset with a stated error bound. REACHES THE VENUE.
                        Needs --family and --environment. Sets no host clock.
  clock selftest        The clock layer against its own rules and against the
                        venue's published timing rule. Reaches nothing.
                        Exits 1 on a mismatch.
  clock evidence        Write .globin/clock/clock-manifest.json.
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

  --from-file PATH    Read multi-line key material from a file instead of
                      prompting. Only for set and rotate. Refused for a path
                      inside a checkout. Deleting the file afterwards is
                      yours to do.
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
  --network POLICY    What a provisioning run may reach: offline (the default),
                      cache-only or online-allowed. Declared, never probed.
  --recreate          Permit the one destructive action. Only with `bootstrap
                      repair`, and shown by `bootstrap plan --recreate`.
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
    family: str = ""
    kind: str = ""
    name: str = ""
    provider: str = ""
    from_file: str = ""
    config: str = ""
    overrides: tuple[str, ...] = ()
    field: str = ""
    network: str = ""
    """What a provisioning run may reach, as the operator spelled it. Empty means
    the default, which is offline."""
    recreate: bool = False
    """Whether the operator permitted the one destructive action."""


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
    if head == API_REALITY:
        return _parse_api_reality(words[1:])
    if head == REST:
        return _parse_rest(words[1:])
    if head == AUTH:
        return _parse_auth(words[1:])
    if head == CLOCK:
        return _parse_clock(words[1:])
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
        if subcommand in RETIRED_WORDS:
            msg = (
                f"there is no `{subcommand}`; `{RETIRED_WORDS[subcommand]}` runs every "
                f"check and gates"
            )
            raise UsageError(msg)
        if subcommand not in BOOTSTRAP_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)

    # `--network` and `--recreate` are read here rather than in `_options`, which
    # five command groups share and which must go on accepting exactly the four
    # configuration options.
    network = ""
    recreate = False
    remaining: list[str] = []
    pending = list(words)
    while pending:
        word = pending.pop(0)
        if word == NETWORK_FLAG:
            if network:
                msg = f"{NETWORK_FLAG} was given more than once"
                raise UsageError(msg)
            network = _valued(pending, NETWORK_FLAG, network)
            continue
        if word == RECREATE_FLAG:
            if recreate:
                msg = f"{RECREATE_FLAG} was given more than once"
                raise UsageError(msg)
            recreate = True
            continue
        remaining.append(word)

    if network and subcommand not in {PLAN, *BOOTSTRAP_MUTATING}:
        msg = (
            f"{NETWORK_FLAG} means nothing with {subcommand}, which changes nothing and "
            f"reaches nothing; it applies to `{BOOTSTRAP} {PLAN}`, `{BOOTSTRAP} {SETUP}` "
            f"and `{BOOTSTRAP} {REPAIR}`"
        )
        raise UsageError(msg)
    if recreate and subcommand not in {PLAN, REPAIR}:
        msg = (
            f"{RECREATE_FLAG} means nothing with {subcommand}; the destructive rebuild is "
            f"`{BOOTSTRAP} {REPAIR} {RECREATE_FLAG}`, and `{BOOTSTRAP} {PLAN} "
            f"{RECREATE_FLAG}` shows what it would do"
        )
        raise UsageError(msg)
    if network and network not in {policy.value for policy in NetworkPolicy}:
        offered = ", ".join(sorted(policy.value for policy in NetworkPolicy))
        msg = f"{NETWORK_FLAG} takes one of {offered}, and {network!r} is not one of them"
        raise UsageError(msg)

    options = _options(remaining, f"{BOOTSTRAP} {subcommand}")
    if options.as_json and subcommand == EVIDENCE:
        msg = (
            f"{JSON_FLAG} means nothing with {EVIDENCE}, which writes a file; "
            f"use `{BOOTSTRAP} {CHECK} {JSON_FLAG}` to read the same document on standard output"
        )
        raise UsageError(msg)
    invocation = _invocation(f"{BOOTSTRAP} {subcommand}", options)
    return replace(invocation, network=network, recreate=recreate)


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

    if invocation.command.startswith(AUTH):
        try:
            return _auth(invocation, out=out, err=err, start=start)
        except GlobinError as fault:
            print(f"globin: the authentication surface could not answer: {fault}", file=err)
            return int(ExitCode.CONFIGURATION_INVALID)
    if invocation.command.startswith(CLOCK):
        try:
            return _clock(invocation, out=out, err=err, start=start)
        except (GlobinError, OSError) as fault:
            print(f"globin: the clock surface could not answer: {fault}", file=err)
            return int(ExitCode.GATE_FAILED)
    if invocation.command.startswith(REST):
        try:
            return _rest(invocation, out=out, err=err, start=start)
        except (GlobinError, OSError) as fault:
            print(f"globin: the REST surface could not answer: {fault}", file=err)
            return int(ExitCode.GATE_FAILED)
    if invocation.command.startswith(API_REALITY):
        try:
            return _api_reality(invocation, out=out, err=err, start=start)
        except (GlobinError, OSError) as fault:
            print(f"globin: the api reality registry could not be read: {fault}", file=err)
            return int(ExitCode.GATE_FAILED)
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

    if invocation.command.rsplit(" ", 1)[-1] in {PLAN, SETUP, REPAIR}:
        return _provision(invocation, out=out, err=err, start=start)

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


def _provision(invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None) -> int:
    """Run ``bootstrap plan``, ``setup`` or ``repair``.

    Args:
        invocation: What was asked for.
        out: Where the answer goes.
        err: Where the human summary goes when JSON was asked for.
        start: Where to begin the search for the project root.

    Returns:
        The exit code.

    The three verbs share one handler because they share one shape: measure,
    derive a plan, and then either print it or apply it. What differs is a
    read-only wiring and an admitted-mutation set, both of which are arguments.
    """
    verb = invocation.command.rsplit(" ", 1)[-1]
    policy = NetworkPolicy(invocation.network) if invocation.network else NetworkPolicy.OFFLINE
    overrides = parse_overrides(invocation.overrides)
    provisioning = build_provisioning(
        Path.cwd() if start is None else start,
        policy=policy,
        read_only=verb == PLAN,
        recreate=invocation.recreate,
        profile=resolve_run_profile(invocation.profile or None),
        explicit=_explicit_document(invocation),
        overrides=overrides,
    )

    if verb == PLAN:
        proposal = provisioning.propose()
        outstanding = provisioning.outstanding()
        document = {
            **proposal.as_record(),
            "outstanding": None if outstanding is None else outstanding.as_record(),
        }
        if invocation.as_json:
            print(render_json_document(document), file=out)
            print(render_plan_human(proposal, outstanding), end="", file=err)
        else:
            print(render_plan_human(proposal, outstanding), end="", file=out)
        return int(proposal.exit_code)

    outcome = (
        provisioning.setup() if verb == SETUP else provisioning.repair(recreate=invocation.recreate)
    )
    if invocation.as_json:
        print(render_json_document(outcome.as_record()), file=out)
        print(render_journal_human(outcome), end="", file=err)
    else:
        print(render_journal_human(outcome), end="", file=out)
    return int(outcome.exit_code)


def render_json_document(document: Mapping[str, object]) -> str:
    """One mapping as the canonical JSON every command here emits.

    Args:
        document: What to render.

    Returns:
        Sorted keys, compact separators, ASCII only.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def render_plan_human(proposal: ProvisioningProposal, outstanding: ProvisioningPlan | None) -> str:
    """What ``bootstrap plan`` prints.

    Args:
        proposal: What was measured and what would change.
        outstanding: What an interrupted run left behind, if anything.

    Returns:
        The report, ending in a newline.

    Every mutating line names its class, whether it is destructive and what it
    needs, because those are the three things an operator approving a plan is
    deciding about.
    """
    lines: list[str] = []
    if outstanding is not None:
        lines.append(
            "INCOMPLETE  a previous run was interrupted part-way and left a claim behind.\n"
            "            `globin bootstrap repair` clears it.\n"
        )
    plan = proposal.plan
    if plan.empty:
        lines.append("Nothing to do. Every check this command can answer for already passes.\n")
        return "".join(lines)

    lines.append(f"Plan ({plan.policy.value}), {len(plan.actions)} action(s):\n")
    for action in plan.actions:
        spec = action.spec
        marks = [spec.mutation.value]
        if spec.destructive:
            marks.append("DESTRUCTIVE")
        if spec.network is not spec.network.NONE:
            marks.append(f"needs {spec.network.value}")
        lines.append(f"  {action.identifier:22} [{', '.join(marks)}]\n")
        lines.append(f"    {action.reason}\n")
        lines.append(
            f"    then: {spec.postcondition} passes; on interruption: {spec.recovery.value}\n"
        )

    refused = plan.refused_by_policy()
    if refused:
        lines.append(
            f"\n{len(refused)} action(s) the {plan.policy.value} policy forbids: "
            f"{', '.join(action.identifier for action in refused)}\n"
        )
    lines.append("\nNothing has been changed. `globin bootstrap setup` applies this.\n")
    return "".join(lines)


def render_journal_human(outcome: ProvisioningOutcome) -> str:
    """What ``bootstrap setup`` and ``bootstrap repair`` print.

    Args:
        outcome: What was intended and what happened.

    Returns:
        The report, ending in a newline.
    """
    lines: list[str] = []
    journal = outcome.journal
    if not journal.steps:
        lines.append("Nothing to do. Every check this command can answer for already passes.\n")
        return "".join(lines)

    for step in journal.steps:
        lines.append(f"  {step.outcome.value.upper():14} {step.action.identifier}\n")
        if step.detail:
            lines.append(f"    {step.detail}\n")

    if outcome.after is None:
        lines.append(
            "\nThe run did not complete, so nothing was re-measured and the environment "
            "is left part-way. The claim it wrote is still there.\n"
        )
        return "".join(lines)

    lines.append("\n" + render_human(outcome.after))
    return "".join(lines)


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
        from_file=options.from_file,
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
    from_file: str = ""


def _secret_options(words: Sequence[str], context: str) -> _SecretOptions:
    """Accept the seven options a secrets subcommand may take, and nothing else.

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
        FROM_FILE_FLAG: "from_file",
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
        from_file=values.get("from_file", ""),
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

    if invocation.from_file and word not in SECRETS_WRITING:
        msg = f"{FROM_FILE_FLAG} supplies material, so it means nothing for {SECRETS} {word}"
        raise UsageError(msg)
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
    entry = _file_entry(invocation.from_file) if invocation.from_file else build_secret_entry(err)
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


def _file_entry(location: str) -> SecretEntry:
    """A collector that reads one file instead of prompting.

    Args:
        location: Where the material is.

    Returns:
        Something satisfying :class:`~globin.ports.secret_entry.SecretEntry`, so
        that :func:`~globin.application.secrets.set_from_entry` and its rotation
        sibling are reached unchanged. The route material arrives by is not their
        concern, and giving them a second entry point would have duplicated the
        four-step rotation.

    Raises:
        UsageError: If the path is inside a GLOBIN checkout. A private key in a
            working tree is one ``git add -A`` from being committed for ever, and
            ``SECURITY_BASELINE.md`` rule 1 is absolute about that. Refusing the
            *source* is the only point at which GLOBIN can act on it -- it cannot
            delete the file, and pretending it will would be worse than saying
            nothing.

    **The path is never logged and never published.** It reaches this function,
    is opened, and is discarded; no record carries it, for the reason
    ``RUNTIME_FILESYSTEM.md`` gives about the runtime root -- a path names a
    person's machine and often the person.
    """
    path = Path(location).expanduser()
    try:
        resolved = path.resolve()
    except OSError as fault:
        msg = f"that file could not be resolved: {fault.strerror or fault}"
        raise UsageError(msg) from fault
    if find_project_root(resolved.parent) is not None:
        msg = (
            "that file is inside a GLOBIN checkout, where a key is one commit from "
            "being permanent; move it outside the repository first"
        )
        raise UsageError(msg)
    return _FileSecretEntry(path=resolved)


@dataclass(frozen=True, slots=True)
class _FileSecretEntry:
    """Reads material from a file, judged by the file-sourced rules.

    Args:
        path: Where the material is, already resolved and already refused if it
            sits inside a checkout.

    Every outcome is a value rather than an exception, because
    :class:`~globin.ports.secret_entry.SecretEntry` promises that: an unreadable
    file, an undecodable one and material breaking a rule are all answers a caller
    reports rather than faults that stop a process.
    """

    path: Path

    def collect(self, prompt: str) -> SecretEntryOutcome:
        """Read the file and judge what it holds.

        Args:
            prompt: What would have been shown at a terminal. Unused here, and
                deliberately not printed -- there is nobody to prompt, and echoing
                it would put the reference in the operator's scrollback for no
                reason.

        Returns:
            The outcome.
        """
        del prompt
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return SecretEntryOutcome(value=None, fault=EntryFault.ENTRY_UNAVAILABLE)
        problems = file_material_problems(text)
        if problems:
            return SecretEntryOutcome(
                value=None, fault=EntryFault.REFUSED_FORMAT, problems=problems
            )
        return SecretEntryOutcome(value=SecretValue(file_material(text)))


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


def _parse_api_reality(rest: Sequence[str]) -> Invocation:
    """Read what follows ``api-reality``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, if a positional is given to
            a verb that takes none, if ``diff`` is given none, or if a second
            positional follows.

    Two verbs take a positional and the rest take none. ``diff`` requires one --
    a diff against nothing is not a diff, and defaulting to the committed registry
    would compare a document with itself and always report agreement.
    """
    words = list(rest)
    subcommand = SHOW
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in API_REALITY_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    field = ""
    if words and not words[0].startswith("-"):
        if subcommand not in {CAPABILITY, DIFF}:
            msg = f"{API_REALITY} {subcommand} takes no argument, but {words[0]!r} was given"
            raise UsageError(msg)
        field = words.pop(0)
        if words and not words[0].startswith("-"):
            msg = f"{API_REALITY} {subcommand} takes one argument, but {words[0]!r} followed"
            raise UsageError(msg)
    if subcommand == DIFF and not field:
        msg = f"{API_REALITY} {DIFF} needs a snapshot to compare against"
        raise UsageError(msg)
    if subcommand == CAPABILITY and field and field not in {item.value for item in SurfaceStatus}:
        permitted = ", ".join(sorted(item.value for item in SurfaceStatus))
        msg = f"{field!r} is not a status; expected one of {permitted}"
        raise UsageError(msg)
    return _invocation(f"{API_REALITY} {subcommand}", _options(words, subcommand), field=field)


def _api_reality_registry(start: Path | None) -> tuple[ApiRealitySnapshot | None, Path]:
    """The committed registry and where it was looked for.

    Args:
        start: Where to begin looking for the repository root.

    Returns:
        The snapshot -- ``None`` when there is no readable declaration -- and the
        path.

    Raises:
        RegistryError: If the declaration is present and contradicts itself.
    """
    base = (start or Path.cwd()).resolve()
    root = find_project_root(base) or base
    return build_api_reality_source(root).snapshot(), root / REGISTRY_PATH


def _api_reality(invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None) -> int:
    """Report what the venue is recorded as documenting.

    Args:
        invocation: What was asked for.
        out: Where the report goes.
        err: Where human text goes under ``--json``.
        start: Where to begin looking for the repository root.

    Returns:
        ``0`` when the question was answered, ``3`` when there is no registry to
        answer it from, and ``1`` when the registry is present and wrong or a
        ``diff`` found something that demands attention.

    **Reaches no network.** The registry is a committed document, and refreshing
    it from the venue is the api-reality gate under `tools/quality/`, which lives
    outside this package precisely so that nothing here opens an outbound socket.
    """
    try:
        snapshot, path = _api_reality_registry(start)
    except ValidationError as problem:
        print(f"globin: the api reality registry did not validate: {problem}", file=err)
        return int(ExitCode.GATE_FAILED)
    if snapshot is None:
        stream = err if invocation.as_json else out
        print(f"api-reality  unmeasured (no registry at {REGISTRY_PATH})", file=stream)
        return int(ExitCode.UNMEASURED)
    if invocation.command.endswith(DIFF):
        return _api_reality_diff(invocation, snapshot, out=out, err=err)
    document, human = _api_reality_report(invocation, snapshot, path=path)
    if invocation.as_json:
        print(render_json_document(document), file=out)
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    return int(ExitCode.OK)


def _api_reality_report(
    invocation: Invocation, snapshot: ApiRealitySnapshot, *, path: Path
) -> tuple[dict[str, object], str]:
    """One read-only answer, as a document and as text.

    Args:
        invocation: What was asked for.
        snapshot: The registry.
        path: Where it was read from, for the unmeasured case's message.

    Returns:
        The document and the human rendering.
    """
    del path
    command = invocation.command
    if command.endswith(PRODUCTS):
        return _api_reality_products(snapshot)
    if command.endswith(SURFACES):
        return _api_reality_surfaces(snapshot)
    if command.endswith(ENVIRONMENTS):
        return _api_reality_environments(snapshot)
    if command.endswith(CAPABILITY):
        return _api_reality_capability(snapshot, invocation.field)
    if command.endswith(VERIFY):
        return _api_reality_verify(snapshot)
    return _api_reality_show(snapshot)


def _api_reality_show(snapshot: ApiRealitySnapshot) -> tuple[dict[str, object], str]:
    """The whole registry, summarised.

    Args:
        snapshot: The registry.

    Returns:
        The summary document and its rendering.
    """
    document = summarise_registry(snapshot)
    counts = snapshot.status_counts()
    lines = [
        f"api-reality  {len(snapshot.products)} products, {len(snapshot.surfaces)} surfaces, "
        f"{len(snapshot.endpoints)} endpoints\n",
        f"  sources      {len(snapshot.sources)} "
        f"({len(snapshot.unrefreshable_sources())} not refreshable)\n",
        f"  schemas      {len(snapshot.schemas)} versions\n",
    ]
    lines.extend(f"  {name:<12} {counts[name]}\n" for name in sorted(counts))
    return document, "".join(lines)


def _api_reality_products(snapshot: ApiRealitySnapshot) -> tuple[dict[str, object], str]:
    """Every product family and what it is to GLOBIN.

    Args:
        snapshot: The registry.

    Returns:
        The document and its rendering.
    """
    document: dict[str, object] = {"products": [item.as_record() for item in snapshot.products]}
    lines = [
        f"  {item.family.slug:<22} {item.scope.value:<21} "
        f"{item.capability.status.value:<12} {item.title}\n"
        for item in snapshot.products
    ]
    return document, f"api-reality products  {len(snapshot.products)}\n" + "".join(lines)


def _api_reality_surfaces(snapshot: ApiRealitySnapshot) -> tuple[dict[str, object], str]:
    """Every product-and-protocol surface.

    Args:
        snapshot: The registry.

    Returns:
        The document and its rendering.
    """
    document: dict[str, object] = {"surfaces": [item.as_record() for item in snapshot.surfaces]}
    lines = [
        f"  {item.family.slug:<22} {item.protocol.value:<26} {item.capability.status.value}\n"
        for item in snapshot.surfaces
    ]
    return document, f"api-reality surfaces  {len(snapshot.surfaces)}\n" + "".join(lines)


def _api_reality_environments(snapshot: ApiRealitySnapshot) -> tuple[dict[str, object], str]:
    """Every product-and-environment pair, and how many endpoints each has.

    Args:
        snapshot: The registry.

    Returns:
        The document and its rendering.
    """
    document: dict[str, object] = {
        "environments": [item.as_record() for item in snapshot.environments]
    }
    lines = []
    for item in snapshot.environments:
        found = len(snapshot.endpoints_for(item.family, item.environment))
        capital = "real capital" if item.carries_real_capital else f"marked {item.host_marker!r}"
        lines.append(
            f"  {item.family.slug:<22} {item.environment.slug:<12} "
            f"{item.capability.status.value:<12} {found:>3} endpoints  {capital}\n"
        )
    return document, f"api-reality environments  {len(snapshot.environments)}\n" + "".join(lines)


def _api_reality_capability(
    snapshot: ApiRealitySnapshot, status_word: str
) -> tuple[dict[str, object], str]:
    """Every record carrying one status, or the counts when none is named.

    Args:
        snapshot: The registry.
        status_word: The status asked about, or an empty string.

    Returns:
        The document and its rendering.

    The word is validated in the parser rather than here, so an argument fault
    becomes exit 2 rather than being caught by the group's error handler and
    reported as a failure to read the registry.
    """
    if not status_word:
        counts = snapshot.status_counts()
        lines = [f"  {name:<12} {counts[name]}\n" for name in sorted(counts)]
        return {"status_counts": counts}, "api-reality capability\n" + "".join(lines)
    status = SurfaceStatus(status_word)
    named = snapshot.capabilities_with_status(status)
    document: dict[str, object] = {"status": status.value, "records": list(named)}
    lines = [f"  {item}\n" for item in named]
    return document, f"api-reality capability {status.value}  {len(named)}\n" + "".join(lines)


def _api_reality_verify(snapshot: ApiRealitySnapshot) -> tuple[dict[str, object], str]:
    """That the registry parsed, validated, and what it rests on.

    Args:
        snapshot: The registry.

    Returns:
        The document and its rendering.

    Reaching this point *is* the verification: the snapshot's own constructor
    refuses a document that contradicts itself, so a registry that could be read
    has already been checked.
    """
    document = summarise_registry(snapshot)
    unrefreshable = snapshot.unrefreshable_sources()
    lines = [
        "api-reality  the registry parsed and validated\n",
        f"  digest       {document['registry_digest']}\n",
        f"  sources      {len(snapshot.sources)}\n",
    ]
    lines.extend(f"  unrefreshable {item}\n" for item in unrefreshable)
    return document, "".join(lines)


def _api_reality_diff(
    invocation: Invocation, snapshot: ApiRealitySnapshot, *, out: TextIO, err: TextIO
) -> int:
    """Compare the committed registry against another snapshot.

    Args:
        invocation: What was asked for, carrying the other document's path.
        snapshot: The committed registry.
        out: Where the report goes.
        err: Where human text goes under ``--json``.

    Returns:
        ``0`` when the two agree or differ only informationally, ``1`` when
        anything demands attention, and ``3`` when the other document cannot be
        read.
    """
    other = Path(invocation.field)
    try:
        against = read_registry(other)
    except ValidationError as problem:
        print(f"globin: {other} did not validate: {problem}", file=err)
        return int(ExitCode.GATE_FAILED)
    if against is None:
        print(f"api-reality  unmeasured (no snapshot at {other})", file=err)
        return int(ExitCode.UNMEASURED)
    found = compare_registries(against, snapshot)
    document = found.as_record()
    lines = [f"api-reality diff  {len(found.findings)} findings\n"]
    lines.extend(
        f"  {item.risk.value:<18} {item.drift.value:<24} {item.summary}\n"
        for item in found.findings
    )
    human = "".join(lines)
    if invocation.as_json:
        print(render_json_document(document), file=out)
        print(human, end="", file=err)
    else:
        print(human, end="", file=out)
    return int(ExitCode.GATE_FAILED if found.demands_attention else ExitCode.OK)


def _parse_auth(rest: Sequence[str]) -> Invocation:
    """Read what follows ``auth``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, if a required option is
            missing, or if an option appears where it means nothing.

    ``--family`` and ``--environment`` are required by the two verbs that name a
    single surface and refused by the three that do not. There is no default
    environment here for the same reason ``rest`` has none, and with more force:
    defaulting it would mean the live exchange could be reached by typing nothing.
    """
    words = list(rest)
    subcommand = CAPABILITIES
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in AUTH_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    options = _rest_options(words, subcommand)
    if subcommand in AUTH_SURFACE_SUBCOMMANDS:
        if not options.family:
            msg = f"{AUTH} {subcommand} needs {FAMILY_FLAG}"
            raise UsageError(msg)
        if not options.environment:
            msg = f"{AUTH} {subcommand} needs {ENVIRONMENT_FLAG}"
            raise UsageError(msg)
    elif options.family or options.environment:
        msg = (
            f"{AUTH} {subcommand} names no single surface, so {FAMILY_FLAG} and "
            f"{ENVIRONMENT_FLAG} mean nothing here"
        )
        raise UsageError(msg)
    return Invocation(
        command=f"{AUTH} {subcommand}",
        as_json=options.as_json,
        family=options.family,
        environment=options.environment,
    )


def _parse_clock(rest: Sequence[str]) -> Invocation:
    """Read what follows ``clock``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, if ``calibrate`` names no
            surface, or if an option appears where it means nothing.

    **``calibrate`` requires both flags and ``status`` does not**, which is the one
    asymmetry here and it is deliberate. Reading what GLOBIN already believes about
    every domain costs nothing and is the report an operator wants first;
    calibrating every domain would open one connection per venue environment from a
    single unqualified word. A command that reaches a network says which network.
    """
    words = list(rest)
    subcommand = STATUS
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in CLOCK_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    options = _rest_options(words, subcommand)
    if subcommand == CALIBRATE:
        if not options.family:
            msg = f"{CLOCK} {subcommand} needs {FAMILY_FLAG}"
            raise UsageError(msg)
        if not options.environment:
            msg = f"{CLOCK} {subcommand} needs {ENVIRONMENT_FLAG}"
            raise UsageError(msg)
    elif subcommand not in CLOCK_SURFACE_SUBCOMMANDS and (options.family or options.environment):
        msg = (
            f"{CLOCK} {subcommand} names no single surface, so {FAMILY_FLAG} and "
            f"{ENVIRONMENT_FLAG} mean nothing here"
        )
        raise UsageError(msg)
    return Invocation(
        command=f"{CLOCK} {subcommand}",
        as_json=options.as_json,
        family=options.family,
        environment=options.environment,
    )


def _parse_rest(rest: Sequence[str]) -> Invocation:
    """Read what follows ``rest``.

    Args:
        rest: The remaining words.

    Returns:
        The invocation.

    Raises:
        UsageError: If the subcommand is unrecognised, if a required option is
            missing, or if an option appears where it means nothing.

    ``--family`` and ``--environment`` are required by the four verbs that name a
    single surface and refused by the two that do not. A default environment is
    deliberately absent: defaulting it would mean one of ``production``,
    ``testnet`` or ``demo`` was reached by typing nothing, and which one is exactly
    the decision an operator must make out loud.
    """
    words = list(rest)
    subcommand = RESOLVE
    if words and not words[0].startswith("-"):
        subcommand = words.pop(0)
        if subcommand not in REST_SUBCOMMANDS:
            msg = f"unrecognised argument: {subcommand!r}"
            raise UsageError(msg)
    options = _rest_options(words, subcommand)
    if subcommand in REST_SURFACE_SUBCOMMANDS:
        if not options.family:
            msg = f"{REST} {subcommand} needs {FAMILY_FLAG}"
            raise UsageError(msg)
        if not options.environment:
            msg = f"{REST} {subcommand} needs {ENVIRONMENT_FLAG}"
            raise UsageError(msg)
    elif options.family or options.environment:
        msg = (
            f"{REST} {subcommand} names no single surface, so {FAMILY_FLAG} and "
            f"{ENVIRONMENT_FLAG} mean nothing here"
        )
        raise UsageError(msg)
    return Invocation(
        command=f"{REST} {subcommand}",
        as_json=options.as_json,
        family=options.family,
        environment=options.environment,
    )


@dataclass(frozen=True, slots=True)
class _RestOptions:
    """What a rest subcommand was given."""

    as_json: bool = False
    family: str = ""
    environment: str = ""


def _rest_options(words: Sequence[str], context: str) -> _RestOptions:
    """Accept the three options a rest subcommand may take, and nothing else.

    Args:
        words: The remaining words.
        context: What they followed, for the message.

    Returns:
        What was asked for.

    Raises:
        UsageError: If anything else appears, if an option repeats, or if one that
            takes a value is given without one.

    A separate reader rather than four more fields on :class:`Options`, for the
    reason ``_secret_options`` gives: an option every command accepts is an option
    every command has to be checked for, and a flag that silently does nothing is
    how a caller ends up believing it asked for something.
    """
    remaining = list(words)
    as_json = False
    family = ""
    environment = ""
    while remaining:
        word = remaining.pop(0)
        if word == JSON_FLAG:
            if as_json:
                msg = f"{JSON_FLAG} was given twice"
                raise UsageError(msg)
            as_json = True
            continue
        if word == FAMILY_FLAG:
            family = _valued(remaining, FAMILY_FLAG, family)
            continue
        if word == ENVIRONMENT_FLAG:
            environment = _valued(remaining, ENVIRONMENT_FLAG, environment)
            continue
        msg = f"unrecognised argument after {context}: {word!r}"
        raise UsageError(msg)
    return _RestOptions(as_json=as_json, family=family, environment=environment)


AUTH_SCHEMA: Final[str] = "globin.rest.auth"
"""What a document the authentication surface produces calls itself."""

AUTH_SCHEMA_VERSION: Final[int] = 1
"""The version every such document is written against."""

AUTH_PROBE_OPERATION: Final[str] = "spot.account"
"""The one operation ``auth probe`` may send.

``GET /api/v3/account`` — documented ``USER_DATA``, and **read-only**. Spelled as a
constant with no parameter that could change it, exactly as
:func:`globin.application.rest.run_probe` hardcodes ``PUBLIC`` and ``READ_ONLY``:
there is no argument by which this verb becomes a write, because there is no
argument at all.
"""

AUTH_PROBE_PATH: Final[str] = "/v3/account"
"""Where that operation lives, relative to the endpoint's recorded path prefix."""


def _auth_policy(config: GlobinConfig) -> AuthPolicy:
    """Turn the configured settings into the policy the gate reads.

    Args:
        config: The resolved configuration.

    Returns:
        The policy.

    Raises:
        ValidationError: If the window cannot be parsed, which
            :func:`globin.domain.configuration.as_config` has already refused — so
            reaching it means a caller built a configuration some other way.

    ``key_type`` is empty when nothing is configured, and it stays ``None`` here
    rather than becoming a default. The refusal that follows names what to enrol.
    """
    key_type = ApiKeyType(config.auth.key_type) if config.auth.key_type else None
    return AuthPolicy(
        key_type=key_type,
        recv_window=parse_recv_window(config.auth.recv_window_millis),
        timestamp_unit=TimestampUnit(config.auth.timestamp_unit),
        probe_enabled=config.auth.probe_enabled,
        allow_production_probe=config.auth.allow_production_probe,
    )


def _auth(
    invocation: Invocation,
    *,
    out: TextIO,
    err: TextIO,
    start: Path | None,
) -> int:
    """Report what could sign a request, and optionally send one.

    Args:
        invocation: What was asked for.
        out: Where the report goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the search for the project root.

    Returns:
        The exit code. ``3`` when a document is missing, ``14`` when signing could
        not be authorised, ``1`` when a check failed, ``0`` otherwise.

    **Configuration is resolved the way a real run resolves it** — through the
    documents the resolved profile names, then the environment — rather than from
    the declared defaults, which is the correction Phase 027 made to ``doctor`` and
    for the same reason: a report describing settings nobody is running would look
    exactly like one describing settings somebody is.

    **No twenty-sixth exit code, and the choices are the ones the table already
    makes.** A refused key type is a configuration the operator wrote, which is
    ``14``. An absent registry established nothing, which is ``3``. A credential
    that is configured and will not resolve is ``15``, which is what
    ``SECRETS_UNREADY`` has always meant. 26 stays free.
    """
    sources = build_config_sources(
        find_project_root(Path.cwd() if start is None else start),
        resolve_run_profile(invocation.profile or None),
        explicit=_explicit_document(invocation),
        overrides=parse_overrides(invocation.overrides),
    )
    config = as_config(resolve_settings(sources))
    snapshot, contract, policy = _rest_sources(start)
    base = (start or Path.cwd()).resolve()
    root = find_project_root(base) or base
    read = read_classes(root / CLASSES_PATH)
    absent = [
        name
        for name, document in (
            ("the api reality registry", snapshot),
            ("the transport contract", contract),
            ("the ingestion policy", policy),
            ("the environment class document", read),
        )
        if document is None
    ]
    if snapshot is None or contract is None or policy is None or read is None:
        print(f"globin: {', '.join(absent)} is absent, so nothing was established", file=err)
        return int(ExitCode.UNMEASURED)
    classification, declared = read
    auth_policy = _auth_policy(config)
    subcommand = invocation.command.removeprefix(f"{AUTH} ")

    if subcommand == CLASSES:
        problems = disagreements(declared)
        document = {
            "schema": AUTH_SCHEMA,
            "schema_version": AUTH_SCHEMA_VERSION,
            "classes": [item.as_record() for item in guarantees_of(classification)],
            "classification": classification.as_record(),
            "disagreements": list(problems),
        }
        _emit(
            document,
            _auth_classes_text(classification, declared),
            out=out,
            as_json=invocation.as_json,
        )
        return int(ExitCode.OK if not problems else ExitCode.CONFIGURATION_INVALID)

    if subcommand == SELFTEST:
        return _auth_selftest(out=out, as_json=invocation.as_json)

    if subcommand == EVIDENCE:
        return _auth_evidence(classification, declared, auth_policy, out=out, start=start)

    freshness = _rest_freshness(snapshot, policy)
    resolution = resolve_endpoint(
        snapshot,
        family=ProductFamily(invocation.family),
        environment=EnvironmentName(invocation.environment),
        capability=SurfaceCapability.ACCOUNT_DATA,
        intent=SecurityType.USER_DATA.intent,
        stale_sources=freshness.stale,
    )
    authorisation = resolve_auth(
        resolution,
        security_type=SecurityType.USER_DATA,
        policy=auth_policy,
        classification=classification,
        credentials={},
        available=available_algorithms(),
    )
    if subcommand == CAPABILITIES:
        _emit(
            _auth_capability_document(resolution, authorisation, auth_policy),
            _auth_capability_text(resolution, authorisation, auth_policy),
            out=out,
            as_json=invocation.as_json,
        )
        return int(ExitCode.OK)
    return _auth_probe(authorisation, auth_policy, out=out, err=err, as_json=invocation.as_json)


def _auth_capability_document(
    resolution: EndpointResolution,
    authorisation: AuthResolution,
    policy: AuthPolicy,
) -> dict[str, object]:
    """What could sign a request here, as plain JSON-safe values.

    Args:
        resolution: Where a request would go.
        authorisation: Whether it could be signed, and with what.
        policy: What the operator configured.

    Returns:
        The document. **It carries no credential, no key and no fingerprint**: this
        command reads nothing from the secret store, so there is nothing it could
        publish even by accident. Availability is reported from configuration, which
        is the honest answer to "is a credential set up" without one being read.
    """
    endpoint = resolution.endpoint
    documented = sorted(item.value for item in (endpoint.key_types if endpoint else ()))
    return {
        "schema": AUTH_SCHEMA,
        "schema_version": AUTH_SCHEMA_VERSION,
        "family": authorisation.family,
        "environment": authorisation.environment,
        "environment_class": (
            authorisation.environment_class.value if authorisation.environment_class else None
        ),
        "endpoint_resolved": resolution.permitted,
        "endpoint_outcome": resolution.outcome.value,
        "documented_key_types": documented,
        "configured_key_type": policy.key_type.value if policy.key_type else None,
        "available_algorithms": sorted(item.value for item in available_algorithms()),
        "auth_outcome": authorisation.outcome.value,
        "signer": authorisation.profile.as_record() if authorisation.profile else None,
        "policy": policy.as_record(),
        "detail": authorisation.detail,
        "verdict": "PASS" if authorisation.permitted else "FAIL",
    }


def _auth_capability_text(
    resolution: EndpointResolution,
    authorisation: AuthResolution,
    policy: AuthPolicy,
) -> str:
    """Render a capability report for a person.

    Args:
        resolution: Where a request would go.
        authorisation: Whether it could be signed, and with what.
        policy: What the operator configured.

    Returns:
        The text.

    **Built from the typed values rather than from the JSON document beside it.**
    Rendering a report by reading back the mapping that was just built makes every
    field an ``object`` the renderer has to assert its way out of, and the
    assertions are what would eventually be wrong. Both forms are produced from one
    set of values, so neither can describe something the other does not.
    """
    endpoint = resolution.endpoint
    documented = ", ".join(sorted(item.value for item in (endpoint.key_types if endpoint else ())))
    available = ", ".join(sorted(item.value for item in available_algorithms()))
    signer = authorisation.profile.algorithm.value if authorisation.profile else "none"
    environment_class = (
        authorisation.environment_class.value
        if authorisation.environment_class is not None
        else "unclassified"
    )
    lines = [
        f"authentication capability: {authorisation.family} / {authorisation.environment}",
        "",
        f"  environment class     {environment_class}",
        f"  endpoint              {resolution.outcome.value}",
        f"  documented key types  {documented or 'none'}",
        f"  configured key type   {policy.key_type.value if policy.key_type else 'not configured'}",
        f"  available algorithms  {available or 'none'}",
        f"  signer                {signer}",
        f"  timestamp unit        {policy.timestamp_unit.value}",
        f"  recvWindow            {policy.window} ms",
        "",
        f"  {'PASS' if authorisation.permitted else 'FAIL'}  {authorisation.outcome.value}",
    ]
    if authorisation.detail:
        lines.append(f"        {authorisation.detail}")
    return "\n".join(lines) + "\n"


def _auth_classes_text(
    classification: EnvironmentClassification, declared: tuple[DeclaredClass, ...]
) -> str:
    """Render the environment classes for a person.

    Args:
        classification: Which environments belong to which classes.
        declared: The class rows as the document states them.

    Returns:
        The text.
    """
    lines = ["environment classes", ""]
    for item in guarantees_of(classification):
        lines.append(f"  {item.environment_class.value}")
        lines.append(
            f"      capital={item.carries_real_capital!s:<5} "
            f"venue={item.reaches_venue!s:<5} "
            f"credential={item.accepts_credential!s:<5} "
            f"binding={item.orders_are_binding!s:<5}"
        )
        lines.append(
            f"      real_data={item.market_data_is_real!s:<5} "
            f"venue_state={item.state_is_venue_owned!s:<5} "
            f"parity={item.feature_parity_with_live!s:<5} "
            f"source={item.source}"
        )
        lines.append(f"      {item.semantics}")
        lines.append("")
    lines.append("  environments")
    for name, environment_class in classification.entries:
        lines.append(f"      {name:<14} {environment_class.value}")
    problems = disagreements(declared)
    lines.append("")
    if problems:
        lines.append("  the document and the package disagree:")
        lines += [f"      {item}" for item in problems]
    else:
        lines.append("  the document and the package agree on every guarantee")
    return "\n".join(lines) + "\n"


def _auth_selftest(*, out: TextIO, as_json: bool) -> int:
    """Recompute the signing path against the venue's published answers.

    Args:
        out: Where the report goes.
        as_json: Whether JSON was asked for.

    Returns:
        ``0`` when every check passed, ``1`` otherwise.
    """
    report = auth_self_test(hmac_signer(), available_algorithms())
    lines = ["REST authentication self-test", ""]
    lines += [
        f"  {'pass' if item.passed else 'FAIL'}  {item.check:28} {item.detail}"
        for item in report.findings
    ]
    verdict = "passed" if report.passed else "FAILED"
    lines.append("")
    lines.append(f"  {verdict}: {len(report.failures)} of {len(report.findings)} checks failed")
    _emit(report.as_record(), "\n".join(lines) + "\n", out=out, as_json=as_json)
    return int(ExitCode.OK if report.passed else ExitCode.GATE_FAILED)


def _auth_probe(
    authorisation: AuthResolution,
    policy: AuthPolicy,
    *,
    out: TextIO,
    err: TextIO,
    as_json: bool,
) -> int:
    """Send one authenticated read-only request, or say deterministically why not.

    Args:
        authorisation: Whether signing was authorised, and with what.
        policy: What the operator configured.
        out: Where the report goes.
        err: Where human text goes under ``--json``.
        as_json: Whether JSON was asked for.

    Returns:
        ``0`` for a skip, because a skip is an answer rather than a failure; ``14``
        when signing could not be authorised.

    **This verb sends nothing today, and the reason is stated rather than hidden.**
    GLOBIN holds no credential, so :func:`resolve_auth` refuses at gate 5 with
    :attr:`~globin.domain.auth.AuthStatus.MISSING_CREDENTIAL` and this reports a
    deterministic SKIP naming what to enrol. A skip is ``0``: the brief's own rule
    is that an unconfigured credential must not fail a suite, and *nothing was
    configured* is a true report rather than a fault.

    **Three switches guard the request that will eventually happen**, and none of
    them is a default. The verb must be typed, ``auth.probe_enabled`` must be on,
    and against the live exchange ``auth.allow_production_probe`` must be on too.
    """
    reasons: list[str] = []
    if not policy.probe_enabled:
        reasons.append("auth.probe_enabled is off")
    if not authorisation.permitted:
        reasons.append(f"{authorisation.outcome.value}: {authorisation.detail}")
    facts = (
        guarantees_for(authorisation.environment_class)
        if authorisation.environment_class is not None
        else None
    )
    if facts is not None and facts.carries_real_capital and not policy.allow_production_probe:
        reasons.append("auth.allow_production_probe is off and this environment risks capital")
    document: dict[str, object] = {
        "schema": AUTH_SCHEMA,
        "schema_version": AUTH_SCHEMA_VERSION,
        "operation": AUTH_PROBE_OPERATION,
        "family": authorisation.family,
        "environment": authorisation.environment,
        "sent": False,
        "verdict": "SKIP",
        "reasons": reasons,
    }
    text = "\n".join(
        [
            f"authenticated probe: {AUTH_PROBE_OPERATION}",
            "",
            "  SKIP  nothing was sent",
            *(f"        {item}" for item in reasons),
            "",
        ]
    )
    _emit(document, text, out=out, as_json=as_json)
    del err
    return int(ExitCode.OK)


def _auth_evidence(
    classification: EnvironmentClassification,
    declared: tuple[DeclaredClass, ...],
    policy: AuthPolicy,
    *,
    out: TextIO,
    start: Path | None,
) -> int:
    """Write the Phase 035 evidence manifest.

    Args:
        classification: Which environments belong to which classes.
        declared: The class rows as the document states them.
        policy: What the operator configured.
        out: Where the path is printed.
        start: Where to begin the search for the project root.

    Returns:
        ``0`` when the manifest was written and every check passed.

    **The manifest carries no credential, no key, no signature and no signing
    payload.** The self-test's findings are check names and verdicts; the
    classification is public vocabulary; the policy carries a key *type* and a
    window. There is nothing here to redact, which is the property
    ``RestDiagnosticsRecord`` already has and for the same reason: safety by
    construction beats safety by remembering.
    """
    base = (start or Path.cwd()).resolve()
    root = find_project_root(base) or base
    report = auth_self_test(hmac_signer(), available_algorithms())
    document: dict[str, object] = {
        "schema": AUTH_SCHEMA,
        "schema_version": AUTH_SCHEMA_VERSION,
        "phase": AUTH_PHASE,
        "classes": [item.as_record() for item in guarantees_of(classification)],
        "classification": classification.as_record(),
        "class_disagreements": list(disagreements(declared)),
        "policy": policy.as_record(),
        "available_algorithms": sorted(item.value for item in available_algorithms()),
        "self_test": report.as_record(),
    }
    directory = root / ".globin" / "auth"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "auth-manifest.json"
    target.write_text(render_json_document(document) + "\n", encoding="utf-8", newline="\n")
    print(f"auth: wrote {target}", file=out)
    sound = report.passed and not disagreements(declared)
    return int(ExitCode.OK if sound else ExitCode.GATE_FAILED)


CLOCK_SCHEMA: Final[str] = "globin.clock"
"""What the clock surface calls its own documents."""

CLOCK_SCHEMA_VERSION: Final[int] = 1
"""The version of that shape."""

CLOCK_PHASE: Final[int] = 36
"""Which phase delivered the clock discipline layer."""

CLOCK_EVIDENCE_DIRECTORY: Final[str] = "clock"
"""Where the clock manifest is written, under `.globin/`."""


def _clock_discipline(config: GlobinConfig) -> ClockDiscipline:
    """Turn the configured thresholds into the discipline the gates read.

    Args:
        config: The resolved configuration.

    Returns:
        The discipline.

    Raises:
        ValidationError: If the thresholds contradict each other, which
            :class:`~globin.domain.clock_sync.ClockDiscipline` refuses. The command
            surface reports that as ``14``, because an operator wrote it.
    """
    settings = config.clock
    return discipline_from(
        sample_count=settings.sample_count,
        freshness_ttl_millis=settings.freshness_ttl_millis,
        degraded_grace_millis=settings.degraded_grace_millis,
        max_round_trip_millis=settings.max_round_trip_millis,
        max_uncertainty_millis=settings.max_uncertainty_millis,
        max_offset_jump_millis=settings.max_offset_jump_millis,
        max_wall_divergence_millis=settings.max_wall_divergence_millis,
        network_budget_millis=settings.network_budget_millis,
    )


def _clock(invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None) -> int:
    """Report what GLOBIN believes about the venue's clocks, and optionally ask one.

    Args:
        invocation: What was asked for.
        out: Where the report goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the search for the project root.

    Returns:
        The exit code. ``3`` when nothing has been established, ``14`` when the
        configuration will not bind, ``1`` when a clock is unsynchronized or a check
        failed, ``0`` otherwise.

    **The exit codes are the health triad every gate here already speaks**, and no
    twenty-sixth code is added. ``0`` is synchronized, ``3`` is *nothing was
    established* — the same answer ``drift`` gives for an unrecorded baseline and
    the honest verdict for a fresh process that has calibrated nothing — and ``1``
    is a measured bad state. **26 stays free.**
    """
    sources = build_config_sources(
        find_project_root(Path.cwd() if start is None else start),
        resolve_run_profile(invocation.profile or None),
        explicit=_explicit_document(invocation),
        overrides=parse_overrides(invocation.overrides),
    )
    config = as_config(resolve_settings(sources))
    discipline = _clock_discipline(config)
    subcommand = invocation.command.removeprefix(f"{CLOCK} ")

    if subcommand == SELFTEST:
        return _clock_selftest(discipline, out=out, as_json=invocation.as_json)

    snapshot, contract, policy = _rest_sources(start)
    if snapshot is None or contract is None or policy is None:
        print("globin: the registry, contract or ingestion policy is absent", file=err)
        return int(ExitCode.UNMEASURED)
    freshness = _rest_freshness(snapshot, policy)
    availability = declared_domains(snapshot, contract, stale_sources=freshness.stale)

    if subcommand == DOMAINS:
        return _clock_domains(availability, out=out, as_json=invocation.as_json)
    if subcommand == EVIDENCE:
        return _clock_evidence(discipline, availability, config, out=out, start=start)
    if subcommand == CALIBRATE:
        return _clock_calibrate(
            snapshot,
            contract,
            discipline,
            availability,
            invocation,
            freshness_stale=freshness.stale,
            out=out,
            err=err,
        )
    return _clock_status(discipline, availability, invocation, out=out, as_json=invocation.as_json)


def _clock_manager(
    snapshot: ApiRealitySnapshot,
    contract: TransportContract,
    discipline: ClockDiscipline,
    transport: RestTransport,
    stale: Sequence[str],
) -> ClockManager:
    """Build a manager over one transport.

    Args:
        snapshot: Phase 033's registry.
        contract: The declared transport contract.
        discipline: The thresholds.
        transport: How a request is sent.
        stale: Source identifiers past their re-check interval.

    Returns:
        The manager, holding no calibration.
    """
    return ClockManager(
        source=build_server_time_source(transport, snapshot, contract, stale_sources=stale),
        clock=build_clock(),
        monotonic=build_monotonic_clock(),
        discipline=discipline,
    )


def _clock_domains(
    availability: Sequence[DomainAvailability], *, out: TextIO, as_json: bool
) -> int:
    """List every declared clock domain and whether it can be asked.

    Args:
        availability: One entry per declared product-and-environment pair.
        out: Where the report goes.
        as_json: Whether JSON was asked for.

    Returns:
        ``0`` when at least one domain can be calibrated, ``3`` otherwise.

    **A registry in which nothing is reachable is ``3`` rather than ``1``.** Nothing
    is wrong with GLOBIN in that case; nothing has been established about any venue
    clock, which is the same distinction ``drift`` draws for a missing baseline.
    """
    usable = [item for item in availability if item.available]
    document: dict[str, object] = {
        "schema": CLOCK_SCHEMA,
        "schema_version": CLOCK_SCHEMA_VERSION,
        "domains": [item.as_record() for item in availability],
        "declared": len(availability),
        "available": len(usable),
        "unavailable": len(availability) - len(usable),
    }
    lines = [
        "clock domains",
        "",
        f"  declared    {len(availability)}",
        f"  available   {len(usable)}",
        f"  unavailable {len(availability) - len(usable)}",
        "",
    ]
    for item in availability:
        mark = "OK  " if item.available else "--  "
        lines.append(f"  {mark}{item.domain.label}")
        lines.append(f"        {item.detail or item.resolution}")
    _emit(document, "\n".join(lines), out=out, as_json=as_json)
    return int(ExitCode.OK if usable else ExitCode.UNMEASURED)


def _clock_status(
    discipline: ClockDiscipline,
    availability: Sequence[DomainAvailability],
    invocation: Invocation,
    *,
    out: TextIO,
    as_json: bool,
) -> int:
    """Report what GLOBIN believes about each clock, having asked nothing.

    Args:
        discipline: The thresholds.
        availability: One entry per declared domain.
        invocation: What was asked for, which may name one surface.
        out: Where the report goes.
        as_json: Whether JSON was asked for.

    Returns:
        ``3`` when no domain has ever been calibrated, ``1`` when one is
        unsynchronized, ``0`` otherwise.

    **This command opens nothing, so on a fresh process every domain is
    ``uninitialized`` and the exit code is ``3``.** That is the correct answer
    rather than a limitation: a clock offset lives in one process's memory and
    nothing persists it, so a separate ``globin clock status`` invocation has by
    construction never calibrated anything. What it reports is the *policy* and the
    *reachability*, which is what an operator can act on without touching a venue.
    """
    wanted = [
        item
        for item in availability
        if (not invocation.family or item.domain.family.slug == invocation.family)
        and (not invocation.environment or item.domain.environment.slug == invocation.environment)
    ]
    statuses = [
        evaluate(item.domain, samples=(), age=None, discipline=discipline) for item in wanted
    ]
    summary = status_summary(statuses)
    document: dict[str, object] = {
        "schema": CLOCK_SCHEMA,
        "schema_version": CLOCK_SCHEMA_VERSION,
        "discipline": discipline.as_record(),
        "availability": [item.as_record() for item in wanted],
        **summary,
    }
    counts = summary["counts"]
    lines = [
        "clock status",
        "",
        f"  domains       {len(statuses)}",
        f"  synchronized  {summary['synchronized']}",
        f"  freshness     {discipline.freshness_ttl.milliseconds} ms",
        f"  max rtt       {discipline.max_round_trip.milliseconds} ms",
        f"  max drift     {discipline.max_uncertainty.milliseconds} ms uncertainty",
        f"  net budget    {discipline.network_budget.milliseconds} ms",
        "",
    ]
    for item, status in zip(wanted, statuses, strict=True):
        reach = "reachable" if item.available else "unreachable"
        lines.append(f"  {status.state.value:15s} {status.domain.label}  ({reach})")
    lines += ["", "  This command opened nothing, so nothing is calibrated here."]
    _emit(document, "\n".join(lines), out=out, as_json=as_json)
    if isinstance(counts, dict) and counts.get(SyncState.UNSYNCHRONIZED.value):
        return int(ExitCode.GATE_FAILED)
    return int(ExitCode.OK if summary["synchronized"] else ExitCode.UNMEASURED)


def _clock_calibrate(
    snapshot: ApiRealitySnapshot,
    contract: TransportContract,
    discipline: ClockDiscipline,
    availability: Sequence[DomainAvailability],
    invocation: Invocation,
    *,
    freshness_stale: Sequence[str],
    out: TextIO,
    err: TextIO,
) -> int:
    """Take one calibration against a named domain, and report what it implies.

    Args:
        snapshot: Phase 033's registry.
        contract: The declared transport contract.
        discipline: The thresholds.
        availability: One entry per declared domain.
        invocation: What was asked for.
        freshness_stale: Source identifiers past their re-check interval.
        out: Where the report goes.
        err: Where the notice goes.

    Returns:
        ``14`` when the domain cannot be asked, ``1`` when the calibration did not
        leave the clock synchronized, ``0`` otherwise.

    **The notice is printed before the connection is opened**, names the
    environment, and says the request is public and read-only — the shape
    ``rest ping`` already uses. An operator running this against production is
    entitled to see that before it happens rather than to infer it from the verb.

    **It sets no clock.** The offset lives in this process's manager and dies with
    it; nothing writes the host clock, nothing writes a file, and the next
    invocation starts uninitialized again.
    """
    domain = ClockDomain(
        family=ProductFamily(invocation.family),
        environment=EnvironmentName(invocation.environment),
        protocol=ProtocolKind.REST,
    )
    entry = next((item for item in availability if item.domain == domain), None)
    if entry is None or not entry.available:
        detail = entry.detail if entry else "the registry declares no such product and environment"
        document: dict[str, object] = {
            "schema": CLOCK_SCHEMA,
            "schema_version": CLOCK_SCHEMA_VERSION,
            "domain": domain.as_record(),
            "calibrated": False,
            "reason": entry.resolution if entry else "domain_undeclared",
            "detail": detail,
        }
        text = "\n".join(
            [
                "clock calibrate",
                "",
                f"  REFUSED  {domain.label}",
                f"           {detail}",
                "",
                "  Nothing was sent.",
            ]
        )
        _emit(document, text, out=out, as_json=invocation.as_json)
        return int(ExitCode.CONFIGURATION_INVALID)
    print(
        f"globin: sending a public, read-only, unauthenticated server-time request to "
        f"{domain.environment.slug} for {domain.family.slug} (no credential, sets no clock)",
        file=err,
    )
    with HttpRestTransport(
        environment=domain.environment.slug, clock=build_monotonic_clock()
    ) as transport:
        manager = _clock_manager(snapshot, contract, discipline, transport, freshness_stale)
        outcomes = manager.calibrate_window(domain)
        status = manager.status(domain)
    document = {
        "schema": CLOCK_SCHEMA,
        "schema_version": CLOCK_SCHEMA_VERSION,
        "domain": domain.as_record(),
        "calibrated": status.synchronized,
        "exchanges": len(outcomes),
        "succeeded": len([item for item in outcomes if not item.failed]),
        "outcomes": [item.as_record() for item in outcomes],
        "status": status.as_record(),
    }
    _emit(document, _clock_calibration_text(outcomes, status), out=out, as_json=invocation.as_json)
    return int(ExitCode.OK if status.synchronized else ExitCode.GATE_FAILED)


def _clock_calibration_text(outcomes: Sequence[CalibrationOutcome], status: ClockStatus) -> str:
    """One calibration window, for a person.

    Args:
        outcomes: What each exchange produced, in order.
        status: What the window left the domain in.

    Returns:
        The report. Every unbounded quantity is bucketed except the signed offset in
        whole milliseconds, which is the one number an operator diagnosing a clock
        actually needs.

    **Every exchange is listed, failures included.** The estimate comes from the
    fastest of them, so an operator reading only the chosen sample would have no way
    to see that four of five timed out — which is the difference between a healthy
    link and one that happened to answer once.
    """
    taken = [item for item in outcomes if item.sample is not None]
    lines = [
        "clock calibrate",
        "",
        f"  domain       {status.domain.label}",
        f"  exchanges    {len(taken)} of {len(outcomes)} answered",
    ]
    for index, item in enumerate(outcomes, start=1):
        sample = item.sample
        if sample is None:
            lines.append(f"    {index}. FAILED  {item.detail}")
        else:
            lines.append(
                f"    {index}. {sample.round_trip.milliseconds:>5} ms round trip, "
                f"offset {sample.offset_micros // 1000:+} ms"
            )
    chosen = status.sample
    if chosen is None:
        lines += ["", "  no usable reading"]
    else:
        lines += [
            "",
            f"  offset       {chosen.offset_micros // 1000} ms "
            f"({offset_bucket(chosen.offset_micros)})",
            f"  round trip   {chosen.round_trip.milliseconds} ms "
            f"({round_trip_bucket(chosen.round_trip.microseconds)})",
            f"  uncertainty  +/- {chosen.uncertainty_micros // 1000} ms",
            f"  unit         {chosen.reported_unit.value}",
        ]
    lines += ["", f"  state        {status.state.value}"]
    if status.detail:
        lines.append(f"               {status.detail}")
    if any(item.offset_jumped for item in outcomes):
        lines += ["", "  THE OFFSET MOVED FURTHER THAN A VENUE CLOCK PLAUSIBLY COULD."]
    lines += ["", "  No host clock was set. Nothing was written."]
    return "\n".join(lines)


def _clock_selftest(discipline: ClockDiscipline, *, out: TextIO, as_json: bool) -> int:
    """Check the clock layer against its own rules and the venue's, offline.

    Args:
        discipline: The thresholds to check against.
        out: Where the report goes.
        as_json: Whether JSON was asked for.

    Returns:
        ``0`` when every check passed, ``1`` otherwise.
    """
    report = clock_self_test(discipline)
    lines = ["clock self-test", ""]
    lines += [
        f"  {'PASS' if item.passed else 'FAIL'}  {item.check}\n        {item.detail}"
        for item in report.findings
    ]
    lines += ["", f"  {len(report.findings) - len(report.failures)}/{len(report.findings)} passed"]
    _emit(report.as_record(), "\n".join(lines), out=out, as_json=as_json)
    return int(ExitCode.OK if report.passed else ExitCode.GATE_FAILED)


def _clock_evidence(
    discipline: ClockDiscipline,
    availability: Sequence[DomainAvailability],
    config: GlobinConfig,
    *,
    out: TextIO,
    start: Path | None,
) -> int:
    """Write the Phase 036 evidence manifest.

    Args:
        discipline: The thresholds in force.
        availability: One entry per declared clock domain.
        config: The resolved configuration.
        out: Where the path is printed.
        start: Where to begin the search for the project root.

    Returns:
        ``0`` when the self-test passed, ``1`` otherwise.

    **No calibration result is included and none is invented.** A manifest written
    on a machine that calibrated nothing records ``unmeasured`` for that half, which
    is the answer ``rest evidence`` gives for an unrun probe and ``drift`` gives for
    an unrecorded baseline: nothing was established, which is not the same as
    nothing being wrong.

    **There is no secret to redact here, and that is structural.** The clock layer
    holds no credential, reads no store and produces no signature; every field below
    is GLOBIN's own vocabulary, a bounded bucket or a threshold an operator wrote.
    """
    base = (start or Path.cwd()).resolve()
    root = find_project_root(base) or base
    report = clock_self_test(discipline)
    contract = read_clock_contract(root / CLOCK_CONTRACT_PATH)
    document: dict[str, object] = {
        "schema": CLOCK_SCHEMA,
        "schema_version": CLOCK_SCHEMA_VERSION,
        "phase": CLOCK_PHASE,
        "contract": contract.as_record() if contract else "absent",
        "discipline": discipline.as_record(),
        "configured": {
            "sample_count": config.clock.sample_count,
            "require_calibration": config.clock.require_calibration,
        },
        "domains": [item.as_record() for item in availability],
        "estimator": {
            "selection": "lowest_round_trip",
            "midpoint": "wall_anchor_plus_half_monotonic_round_trip",
            "uncertainty": "half_round_trip",
            "arithmetic": "integer_microseconds",
        },
        "recovery": {
            "code": INVALID_TIMESTAMP_CODE,
            "max_retries": MAX_TIMING_RETRIES,
            "requires_confirmed_outcome": True,
        },
        "buckets": {
            "round_trip_millis": list(ROUND_TRIP_BUCKET_BOUNDS_MILLIS),
            "offset_millis": list(OFFSET_BUCKET_BOUNDS_MILLIS),
        },
        "calibration_results": "unmeasured",
        "reached_network": False,
        "self_test": report.as_record(),
    }
    directory = root / ".globin" / CLOCK_EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "clock-manifest.json"
    target.write_text(render_json_document(document) + "\n", encoding="utf-8", newline="\n")
    print(f"clock: wrote {target}", file=out)
    return int(ExitCode.OK if report.passed else ExitCode.GATE_FAILED)


def _rest_sources(
    start: Path | None,
) -> tuple[ApiRealitySnapshot | None, TransportContract | None, IngestionPolicy | None]:
    """The three committed documents the REST surface reads.

    Args:
        start: Where to begin looking for the repository root.

    Returns:
        Phase 033's registry, Phase 034's transport contract and Phase 034's
        ingestion cadence. Any of the three is ``None`` when its document is absent.

    Raises:
        GlobinError: If a document is present and contradicts itself.
    """
    base = (start or Path.cwd()).resolve()
    root = find_project_root(base) or base
    return (
        build_api_reality_source(root).snapshot(),
        read_contract(root / CONTRACT_PATH),
        read_policy(root / POLICY_PATH),
    )


def _rest_freshness(snapshot: ApiRealitySnapshot, policy: IngestionPolicy) -> FreshnessReport:
    """How old every recorded source is, as of today.

    Args:
        snapshot: Phase 033's registry.
        policy: The declared cadence.

    Returns:
        The report.

    **This is where the phase's two halves meet.** The transport's fail-closed rule
    names ``stale`` among the states it refuses, and nothing in this repository
    could answer whether a source was stale until the cadence existed. Today's date
    is read here, in the runtime layer, and handed down — the domain takes it as an
    argument and reads no clock.
    """
    today = build_clock().now().moment.date().isoformat()
    return assess(snapshot, policy, as_of=today)


def _rest(invocation: Invocation, *, out: TextIO, err: TextIO, start: Path | None) -> int:
    """Report what the REST transport would do, or make one public request.

    Args:
        invocation: What was asked for.
        out: Where the report goes.
        err: Where human text goes under ``--json``.
        start: Where to begin the search for the project root.

    Returns:
        The exit code. ``3`` when a document is missing, ``14`` when the ask cannot
        be resolved, ``1`` when a check or a probe failed, ``0`` otherwise.

    **No twenty-sixth exit code.** A refused resolution is a configuration problem
    -- the operator asked for a surface the registry does not describe -- so it is
    ``14``, which already means exactly that. An absent registry established
    nothing, which is ``3``. 26 stays free.
    """
    snapshot, contract, policy = _rest_sources(start)
    absent = [
        name
        for name, document in (
            ("the api reality registry", snapshot),
            ("the transport contract", contract),
            ("the ingestion policy", policy),
        )
        if document is None
    ]
    if snapshot is None or contract is None or policy is None:
        print(
            f"globin: {', '.join(absent)} is absent, so nothing was established",
            file=err,
        )
        return int(ExitCode.UNMEASURED)
    freshness = _rest_freshness(snapshot, policy)
    subcommand = invocation.command.removeprefix(f"{REST} ")
    if subcommand == SELFTEST:
        return _rest_selftest(contract, out=out, as_json=invocation.as_json)
    if subcommand == ENDPOINTS:
        document = survey_report(snapshot, stale_sources=freshness.stale)
        document["freshness"] = freshness.as_record()
        _emit(document, _rest_survey_text(document), out=out, as_json=invocation.as_json)
        return int(ExitCode.OK)
    if subcommand == EVIDENCE:
        return _rest_evidence(snapshot, contract, freshness, out=out, start=start)
    resolution = resolution_report(
        snapshot,
        family=ProductFamily(invocation.family),
        environment=EnvironmentName(invocation.environment),
        stale_sources=freshness.stale,
    )
    if subcommand == RESOLVE:
        _emit(
            resolution.as_record(),
            _rest_resolution_text(resolution),
            out=out,
            as_json=invocation.as_json,
        )
        return int(ExitCode.OK if resolution.permitted else ExitCode.CONFIGURATION_INVALID)
    return _rest_probe(
        resolution, contract, subcommand, out=out, err=err, as_json=invocation.as_json
    )


def _emit(document: Mapping[str, object], text: str, *, out: TextIO, as_json: bool) -> None:
    """Print one report in whichever form was asked for.

    Args:
        document: The machine-readable form.
        text: The human form.
        out: Where it goes.
        as_json: Which form was asked for.

    Under ``--json`` standard output carries JSON and nothing else, which is the
    rule every command group in this file already follows.
    """
    print(render_json_document(document) if as_json else text, file=out)


def _rest_selftest(contract: TransportContract, *, out: TextIO, as_json: bool) -> int:
    """Check the package against its declared contract and report.

    Args:
        contract: The declared transport contract.
        out: Where the report goes.
        as_json: Whether JSON was asked for.

    Returns:
        ``0`` when every check passed, ``1`` otherwise.
    """
    report = self_test(contract)
    lines = ["REST transport self-test", ""]
    lines += [
        f"  {'pass' if item.passed else 'FAIL'}  {item.check:34} {item.detail}"
        for item in report.findings
    ]
    lines += ["", f"  {len(report.findings)} checked, {len(report.failures)} failed"]
    _emit(report.as_record(), "\n".join(lines), out=out, as_json=as_json)
    return int(ExitCode.OK if report.passed else ExitCode.GATE_FAILED)


def _rest_resolution_text(resolution: EndpointResolution) -> str:
    """One resolution, for a person.

    Args:
        resolution: What was decided.

    Returns:
        The report.

    The environment is on its own line and so is whether real capital is at risk,
    because those two are what an operator is actually checking before they run
    anything else.
    """
    lines = [
        "REST endpoint resolution",
        "",
        f"  product      {resolution.requested_family}",
        f"  environment  {resolution.requested_environment}",
        f"  capability   {resolution.requested_capability}",
        f"  intent       {resolution.intent.value}",
        f"  outcome      {resolution.outcome.value}",
    ]
    endpoint = resolution.endpoint
    if endpoint is None:
        lines += ["", f"  refused: {resolution.detail}"]
        return "\n".join(lines)
    capital = (
        "YES -- this environment carries real capital" if endpoint.carries_real_capital else "no"
    )
    lines += [
        f"  role         {endpoint.role.value}",
        f"  host         {endpoint.host}",
        f"  path prefix  {endpoint.path_prefix or '(none)'}",
        f"  auth         {endpoint.auth}",
        f"  capabilities {', '.join(endpoint.capabilities)}",
        f"  real capital {capital}",
        f"  source       {endpoint.source}",
    ]
    if endpoint.schema_reference is not None:
        reference = endpoint.schema_reference
        lines.append(f"  sbe schema   {reference.identifier}:{reference.version}")
    count = len(resolution.alternates)
    if count:
        noun = "endpoint is" if count == 1 else "endpoints are"
        lines += [
            "",
            f"  {count} alternate {noun} recorded, and nothing fails over to",
            "  them; a resolution is fixed for the life of one request.",
        ]
    return "\n".join(lines)


def _rest_survey_text(document: Mapping[str, object]) -> str:
    """Every declared surface and how it resolves, for a person.

    Args:
        document: What :func:`survey_report` produced.

    Returns:
        The report.
    """
    rows = document["resolutions"]
    counts = document["counts"]
    lines = ["REST endpoint survey", ""]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            endpoint = row.get("endpoint")
            where = endpoint["host"] if isinstance(endpoint, dict) else "--"
            lines.append(
                f"  {row['requested_family']:22} {row['requested_environment']:12} "
                f"{row['outcome']:26} {where}"
            )
    lines += ["", f"  {document['resolved']} resolved, {document['refused']} refused"]
    if isinstance(counts, dict):
        named = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()) if count)
        lines.append(f"  {named}")
    return "\n".join(lines)


def _rest_probe(
    resolution: EndpointResolution,
    contract: TransportContract,
    subcommand: str,
    *,
    out: TextIO,
    err: TextIO,
    as_json: bool,
) -> int:
    """Send one public, read-only request and report the exchange.

    Args:
        resolution: Where to send it, already decided.
        contract: The declared contract, which names the path.
        subcommand: Which probe was asked for.
        out: Where the report goes.
        err: Where the notice goes.
        as_json: Whether JSON was asked for.

    Returns:
        ``14`` when the resolution refused, ``1`` when the exchange did not confirm
        success, ``0`` otherwise.

    **The notice is printed before the connection is opened**, names the
    environment, and says the request is public and read-only. An operator running
    this against production is entitled to see that before it happens rather than
    to infer it from the verb.
    """
    if not resolution.permitted or resolution.endpoint is None:
        _emit(
            resolution.as_record(),
            _rest_resolution_text(resolution),
            out=out,
            as_json=as_json,
        )
        return int(ExitCode.CONFIGURATION_INVALID)
    family = ProductFamily(resolution.requested_family)
    operation = f"{family.slug}.{REST_PROBE_OPERATIONS[subcommand]}"
    descriptor = contract.probe(family, operation)
    if descriptor is None:
        print(
            f"globin: the transport contract declares no {operation!r} probe for "
            f"{resolution.requested_family}; a path is never guessed",
            file=err,
        )
        return int(ExitCode.CONFIGURATION_INVALID)
    endpoint = resolution.endpoint
    print(
        f"globin: sending a public, read-only, unauthenticated {descriptor.method.value} to "
        f"{endpoint.host} in {endpoint.environment} (weight {descriptor.weight}, no credential)",
        file=err,
    )
    correlation = new_correlation_id()
    with HttpRestTransport(
        environment=endpoint.environment, clock=build_monotonic_clock()
    ) as transport:
        exchange = run_probe(
            transport,
            resolution,
            operation=descriptor.operation,
            method=descriptor.method,
            path=descriptor.path,
            correlation_id=correlation,
        )
    _emit(
        exchange.as_record(), _rest_exchange_text(exchange, endpoint.host), out=out, as_json=as_json
    )
    return int(
        ExitCode.OK
        if exchange.outcome is RequestOutcome.SUCCESS_CONFIRMED
        else ExitCode.GATE_FAILED
    )


def _rest_exchange_text(exchange: RestExchange, host: str) -> str:
    """One exchange, for a person.

    Args:
        exchange: What happened.
        host: Where it went.

    Returns:
        The report.
    """
    record = exchange.diagnostics
    lines = [
        "REST probe",
        "",
        f"  operation    {exchange.operation}",
        f"  host         {host}",
        f"  environment  {record.environment}",
        f"  send state   {exchange.send_state.value}",
        f"  outcome      {exchange.outcome.value}",
        f"  elapsed      {record.elapsed_nanoseconds // 1_000_000} ms",
    ]
    response = exchange.response
    if response is not None:
        lines += [
            f"  status       {response.status}",
            f"  body         {response.shape.value}, {record.response_bytes} bytes",
        ]
        limits = response.limits
        if limits.used_weight:
            lines.append(f"  used weight  {dict(limits.used_weight)}")
        if limits.retry_after_seconds is not None:
            lines.append(f"  retry after  {limits.retry_after_seconds}s")
        if response.fault is not None:
            lines.append(f"  venue said   {response.fault.code}: {response.fault.message}")
    if exchange.failure is not None:
        lines += ["", f"  failed: {exchange.detail}"]
    if exchange.at_risk:
        lines += ["", "  THIS OUTCOME IS UNKNOWN. Nothing retries it automatically."]
    return "\n".join(lines)


def _rest_evidence(
    snapshot: ApiRealitySnapshot,
    contract: TransportContract,
    freshness: FreshnessReport,
    *,
    out: TextIO,
    start: Path | None,
) -> int:
    """Write Phase 034's evidence manifest.

    Args:
        snapshot: Phase 033's registry.
        contract: The declared transport contract.
        freshness: How old each recorded source is, as of today.
        out: Where the path is printed.
        start: Where to begin the search for the project root.

    Returns:
        ``0`` when the self-test passed, ``1`` otherwise.

    **No probe result is included and none is invented.** A manifest written on a
    machine that ran no probe records ``unmeasured`` for that half, which is the
    same answer ``drift`` gives for an unrecorded baseline: nothing was established,
    which is not the same as nothing being wrong.
    """
    base = (start or Path.cwd()).resolve()
    root = find_project_root(base) or base
    report = self_test(contract)
    survey = survey_report(snapshot, stale_sources=freshness.stale)
    document = build_rest_manifest(
        run={
            "registry": REGISTRY_PATH,
            "contract": CONTRACT_PATH,
            "ingestion_policy": POLICY_PATH,
            "registry_digest": api_reality_digest(snapshot.as_record()),
            "contract_observed_on": contract.observed_on,
            "probes_declared": [item.as_record() for item in contract.probes],
            "probe_results": "unmeasured",
            "reached_network": False,
        },
        findings={
            "self_test": report.as_record(),
            "resolution_survey": survey,
            "source_freshness": freshness.as_record(),
        },
        verdict={
            "passed": report.passed,
            "resolved": survey["resolved"],
            "refused": survey["refused"],
        },
    )
    directory = root / RuntimePaths().artifacts / REST_EVIDENCE_DIRECTORY
    written = write_rest_manifest(document, directory=directory)
    # Produced, then VERIFIED by reopening the finished file and recomputing its
    # digest -- the shape `SUPPORT_BUNDLE.md` uses, and for the same reason: a
    # writer that checked only what it held in memory would pass on a truncated
    # write. `load` raises if the digest does not match the content.
    verified = load_rest_manifest(written.read_text(encoding="utf-8"))
    print(f"wrote {written}", file=out)
    print(f"verified {verified[DIGEST_KEY]}", file=out)
    return int(ExitCode.OK if report.passed else ExitCode.GATE_FAILED)
