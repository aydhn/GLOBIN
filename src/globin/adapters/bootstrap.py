"""Reading the machine, locating the project, and writing what was found.

The only module in the bootstrap that touches the world. Everything above it is
handed facts; this is where the facts come from — :mod:`sys`, :mod:`platform`,
:mod:`sysconfig`, :mod:`importlib.metadata`, :mod:`pathlib` and :mod:`tomllib`.
Keeping it here is what lets every judgement in :mod:`globin.domain.bootstrap` be
tested from literals.

**No absolute path leaves this module.** A path is turned into a
:class:`~globin.domain.bootstrap.RecordedPath` at the moment it is observed, so
the layers above never hold one and cannot publish one. That is stronger than
filtering the evidence afterwards, which only works while somebody remembers to
do it.

**The leak scanner is not imported here, deliberately.**
``tools/quality/evidence/redaction.py`` scans published artefacts, and it says
about itself that a verifier does not import the package it verifies. The
production side redacts through
:func:`globin.domain.observability.redact` at the point a record is built, and
``tests/contract/test_bootstrap_contract.py`` applies the verifier's scanner to
what this module actually produced. Two independent mechanisms, which is the
point.

**The manifest's shape is the one the quality gates already proved.** Sorted
keys, compact separators, ASCII only, one line and a trailing newline, a digest
over everything except the digest field, and a reader that refuses a document
whose schema, version or digest disagrees. Repeating a solved shape is cheaper
than inventing a second one, and a reader who knows ``.globin/runtime`` knows
this.
"""

import hashlib
import json
import platform
import struct
import sys
import sysconfig
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final

from globin.adapters.dependency import (
    installed_versions,
    marker_environment,
    python_full_version,
    read_lock,
)
from globin.application.environment import snapshot_from
from globin.application.secrets import entitlement, readiness
from globin.domain.bootstrap import (
    CREATED_PATHS,
    MAX_ROOT_SEARCH_DEPTH,
    BootstrapOutcome,
    CheckStatus,
    DependencyReadiness,
    EntitlementReadiness,
    HostFacts,
    InterpreterFacts,
    PathLocation,
    ProjectIdentity,
    RecordedPath,
    RuntimeBaseline,
    RuntimePaths,
    SecretReadiness,
    checks,
    readiness_for,
    recorded_absent,
    recorded_inside,
    recorded_outside,
)
from globin.domain.dependency import (
    DependencyInventory,
    LockReading,
    LockState,
    canonical_name,
    inventory_from,
    requirement_name,
)
from globin.domain.entitlements import CredentialRequirement
from globin.domain.environment import EnvironmentCapabilitySnapshot
from globin.domain.observability import redact
from globin.domain.secrets import SecretReference
from globin.errors import ConfigurationError
from globin.ports.entitlements import GrantRegister
from globin.ports.environment import ToolchainProbe, WindowsSystemApi
from globin.ports.secrets import SecretStore
from globin.project_contract import PACKAGE_NAME

RUNTIME_CONTRACT_PATH: Final[str] = "docs/engineering/runtime-contract.toml"
"""Where the declared baseline lives, relative to the project root.

The same file ``tools/quality/runtime`` reads. One declaration, two readers, and
neither of them a copy of the other — a second contract for the application to
satisfy is exactly the drift ``SOURCE_OF_TRUTH.md`` exists to prevent.
"""

PROJECT_FILE: Final[str] = "pyproject.toml"
"""The sentinel the root search looks for."""

RUNTIME_LOCK: Final[str] = "pylock.toml"
"""The lock that must accompany a declared runtime dependency."""

SCHEMA: Final[str] = "globin.bootstrap.manifest"
"""Identifies what kind of document this is, so another manifest fed to this
reader is refused by name rather than by a missing key."""

SCHEMA_VERSION: Final[int] = 3
"""Bumped whenever the document changes shape, and inside the digested payload so
that a canonicalisation change cannot collide with an older digest.

Two since Phase 029, which added a `readiness` word to the verdict and a
dependency `inventory` to the observed dependencies. `load` already refuses a
document whose version it does not recognise, with a message telling the reader
to regenerate it, so the bump is safe by construction rather than by anybody
remembering to migrate.

Three since Phase 032, which renamed the observed `secrets` section to
`references`. That section had been published as the literal string `[redacted]`
since Phase 029 -- `redact` matches field names by substring, and `secrets`
contains `secret` -- so the counts it exists to carry never survived. Renaming is
what a versioned schema is for; the alternative was an exception inside the
redactor, which would have weakened a default for every caller in order to fix
one key."""

PHASE: Final[int] = 21
"""The phase that established this manifest."""

DIGEST_PREFIX: Final[str] = "sha256:"
DIGEST_KEY: Final[str] = "digest"
"""The one key the digest does not cover, because it holds the digest."""

MANIFEST_NAME: Final[str] = "bootstrap-manifest.json"
"""What the evidence file is called inside the declared evidence root."""

REASON_MANIFEST_NONDETERMINISTIC: Final[str] = "BOOTSTRAP_MANIFEST_NONDETERMINISTIC"
"""Two renderings of one run disagreed, so the digest means nothing."""


def reason_for(identifier: str) -> str:
    """The reason code a failing check contributes.

    Args:
        identifier: The check identifier, in ``area.subject`` form.

    Returns:
        ``BOOTSTRAP_AREA_SUBJECT``.

    Derived rather than declared. A hand-written table would need an entry per
    check and would go stale the first time a phase added one; deriving it means
    the reason set is complete by construction and a new check cannot arrive
    without its code.
    """
    return "BOOTSTRAP_" + identifier.upper().replace(".", "_")


def reasons() -> frozenset[str]:
    """Every reason this manifest can record.

    Returns:
        One code per registered check, plus the one intrinsic code that is about
        the manifest rather than about the host.

    A function rather than a constant, because ``frozenset(...)`` is a call and a
    layer package performs none at import — the same rule that makes
    :func:`~globin.domain.bootstrap.checks` a function.
    """
    return frozenset(
        {reason_for(spec.identifier) for spec in checks()} | {REASON_MANIFEST_NONDETERMINISTIC}
    )


class BootstrapManifestError(ConfigurationError):
    """A bootstrap manifest could not be read, or disagrees with itself.

    A :class:`~globin.errors.ConfigurationError` rather than a validation one:
    the reader did nothing wrong, and what must change is a file on disk.
    """


# ---------------------------------------------------------------------------
# Turning real paths into recordable ones
# ---------------------------------------------------------------------------


def record(path: Path | None, *, root: Path | None) -> RecordedPath:
    """Describe a path in a form that is safe to publish.

    Args:
        path: The path, or ``None``.
        root: The project root, or ``None`` when it was never found — in which
            case nothing can be inside it.

    Returns:
        A :class:`~globin.domain.bootstrap.RecordedPath`.

    Three outcomes and no fourth, which the returned type enforces. A path inside
    the project is recorded relative to it, because that is both meaningful and
    identical on every machine; a path outside is recorded as a fingerprint,
    because it is exactly the kind of value that carries an account name.
    """
    if path is None:
        return recorded_absent()
    if root is None:
        return recorded_outside(str(path))
    try:
        relative = path.relative_to(root)
    except ValueError:
        return recorded_outside(str(path))
    spelling = relative.as_posix()
    return recorded_inside(spelling) if spelling not in {"", "."} else recorded_inside(".")


def find_project_root(start: Path) -> Path | None:
    """Search upwards for the directory holding this project's ``pyproject.toml``.

    Args:
        start: Where to begin. Already resolved.

    Returns:
        The project root, or ``None`` when the search found none.

    Bounded by :data:`~globin.domain.bootstrap.MAX_ROOT_SEARCH_DEPTH`. An
    unbounded walk finds *a* project file eventually on most machines, and which
    one it finds depends on where the command was typed — which is the ambiguity
    this phase exists to remove.

    A ``pyproject.toml`` that names some other project is not this project's
    root, so the search reads the file rather than trusting the filename. That is
    what makes a checkout nested inside an unrelated repository work correctly
    instead of silently borrowing its parent.
    """
    for candidate in (start, *start.parents)[: MAX_ROOT_SEARCH_DEPTH + 1]:
        if _declares_this_project(candidate / PROJECT_FILE):
            return candidate
    return None


def _declares_this_project(path: Path) -> bool:
    """Whether a ``pyproject.toml`` names this project.

    Args:
        path: The candidate file.

    Returns:
        ``True`` when it parses and its ``project.name`` is this package.

    An unreadable or malformed file is not this project's, rather than an error.
    The search is walking through directories it does not own, and one of them
    holding a broken project file is not a reason to refuse to look further.
    """
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = document.get("project")
    return isinstance(project, dict) and project.get("name") == PACKAGE_NAME


# ---------------------------------------------------------------------------
# The probes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TomlRuntimeBaselineSource:
    """Reads the declared baseline from ``runtime-contract.toml``.

    Args:
        path: The declaration. Given rather than guessed, for the reason
            ``globin.adapters.configuration`` gives about its own: searching for
            a file settles by accident where a file should live.
    """

    path: Path

    def baseline(self) -> RuntimeBaseline:
        """Read and parse the declaration.

        Returns:
            The parsed contract.

        Raises:
            ConfigurationError: If it is missing, malformed, or does not carry
                every field the bootstrap judges against.
        """
        try:
            with self.path.open("rb") as handle:
                document = tomllib.load(handle)
        except OSError as fault:
            msg = f"the runtime contract at {RUNTIME_CONTRACT_PATH} could not be read: {fault}"
            raise ConfigurationError(msg) from fault
        except tomllib.TOMLDecodeError as fault:
            msg = f"the runtime contract at {RUNTIME_CONTRACT_PATH} is not valid TOML: {fault}"
            raise ConfigurationError(msg) from fault
        return parse_baseline(document)


def parse_baseline(document: Mapping[str, object]) -> RuntimeBaseline:
    """Build a baseline from a parsed runtime contract.

    Args:
        document: The parsed TOML.

    Returns:
        The baseline.

    Raises:
        ConfigurationError: If a table or a field is missing, or has the wrong
            type. Nothing is defaulted: a contract with a hole in it has not
            declared the thing the hole was for.

    Separated from the reading so that every malformed shape is reachable from a
    literal rather than from a fixture file.
    """
    interpreter = _table(document, "interpreter")
    host = _table(document, "host")
    environment = _table(document, "environment")
    return RuntimeBaseline(
        system=_text(host, "system", "host"),
        minimum_release=_text(host, "minimum_release", "host"),
        implementation=_text(interpreter, "implementation", "interpreter"),
        minor_line=_text(interpreter, "minor_line", "interpreter"),
        minimum_patch=_text(interpreter, "minimum_patch", "interpreter"),
        architecture=_text(interpreter, "architecture", "interpreter"),
        pointer_bits=_integer(interpreter, "pointer_bits", "interpreter"),
        free_threaded=_flag(interpreter, "free_threaded", "interpreter"),
        allow_prerelease=_flag(interpreter, "allow_prerelease", "interpreter"),
        environment_directory=_text(environment, "directory", "environment"),
    )


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    """One table from the contract.

    Args:
        document: The parsed TOML.
        name: The table name.

    Returns:
        The table.

    Raises:
        ConfigurationError: If it is missing or is not a table.
    """
    value = document.get(name)
    if not isinstance(value, Mapping):
        msg = f"the runtime contract has no [{name}] table"
        raise ConfigurationError(msg)
    return value


def _text(table: Mapping[str, object], key: str, name: str) -> str:
    """One string field.

    Args:
        table: The table it lives in.
        key: The field name.
        name: The table's name, for the message.

    Returns:
        The value.

    Raises:
        ConfigurationError: If it is missing or is not a string.
    """
    value = table.get(key)
    if not isinstance(value, str):
        msg = f"the runtime contract's [{name}] table has no string {key!r}"
        raise ConfigurationError(msg)
    return value


def _integer(table: Mapping[str, object], key: str, name: str) -> int:
    """One integer field.

    Args:
        table: The table it lives in.
        key: The field name.
        name: The table's name, for the message.

    Returns:
        The value.

    Raises:
        ConfigurationError: If it is missing or is not an integer.

    A boolean is refused explicitly. Python makes ``True`` an integer, so a
    contract saying ``pointer_bits = true`` would otherwise be accepted and then
    compared against 64.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"the runtime contract's [{name}] table has no integer {key!r}"
        raise ConfigurationError(msg)
    return value


def _flag(table: Mapping[str, object], key: str, name: str) -> bool:
    """One boolean field.

    Args:
        table: The table it lives in.
        key: The field name.
        name: The table's name, for the message.

    Returns:
        The value.

    Raises:
        ConfigurationError: If it is missing or is not a boolean.
    """
    value = table.get(key)
    if not isinstance(value, bool):
        msg = f"the runtime contract's [{name}] table has no boolean {key!r}"
        raise ConfigurationError(msg)
    return value


@dataclass(frozen=True, slots=True)
class SystemHostProbe:
    """Reads the machine and the interpreter this process is running on.

    Args:
        root: The project root, or ``None`` when it was not found. Every observed
            path is recorded against it, so a probe with no root records every
            path as outside — which is true, and which is why it is not an error.
    """

    root: Path | None

    def host(self) -> HostFacts:
        """Read what this machine is.

        Returns:
            The operating system, its release, the architecture and the pointer
            width.

        Windows reports its release through :func:`platform.release`, and
        :func:`platform.machine` reports ``AMD64`` there rather than ``x86_64``.
        Neither is normalised here: normalising an observation is editing it, and
        the comparison belongs to the judgement.
        """
        return HostFacts(
            system=platform.system(),
            release=platform.release(),
            machine=platform.machine(),
            pointer_bits=struct.calcsize("P") * 8,
        )

    def interpreter(self) -> InterpreterFacts:
        """Read what this Python is.

        Returns:
            The implementation, version, build and the three paths that decide
            which environment it belongs to.

        ``sys.prefix`` differing from ``sys.base_prefix`` is what a virtual
        environment *is*, so that comparison is the measurement rather than a
        heuristic about directory names.
        """
        info = sys.version_info
        return InterpreterFacts(
            implementation=sys.implementation.name,
            version=f"{info.major}.{info.minor}.{info.micro}",
            release_level=info.releaselevel,
            free_threaded=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            executable=record(Path(sys.executable).resolve(), root=self.root),
            prefix=record(Path(sys.prefix).resolve(), root=self.root),
            base_prefix=record(Path(sys.base_prefix).resolve(), root=self.root),
            in_virtual_environment=sys.prefix != sys.base_prefix,
        )


@dataclass(frozen=True, slots=True)
class FilesystemProjectProbe:
    """Locates the project and reads its identity.

    Args:
        location: Where the root was found, or ``None``. Named for what it holds
            rather than for the port's ``root`` method, because a field and a
            method cannot share one name and the method is the part a caller
            reads.
        started_from: Where the search began, for the failure message.
        version_from_package: The imported package's ``__version__``, used when
            no installed distribution can supply one. Passed in rather than read
            here so that both branches are reachable in a test.
    """

    location: Path | None
    started_from: Path
    version_from_package: str | None = None

    def root(self) -> RecordedPath:
        """Where the project root was found.

        Returns:
            The root, recorded — which for the root itself is always ``"."``.
        """
        if self.location is None:
            return recorded_absent()
        return recorded_inside(".")

    def origin(self) -> str:
        """How the search started.

        Returns:
            A phrase completing "no project root was found ...".

        The starting directory is recorded rather than spelled out, for the same
        reason every other path here is: it is a working directory, and a working
        directory on a personal machine names its owner.
        """
        recorded = record(self.started_from, root=self.location)
        if recorded.location is PathLocation.REPOSITORY:
            return f"searching upwards from {recorded.path!r} inside the project"
        return "searching upwards from the working directory"

    def identity(self) -> ProjectIdentity | None:
        """Read which GLOBIN this is.

        Returns:
            The name, version and where the version came from, or ``None`` when
            neither installed metadata nor the imported package could supply one.

        Installed metadata is preferred because it describes what was installed.
        The package attribute is the fallback and is reported as such, because on
        a development machine the source tree can be newer than what is installed
        and a reader deserves to know which of the two they are being told about.
        """
        try:
            return ProjectIdentity(
                name=PACKAGE_NAME,
                version=metadata.version(PACKAGE_NAME),
                source="metadata",
            )
        except metadata.PackageNotFoundError:
            if self.version_from_package is None:
                return None
            return ProjectIdentity(
                name=PACKAGE_NAME,
                version=self.version_from_package,
                source="package",
            )


def normalise(name: str) -> str:
    """Normalise a distribution name for comparison.

    Args:
        name: The name as it was written.

    Returns:
        Lower-cased, with every run of ``-``, ``_`` and ``.`` collapsed to a
        single ``-``, as PEP 503 specifies.

    Kept as a name and re-exported rather than deleted, because call sites and
    tests import it from here. The implementation moved to
    :func:`globin.domain.dependency.canonical_name` in Phase 029, which delegates
    to ``packaging``.

    This function's previous docstring said it was "written out rather than
    imported" because ADR-0003 made the empty runtime dependency list an
    invariant and "a normalisation rule of four lines is not a reason to spend
    it". That reasoning was right and is now spent for a different reason: the
    repository needed PEP 440, PEP 508 and PEP 751 as well, and one library
    supplies all four.
    """
    return canonical_name(name)


def distribution_name(requirement: str) -> str:
    """The distribution a requirement string names.

    Args:
        requirement: A PEP 508 requirement, such as ``"pandas>=2.2; python_version
            >= '3.12'"``.

    Returns:
        Its normalised distribution name, with any extras, version specifier and
        environment marker removed, or empty when the requirement is malformed.

    **This is the parser its own predecessor predicted.** That version split on
    eight separator characters and said it "must not become" a requirement
    parser, "because the moment it needs to be right about markers it needs
    ``packaging`` and the zero-dependency invariant is gone". Phase 029 spent the
    invariant deliberately, and being right about markers is exactly what the
    dependency inventory needs.

    The substantive change is not tidiness. The old splitter returned a name for
    input no requirement grammar accepts, so a malformed ``pyproject.toml`` line
    produced a plausible distribution name and a start-up check that reported a
    package missing which had never been declared. This returns empty instead,
    and the inventory skips it.
    """
    return requirement_name(requirement)


@dataclass(frozen=True, slots=True)
class DeclaredDependencyProbe:
    """Reports what ``pyproject.toml`` declares and what is installed.

    Args:
        project_file: The project manifest.
        lock_file: Where the runtime lock would be.
        installed: Supplies every distribution name this interpreter can see,
            normalised. A callable rather than a value for two reasons: the scan
            then happens when the check runs rather than when the object is
            built, which keeps the composition root's "constructing performs no
            work" property; and a test substitutes an environment without having
            to install anything into one.

    Nothing is resolved and no index is consulted. Start-up must work without a
    network, which means the only question this may ask is the local one.
    """

    project_file: Path
    lock_file: Path
    installed: Callable[[], Mapping[str, str]]
    environment: Callable[[], Mapping[str, str]] = marker_environment

    def readiness(self) -> DependencyReadiness:
        """Read the state of the declared runtime dependencies.

        Returns:
            The declared set, whether a runtime lock accompanies it, and which
            declared distributions this interpreter cannot see.

        An unreadable project file yields an empty declaration rather than an
        exception. The check that consumes this cannot distinguish "declares
        nothing" from "could not be read", so ``project.root`` is what refuses
        first — and it already has.
        """
        present = self.installed()
        requirements = self._requirements()
        declared = tuple(sorted({distribution_name(item) for item in requirements} - {""}))
        missing = tuple(name for name in declared if name not in present)
        return DependencyReadiness(
            declared=declared,
            locked=self.lock_file.is_file(),
            missing=missing,
            inventory=self._inventory(requirements, present),
        )

    def _inventory(
        self, requirements: tuple[str, ...], present: Mapping[str, str]
    ) -> DependencyInventory:
        """Compare the lock against this environment.

        Args:
            requirements: The raw requirement strings, as declared.
            present: Canonical distribution name to installed version.

        Returns:
            The inventory. A lock that is absent or unreadable produces one
            saying so rather than nothing at all, because "there is no lock" is
            an answer the check needs and ``None`` would lose it.
        """
        try:
            text = self.lock_file.read_text(encoding="utf-8")
        except OSError:
            reading = LockReading(state=LockState.ABSENT)
        else:
            reading = read_lock(text)
        environment = self.environment()
        return inventory_from(
            declared=requirements,
            reading=reading,
            installed=present,
            environment=environment,
            python_version=python_full_version(environment),
        )

    def _requirements(self) -> tuple[str, ...]:
        """Every requirement string ``project.dependencies`` holds, verbatim.

        Returns:
            The strings as written, markers and specifiers intact.

        Verbatim rather than reduced to names, because the inventory needs the
        marker to decide whether an entry applies on this platform at all. The
        predecessor of this method returned names and threw the rest away, which
        is why a marked dependency would have been reported missing here.
        """
        try:
            with self.project_file.open("rb") as handle:
                document = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return ()
        project = document.get("project")
        if not isinstance(project, dict):
            return ()
        dependencies = project.get("dependencies")
        if not isinstance(dependencies, list):
            return ()
        return tuple(item for item in dependencies if isinstance(item, str))


def installed_distributions() -> frozenset[str]:
    """Every distribution this interpreter can import metadata for.

    Returns:
        Their normalised names.

    Read through :mod:`importlib.metadata` rather than by running ``pip list``:
    it is the standard library's own view of the environment it is running in,
    needs no child process, and therefore cannot become a network call by
    accident.

    Kept, and now derived from :func:`globin.adapters.dependency.installed_versions`
    so that one scan answers both questions. **This function is why Phase 029
    exists**: it walked every distribution's metadata and then discarded
    ``distribution.version``, so a package installed at a version the lock does
    not name was reported present and correct. Callers wanting the versions
    should ask for them directly rather than through this.
    """
    return frozenset(installed_versions())


@dataclass(frozen=True, slots=True)
class StoreBackedSecrets:
    """Reports readiness by asking the real store about the required references.

    Args:
        store: The local secret store.
        required: The references a start-up must resolve. **Empty today**, and
            empty because GLOBIN holds no credentials rather than by omission — it
            opens no authenticated connection, so the set is genuinely nothing.
            Phase 034 gave it a transport and left this untouched: the three
            requests it can send are public, and a public request reads no secret.

    Phase 028 replaced :class:`NoSecretsRequired` with this, which is what the
    port existed for. The behaviour with an empty ``required`` set is identical
    to what that class did — a vacuous pass — so nothing observable changed on a
    host with no credentials, and everything changed for the phase that fills
    the set in.

    **Phase 029 populated it, and it is still empty.** That is not a
    contradiction: what changed is that the emptiness became a *derivation*
    rather than a literal. The composition root now feeds
    :func:`globin.domain.entitlements.required_references` into this field, and
    that function returns nothing because GLOBIN reaches no venue and therefore
    genuinely requires no credential at start-up. Phase 038 brings the first
    authenticated surface; adding one entry to the registry is all it will take
    for this check to begin demanding a credential, with no plumbing in between.

    Declaring one now would make ``bootstrap check`` refuse on every clean host,
    including the one CI builds, and the only way to satisfy it would be to
    manufacture a credential to meet a requirement nothing has established.
    """

    store: SecretStore
    required: tuple[SecretReference, ...] = ()

    def readiness(self) -> SecretReadiness:
        """Read the state of the required secret references.

        Returns:
            The readiness, naming the required references and any that did not
            resolve. No value is read, returned or held — resolution is asked
            for its *outcome* only.
        """
        return readiness(self.store, self.required)


@dataclass(frozen=True, slots=True)
class RegisterBackedEntitlements:
    """Reports whether required credentials are permitted, from the register.

    Args:
        register: Where declarations are kept.
        requirements: What start-up demands. **Empty today**, and empty because
            GLOBIN reaches no venue rather than by omission.

    **The store is never consulted.** An entitlement is decided from what is
    demanded and what is declared, and both are ordinary data. Whether the
    credential also *resolves* is ``secrets.required``'s question, and answering
    two questions in one probe would make a missing credential and an
    over-narrow one indistinguishable.
    """

    register: GrantRegister
    requirements: tuple[CredentialRequirement, ...] = ()

    def readiness(self) -> EntitlementReadiness:
        """Verify every requirement against what is declared.

        Returns:
            What was demanded, what was refused, and each verdict's state. No
            value is read, returned or held.
        """
        verdicts = entitlement(self.requirements, self.register.declarations())
        demanded = tuple(sorted(verdict.reference.name for verdict in verdicts))
        refused = tuple(
            sorted(verdict.reference.name for verdict in verdicts if not verdict.permitted)
        )
        states = tuple(
            sorted((verdict.reference.name, verdict.state.value) for verdict in verdicts)
        )
        return EntitlementReadiness(demanded=demanded, refused=refused, states=states)


@dataclass(frozen=True, slots=True)
class SystemEnvironmentProbe:
    """Measures this host's capabilities through the architecture and toolchain probes.

    Args:
        api: How to ask the operating system about processor architecture.
        toolchain: How to ask whether an executable resolves.
        declared: Which executables to look for, and why each is listed.

    A thin seam. Every judgement lives in
    :mod:`globin.application.environment` and every observation in
    :mod:`globin.adapters.environment`; this exists so that
    :class:`~globin.application.bootstrap.BootstrapPipeline` holds one port for
    the question rather than three, and so that a test can substitute the whole
    capability answer without assembling two fakes.
    """

    api: WindowsSystemApi
    toolchain: ToolchainProbe
    declared: tuple[tuple[str, str], ...]

    def snapshot(self, baseline: RuntimeBaseline) -> EnvironmentCapabilitySnapshot:
        """Measure every declared capability against the contract.

        Args:
            baseline: The contract, as the run already parsed it.

        Returns:
            The snapshot.
        """
        return snapshot_from(
            api=self.api,
            probe=self.toolchain,
            baseline=baseline,
            declared_toolchain=self.declared,
        )


@dataclass(frozen=True, slots=True)
class ProjectRuntimeTree:
    """Creates the permitted runtime roots and checks the rest.

    Args:
        root: The project root.

    Only the roots in :data:`~globin.domain.bootstrap.CREATED_PATHS` are brought
    into existence. Everything else is a reservation, and creating one would be
    making the claim ``REPOSITORY_LAYOUT.md`` refuses — that a capability nobody
    has built is being worked on.
    """

    root: Path

    def prepare(self, paths: RuntimePaths) -> tuple[str, ...]:
        """Create what may be created, and report what cannot be used.

        Args:
            paths: The declared tree, relative to the project root.

        Returns:
            One sentence per declared root that cannot be used.

        A declared root that resolves outside the project is refused before
        anything is created. The values come from a frozen dataclass with sane
        defaults, so this cannot happen today — which is exactly when a boundary
        check is cheap to add and worth having, because the day it can happen is
        the day nobody is looking.
        """
        problems: list[str] = []
        for name, relative in sorted(paths.declared().items()):
            target = (self.root / relative).resolve()
            if not target.is_relative_to(self.root):
                problems.append(f"the {name} root resolves outside the project")
                continue
            if target.exists() and not target.is_dir():
                problems.append(f"the {name} root exists and is not a directory")
                continue
            if name in CREATED_PATHS:
                problems.extend(_create(target, name))
        return tuple(problems)


def _create(target: Path, name: str) -> tuple[str, ...]:
    """Bring one root into existence.

    Args:
        target: Where it goes.
        name: Which declared root this is, for the message.

    Returns:
        Empty when it exists afterwards, otherwise one sentence saying why not.
    """
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as fault:
        return (f"the {name} root could not be created: {fault.strerror or fault}",)
    return ()


# ---------------------------------------------------------------------------
# The evidence
# ---------------------------------------------------------------------------


def render(document: Mapping[str, object]) -> str:
    """Encode a manifest so that two writers cannot disagree about bytes.

    Args:
        document: The manifest.

    Returns:
        One line of JSON followed by a newline — sorted keys, no incidental
        whitespace, ASCII only, exactly as every manifest under ``.globin`` does
        it.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def digest(document: Mapping[str, object]) -> str:
    """The stable identity of a manifest's contents.

    Args:
        document: The manifest.

    Returns:
        ``"sha256:"`` followed by 64 lowercase hexadecimal characters, taken over
        everything except the digest field.
    """
    payload = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return DIGEST_PREFIX + hashlib.sha256(render(payload).encode("utf-8")).hexdigest()


def build(outcome: BootstrapOutcome) -> dict[str, object]:
    """Assemble a manifest for one bootstrap run, and seal it.

    Args:
        outcome: What the run concluded.

    Returns:
        The sealed manifest.

    Every value passes through :func:`globin.domain.observability.redact` before
    it is placed, so a field whose *name* looks like a credential is replaced
    whatever produced it. Nothing in a bootstrap manifest should trip that today;
    the point is that it keeps being true when a later phase adds a section here
    without reading this docstring.
    """
    document: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "observed": redact(dict(outcome.observed or {})),
        "checks": [check.as_record() for check in outcome.report.outcomes],
        "verdict": {
            "ready": outcome.ready,
            "exit_code": int(outcome.exit_code),
            "reasons": sorted(
                reason_for(check.identifier)
                for check in outcome.report.outcomes
                if check.status in {CheckStatus.FAIL, CheckStatus.UNMEASURED}
            ),
            "fingerprint": (outcome.context.fingerprint if outcome.context is not None else None),
            "readiness": readiness_for(outcome.exit_code).value,
        },
    }
    document[DIGEST_KEY] = digest(document)
    return document


def load(text: str) -> dict[str, object]:
    """Read a manifest back, refusing one that disagrees with itself.

    Args:
        text: The file's contents.

    Returns:
        The manifest.

    Raises:
        BootstrapManifestError: If it is not JSON, not an object, not this
            schema, not this version, or has been edited since it was written.

    Five refusals in a fixed order, each with its own message, because "this file
    is wrong" is a diagnosis nobody can act on.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the bootstrap manifest is not valid JSON: {fault}"
        raise BootstrapManifestError(msg) from fault
    if not isinstance(parsed, dict):
        msg = "the bootstrap manifest must be a JSON object"
        raise BootstrapManifestError(msg)
    if parsed.get("schema") != SCHEMA:
        msg = f"this is not a {SCHEMA} document"
        raise BootstrapManifestError(msg)
    if parsed.get("schema_version") != SCHEMA_VERSION:
        msg = (
            f"the bootstrap manifest declares schema version {parsed.get('schema_version')!r} "
            f"and this reader understands {SCHEMA_VERSION}. "
            "Regenerate it rather than reading it anyway."
        )
        raise BootstrapManifestError(msg)
    document: dict[str, object] = parsed
    if document.get(DIGEST_KEY) != digest(document):
        msg = "the bootstrap manifest has been edited or truncated since it was written"
        raise BootstrapManifestError(msg)
    return document


def write(outcome: BootstrapOutcome, *, root: Path, paths: RuntimePaths) -> RecordedPath:
    """Write one run's evidence into the declared evidence root.

    Args:
        outcome: What the run concluded.
        root: The project root.
        paths: The declared tree.

    Returns:
        Where the manifest was written, recorded.

    Raises:
        BootstrapManifestError: If two renderings of the same run disagree, which
            would make the digest meaningless.
        OSError: If the file could not be written. Left to the caller, which is
            the layer that knows whether a missing artefact is fatal.

    Determinism is checked rather than assumed. Rendering twice and comparing
    costs microseconds and catches the class of bug — an unsorted set, a mapping
    iterated in insertion order — that makes a digest a decoration.
    """
    rendered = render(build(outcome))
    if rendered != render(build(outcome)):
        msg = (
            f"two renderings of one bootstrap run disagreed ({REASON_MANIFEST_NONDETERMINISTIC}), "
            "so its digest would identify nothing"
        )
        raise BootstrapManifestError(msg)
    directory = (root / paths.evidence).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MANIFEST_NAME
    target.write_text(rendered, encoding="utf-8", newline="\n")
    return record(target, root=root)
